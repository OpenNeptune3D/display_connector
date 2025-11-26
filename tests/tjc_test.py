from unittest.mock import MagicMock

import pytest
from src.tjc import EventType, TJCClient, TJCNumericInputPayload, TJCProtocol, TJCTouchCoordinatePayload, TJCTouchDataPayload


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
