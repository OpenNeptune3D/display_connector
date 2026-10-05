import logging
import asyncio
from unittest.mock import AsyncMock, Mock, patch
import pytest

from src.communicator import DisplayCommunicator


@pytest.fixture
def communicator():
    # event_handler can be None for these unit tests, since we patch out I/O
    return DisplayCommunicator(logging, "N3", "/dev/ttyS0", None)


def test_get_device_name(communicator):
    # Simple sanity check: constructor stores the model name
    assert communicator.get_device_name() == "N3"


def test_get_display_type_name(communicator):
    # Should just be the class name
    assert communicator.get_display_type_name() == "DisplayCommunicator"


@pytest.mark.asyncio
async def test_navigate(communicator):
    # We don't want real I/O here, so patch write
    communicator.write = AsyncMock()

    await communicator.navigate_to("1")

    # navigate_to blocks other writes with a blocked_key="__nav__"
    communicator.write.assert_awaited_once_with(
        "page 1",
        blocked_key="__nav__",
        auto_unblock=False,
    )


def test_encoding_is_passed_to_client_constructor():
    with patch('src.communicator.TJCClient') as client:
        DisplayCommunicator(logging, 'N4', '/dev/not-opened', None)
    client.assert_called_once_with('/dev/not-opened', 115200, None, encoding='ascii')


@pytest.mark.asyncio
async def test_direct_write_and_queued_write_both_convert(communicator):
    communicator.display.command = AsyncMock(return_value=True)
    communicator.logger = Mock()
    await communicator.write('main.t.txt="265°C"')
    communicator.blocked_by = 'image'
    await communicator.write('main.t.txt="pièce.gcode"')
    assert communicator.display.command.await_count == 1
    await communicator.unblock('image')
    assert [c.args[0] for c in communicator.display.command.await_args_list] == [
        'main.t.txt="265 C"', 'main.t.txt="piece.gcode"',
    ]
    assert communicator.logger.info.call_count == 1
    communicator.logger.warning.assert_not_called()


@pytest.mark.asyncio
async def test_encoding_diagnostics_are_bounded_without_rewriting_syntax(communicator):
    communicator.display.command = AsyncMock()
    communicator.logger = Mock()
    with patch('src.communicator.time.monotonic', side_effect=[0, 1, 2, 60]):
        for _ in range(4):
            await communicator.write('n0.val=−5')
    communicator.display.command.assert_not_awaited()
    assert communicator.logger.warning.call_count == 2
    assert communicator.logger.warning.call_args.args[2] == 2


@pytest.mark.asyncio
async def test_timeout_still_triggers_reconnect(communicator):
    communicator.display.command = AsyncMock(side_effect=asyncio.TimeoutError)
    communicator.display.reconnect = AsyncMock()
    communicator.logger = Mock()
    await communicator.write('page 1')
    communicator.display.reconnect.assert_awaited_once()
    communicator.logger.warning.assert_called_once()


@pytest.mark.asyncio
async def test_real_nextion_encoding_with_simulated_transport(communicator):
    # Keep the real Nextion command/encoding path. Only transport and the
    # acknowledgement are simulated; no serial port is ever opened.
    connection = Mock()
    connection.read_no_wait.side_effect = asyncio.QueueEmpty
    communicator.display._connection = connection
    communicator.display._read_packet = AsyncMock(return_value=b'\x01')
    communicator.logger = Mock()
    await communicator.write('main.t.txt="265°C - pièce 🙂"')
    connection.write.assert_called_once_with(b'main.t.txt="265 C - piece ?"')
    communicator.logger.warning.assert_not_called()
