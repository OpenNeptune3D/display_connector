import asyncio
from unittest.mock import MagicMock

import pytest
from unittest.mock import call

from src.tjc import EventType, TJCClient, TJCNumericInputPayload, TJCProtocol, TJCStringInputPayload, TJCTouchCoordinatePayload, TJCTouchDataPayload


@pytest.fixture(autouse=True)
def ensure_event_loop():
    """Provide an event loop for sync tests that instantiate TJCProtocol.

    NextionProtocol.__init__ (upstream) calls asyncio.get_event_loop().create_future(),
    which raises RuntimeError in Python 3.10+ when no loop is set in the current thread.
    Async tests (marked with @pytest.mark.asyncio) get their own loop from pytest-asyncio;
    this fixture guarantees sync tests have one too.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)


def test_is_event():
    protocol = TJCProtocol(None)
    assert protocol.is_event(b"\x65") is True
    assert protocol.is_event(b"\x71") is False
    assert protocol.is_event(b"\x72") is True

def test_data_received_touch_event():
    m = MagicMock()
    protocol = TJCProtocol(m)
    protocol.data_received(b"\x65\xF1\x02\xFF\xFF\xFF\xFF")
    m.assert_called_once_with(b"\x65\xF1\x02")

def test_data_received_number():
    m = MagicMock()
    protocol = TJCProtocol(m)
    # 0x72 packet: 1 header + 2 (page, component) + 2 (value) + 3 EOL = 8 bytes total
    protocol.data_received(b"\x72\xF1\x02\x03\x05\xFF\xFF\xFF")
    # Handler should see the message without the EOL bytes
    m.assert_called_once_with(b"\x72\xF1\x02\x03\x05")

#def test_data_received_number():
#    m = MagicMock()
#    protocol = TJCProtocol(m)
#    protocol.data_received(b"\x72\xF1\x02\x03\x05\x04\xFF\xFF\xFF")
#    m.assert_called_once_with(b"\x72\xF1\x02\x03\x05\x04")


def test_data_received_number_broken():
    m = MagicMock()
    protocol = TJCProtocol(m)
    protocol.data_received(b"\x71\xF1\x02\x03\x05")
    m.assert_called_once_with(b"\x72\xF1\x02\x03\x05")


@pytest.mark.asyncio
async def test_data_received_variable():
    m = MagicMock()
    protocol = TJCProtocol(m)
    protocol.data_received(b"\x70\x10\x20\x30\x40\xFF\xFF\xFF")
    item = await protocol.queue.get()
    assert item == b"\x70\x10\x20\x30\x40"


@pytest.mark.asyncio
async def test_keyboard_text_has_no_terminator():
    """keybdA's OK sends 0x70 <page> <component> <text> with no 0xFF 0xFF 0xFF."""
    m = MagicMock()
    protocol = TJCProtocol(m)
    protocol.data_received(b"\x70\x84\x01ab")
    protocol.data_received(b"1")
    m.assert_not_called()
    await asyncio.sleep(TJCProtocol.TEXT_INPUT_SETTLE + 0.1)
    m.assert_called_once_with(b"\x70\x84\x01ab1")
    assert protocol.buffer == b""


@pytest.mark.asyncio
async def test_keyboard_text_followed_by_touch_before_flush():
    """A tap right after OK glues its bytes onto the text; both must come out."""
    m = MagicMock()
    protocol = TJCProtocol(m)
    protocol.data_received(b"\x70\x84\x01ab1\x67\x00\x9a\x00\x6e\x01\xFF\xFF\xFF")
    await asyncio.sleep(TJCProtocol.TEXT_INPUT_SETTLE + 0.1)
    assert m.call_args_list == [
        call(b"\x70\x84\x01ab1"),
        call(b"\x67\x00\x9a\x00\x6e\x01"),
    ]
    assert protocol.buffer == b""


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [b"\x01", b"\x1a"])
async def test_keyboard_text_followed_by_command_reply_before_flush(reply):
    """A write acknowledged while the text arrives glues its reply onto the text.

    Seen on a Neptune 4 Pro: a status update's 0x01 ended up in the password and
    the write timed out, which made the connector reconnect to the display.
    """
    m = MagicMock()
    protocol = TJCProtocol(m)
    protocol.data_received(b"\x70\x84\x03ab1" + reply + b"\xFF\xFF\xFF")
    await asyncio.sleep(TJCProtocol.TEXT_INPUT_SETTLE + 0.1)
    m.assert_called_once_with(b"\x70\x84\x03ab1")
    assert await protocol.queue.get() == reply
    assert protocol.buffer == b""


