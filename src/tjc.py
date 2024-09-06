import struct
from collections import namedtuple
from enum import IntEnum
from nextion import Nextion
from nextion.protocol.nextion import NextionProtocol
from nextion.exceptions import CommandTimeout, ConnectionFailed

# Named tuples for various payloads
TJCTouchDataPayload = namedtuple("Touch", "page_id component_id")
TJCStringInputPayload = namedtuple("String", "page_id component_id string")
TJCNumericInputPayload = namedtuple("Numeric", "page_id component_id value")
TJCTouchCoordinatePayload = namedtuple("TouchCoordinate", "x y touch_event")

# Enum for event types
class EventType(IntEnum):
    TOUCH = 0x65
    TOUCH_COORDINATE = 0x67
    TOUCH_IN_SLEEP = 0x68
    SLIDER_INPUT = 0x69
    NUMERIC_INPUT = 0x72
    AUTO_SLEEP = 0x86
    AUTO_WAKE = 0x87
    STARTUP = 0x88
    SD_CARD_UPGRADE = 0x89
    RECONNECTED = 0x666

JUNK_DATA = b"Z\xa5\x06\x83\x10>\x01\x00"

class TJCProtocol(NextionProtocol):
    PACKET_LENGTH_MAP = {
        0x00: 6,  # Nextion Startup
        0x24: 4,  # Serial Buffer Overflow
        0x65: 6,  # Touch Event
        0x66: 5,  # Current Page Number
        0x67: 9,  # Touch Coordinate(awake)
        0x68: 9,  # Touch Coordinate(sleep)
        0x69: 8,  # Slider Value
        0x71: 8,  # Numeric Data Enclosed
        0x72: 8,  # Numneric Input
        0x86: 4,  # Auto Entered Sleep Mode
        0x87: 4,  # Auto Wake from Sleep
        0x88: 4,  # Nextion Ready
        0x89: 4,  # Start microSD Upgrade
        0xFD: 4,  # Transparent Data Finished
        0xFE: 4,  # Transparent Data Ready
    }

    def is_event(self, message):
        """Check if the message is a recognized event."""
        return len(message) > 0 and message[0] in EventType.__members__.values()

    def data_received(self, data):
        """Process received data and handle messages."""
        self.buffer += data
        while True:
            message, was_keyboard_input = self._extract_packet()
            if message is None:
                break
            self._reset_dropped_buffer()
            if self.is_event(message) or was_keyboard_input:
                self.event_message_handler(message)
            else:
                self.queue.put_nowait(message)

    def _extract_packet(self):
        """Extract a packet from the buffer based on the expected length."""
        if len(self.buffer) < 3:
            return None, False

        packet_type = self.buffer[0]
        expected_length = self.PACKET_LENGTH_MAP.get(packet_type)

        if expected_length:
            return self._extract_fixed_length_packet(expected_length)
        return self._extract_varied_length_packet()

    def _extract_fixed_length_packet(self, expected_length):
        """Extract a fixed-length packet from the buffer."""
        if len(self.buffer) < expected_length:
            if len(self.buffer) == 5 and self.buffer[0] in {0x71, 0x72}:
                expected_length = 5
            else:
                return None, False

        full_message = self.buffer[:expected_length]

        if full_message[0] == 0x71 and not full_message.endswith(self.EOL):
            full_message += self.EOL
            full_message = b"\x72" + full_message[1:]
            was_keyboard_input = True
        else:
            was_keyboard_input = False

        if not full_message.endswith(self.EOL):
            if full_message[0] == 0x65:
                full_message = self.buffer[:expected_length + 1]
                if full_message.endswith(self.EOL):
                    self.buffer = self.buffer[expected_length + 1:]
                    return full_message[:-3], was_keyboard_input

            message = self._extract_varied_length_packet()
            if message is None:
                return None, was_keyboard_input

            self.dropped_buffer += message + self.EOL
            return self._extract_packet()

        self.buffer = self.buffer[expected_length:]
        if self.buffer.startswith(self.EOL):
            self.buffer = self.buffer[3:]
            was_keyboard_input = False

        return full_message[:-3], was_keyboard_input

    def _extract_varied_length_packet(self):
        """Extract a varied-length packet from the buffer."""
        message, eol, leftover = self.buffer.partition(self.EOL)
        if not eol:
            if message.startswith(JUNK_DATA):
                self.buffer = leftover
                return None, False
            return None, False

        self.buffer = leftover
        return message, False

class TJCClient(Nextion):
    is_reconnecting = False

    def _make_protocol(self):
        """Create a TJCProtocol instance."""
        return TJCProtocol(event_message_handler=self.event_message_handler)

    def event_message_handler(self, message):
        """Handle incoming event messages with error checking."""
        try:
            event_type = EventType(message[0])
            payload_map = {
                EventType.TOUCH_COORDINATE: (">HHB", TJCTouchCoordinatePayload),
                EventType.TOUCH: ("BB", TJCTouchDataPayload),
                EventType.NUMERIC_INPUT: ("BBH", TJCNumericInputPayload),
                EventType.SLIDER_INPUT: ("BBH", TJCNumericInputPayload),
            }

            if event_type in payload_map:
                format_str, payload_type = payload_map[event_type]
                payload_length = struct.calcsize(format_str)

                if len(message[1:]) >= payload_length:
                    payload = struct.unpack(format_str, message[1:])
                    self._schedule_event_message_handler(event_type, payload_type._make(payload))
                else:
                    self.logger.error(f"Received message with insufficient data for {event_type.name}: {message[1:]}")
            else:
                self.logger.warning(f"Unhandled message type: {event_type.name} with data: {message}")

        except struct.error as e:
            self.logger.error(f"Struct error while unpacking message: {message}, error: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error while handling message: {message}, error: {e}")

    async def reconnect(self):
        """Reconnect to the device."""
        await self._connection.close()
        self.is_reconnecting = True
        await self.connect()

    async def connect(self) -> None:
        """Connect to the device with error handling."""
        try:
            await self._try_connect_on_different_baudrates()
            try:
                await self._command("bkcmd=3", attempts=1)
            except CommandTimeout:
                pass

            await self._update_sleep_status()
            if self.is_reconnecting:
                self.is_reconnecting = False
                self._schedule_event_message_handler(EventType.RECONNECTED, None)
        except ConnectionFailed:
            raise
        except Exception as e:
            # Log the exception or handle it appropriately
            raise e