@pytest.mark.asyncio
async def test_empty_keyboard_text_keeps_its_header():
    m = MagicMock()
    protocol = TJCProtocol(m)
    protocol.data_received(b"\x70\x84\x03\x01\xFF\xFF\xFF")
    await asyncio.sleep(TJCProtocol.TEXT_INPUT_SETTLE + 0.1)
    m.assert_called_once_with(b"\x70\x84\x03")
    assert await protocol.queue.get() == b"\x01"


@pytest.mark.asyncio
async def test_get_text_reply_is_not_keyboard_text():
    m = MagicMock()
    protocol = TJCProtocol(m)
    protocol.data_received(b"\x70Settings\xFF\xFF\xFF")
    assert await protocol.queue.get() == b"\x70Settings"
    m.assert_not_called()


def test_event_string_input():
    m = MagicMock()
    client = TJCClient(None)
    client._schedule_event_message_handler = m
    client.event_message_handler(b"\x70\x84\x01my pass.1")
    m.assert_called_once_with(EventType.STRING_INPUT, TJCStringInputPayload(page_id=132, component_id=1, string="my pass.1"))


def test_event_touch_coordinate():
    m = MagicMock()
    client = TJCClient(None)
    client._schedule_event_message_handler = m
    client.event_message_handler(b"\x67\xF1\x02\x30\x20\x01")
    m.assert_called_once_with(EventType.TOUCH_COORDINATE, TJCTouchCoordinatePayload(x=61698, y=12320, touch_event=1))


def test_event_touch():
    m = MagicMock()
    client = TJCClient(None)
    client._schedule_event_message_handler = m
    client.event_message_handler(b"\x65\x02\x15")
    m.assert_called_once_with(EventType.TOUCH, TJCTouchDataPayload(page_id=2, component_id=21))


def test_numeric_input():
    m = MagicMock()
    client = TJCClient(None)
    client._schedule_event_message_handler = m
    client.event_message_handler(b"\x72\x03\x15\x10\x08")
    m.assert_called_once_with(EventType.NUMERIC_INPUT, TJCNumericInputPayload(page_id=3, component_id=21, value=2064))


def test_event_slider():
    m = MagicMock()
    client = TJCClient(None)
    client._schedule_event_message_handler = m
    client.event_message_handler(b"\x72\x03\x16\x10\x09")
    m.assert_called_once_with(EventType.NUMERIC_INPUT, TJCNumericInputPayload(page_id=3, component_id=22, value=2320))


@pytest.mark.asyncio
async def test_connect_drains_serial_port_before_probing():
    from unittest.mock import AsyncMock, patch
    from nextion.exceptions import ConnectionFailed

    client = TJCClient("/dev/ttyS1", 115200)
    calls = []
    client._try_connect_on_different_baudrates = AsyncMock(
        side_effect=lambda: calls.append("probe") or (_ for _ in ()).throw(ConnectionFailed("No baud rate suited"))
    )
    with patch("src.tjc.serial.serial_for_url") as serial_for_url:
        port = serial_for_url.return_value.__enter__.return_value
        port.reset_input_buffer.side_effect = lambda: calls.append("drain")
        with pytest.raises(ConnectionFailed):
            await client.connect()

    serial_for_url.assert_called_once_with("/dev/ttyS1", baudrate=115200, timeout=0)
    port.write.assert_called_once_with(b"\xff\xff\xff")
    assert calls == ["drain", "drain", "probe"]


def test_drain_serial_port_ignores_missing_port():
    client = TJCClient("/dev/does-not-exist", 115200)
    client._drain_serial_port()  # must not raise; connect() reports the real error
