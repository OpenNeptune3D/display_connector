import asyncio
import logging
import struct
from collections import namedtuple
from enum import IntEnum
from nextion import Nextion
from nextion.protocol.nextion import NextionProtocol
from nextion.exceptions import CommandTimeout, ConnectionFailed

# Define the payloads
TJCTouchDataPayload = namedtuple("Touch", "page_id component_id")
TJCStringInputPayload = namedtuple("String", "page_id component_id string")
TJCNumericInputPayload = namedtuple("Numeric", "page_id component_id value")
TJCTouchCoordinatePayload = namedtuple("TouchCoordinate", "x y touch_event")

# Define event types
class EventType(IntEnum):
    TOUCH = 0x65  # Touch event
    TOUCH_COORDINATE = 0x67  # Touch coordinate
    TOUCH_IN_SLEEP = 0x68  # Touch event in sleep mode
    SLIDER_INPUT = 0x69
    NUMERIC_INPUT = 0x72  # Numeric input
    AUTO_SLEEP = 0x86  # Device automatically enters into sleep mode
    AUTO_WAKE = 0x87  # Device automatically wake up
    STARTUP = 0x88  # System successful start up
    SD_CARD_UPGRADE = 0x89  # Start SD card upgrade
    RECONNECTED = 0x666  # Device reconnected

# Define constant values
JUNK_DATA = b"Z\xa5\x06\x83\x10>\x01\x00"
EOL = b'\xFF\xFF\xFF'

# Custom protocol implementation
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
        0x86: 4,  # Auto Entered Sleep Mode
        0x87: 4,  # Auto Wake from Sleep
        0x88: 4,  # Nextion Ready
        0x89: 4,  # Start microSD Upgrade
        0xFD: 4,  # Transparent Data Finished
        0xFE: 4,  # Transparent Data Ready
    }

    def is_event(self, message):
        return len(message) > 0 and message[0] in EventType.__members__.values()

    def data_received(self, data):
        self.buffer += data

        while True:
            message, was_keyboard_input = self._extract_packet()

            if message is None:  # EOL not found or incomplete packet
                break

            self._reset_dropped_buffer()

            if self.is_event(message) or was_keyboard_input:
                self.event_message_handler(message)
            else:
                self.queue.put_nowait(message)

    def _extract_packet(self):
        if len(self.buffer) < 3:
            return None, False

        packet_type = self.buffer[0]
        expected_length = self.PACKET_LENGTH_MAP.get(packet_type)

        if expected_length:
            return self._extract_fixed_length_packet(expected_length)
        else:
            return self._extract_varied_length_packet()

    def _extract_fixed_length_packet(self, expected_length):
        buffer_len = len(self.buffer)
        was_keyboard_input = False

        # Ensure the buffer is long enough for the expected packet length
        if buffer_len < expected_length:
            if buffer_len == 5 and (self.buffer[0] == 0x72 or self.buffer[0] == 0x71):
                expected_length = 5
            else:
                return None, False

        full_message = self.buffer[:expected_length]

        # Handle special cases for keyboard input (e.g., 0x71) and ensure it ends with EOL
        if full_message[0] == 0x71 and not full_message.endswith(EOL):
            full_message += EOL
            full_message = b"\x72" + full_message[1:]
            was_keyboard_input = True

        # If still no EOL, it's likely a varied-length packet or corrupted data
        if not full_message.endswith(EOL):
            message = self._handle_incomplete_fixed_packet(expected_length)
            if message is None:
                return None, False
            self.dropped_buffer += message + EOL
            return self._extract_packet()

        # Clean up the buffer
        self.buffer = self.buffer[expected_length:]

        # Handle case where the buffer starts with EOL, likely due to keyboard input
        if self.buffer.startswith(EOL):
            self.buffer = self.buffer[3:]
            was_keyboard_input = False

        return full_message[:-3], was_keyboard_input

    def _handle_incomplete_fixed_packet(self, expected_length):
        if self.buffer[0] == 0x65:  # Touch event that might have the press/release byte
            extended_message = self.buffer[: expected_length + 1]
            if extended_message.endswith(EOL):
                self.buffer = self.buffer[expected_length + 1 :]
                return extended_message[:-3]
        return None

    def _extract_varied_length_packet(self):
        message, eol, leftover = self.buffer.partition(EOL)
        if not eol:
            if message.startswith(JUNK_DATA):
                self.buffer = leftover
                return None, False
            return None, False

        self.buffer = leftover
        return message, False

# Client implementation
class TJCClient(Nextion):
    is_reconnecting = False
    _lock = asyncio.Lock()

    def _make_protocol(self):
        return TJCProtocol(event_message_handler=self.event_message_handler)

    def event_message_handler(self, message):
        typ = message[0]
        try:
            if typ == EventType.TOUCH_COORDINATE:
                # Ensure the message length is correct before unpacking
                if len(message) >= 6:  # 1 byte for type + 5 bytes for payload
                    payload = TJCTouchCoordinatePayload._make(struct.unpack(">HHB", message[1:]))
                    self._schedule_event_message_handler(EventType(typ), payload)
                else:
                    raise ValueError(f"Invalid message length for TOUCH_COORDINATE: {len(message)}")
            elif typ == EventType.TOUCH:  # Touch event
                if len(message) >= 3:  # 1 byte for type + 2 bytes for payload
                    payload = TJCTouchDataPayload._make(struct.unpack("BB", message[1:]))
                    self._schedule_event_message_handler(EventType(typ), payload)
                else:
                    raise ValueError(f"Invalid message length for TOUCH: {len(message)}")
            elif typ == EventType.NUMERIC_INPUT:
                if len(message) >= 4:  # 1 byte for type + 3 bytes for payload
                    payload = TJCNumericInputPayload._make(struct.unpack("BBH", message[1:]))
                    self._schedule_event_message_handler(EventType(typ), payload)
                else:
                    raise ValueError(f"Invalid message length for NUMERIC_INPUT: {len(message)}")
            elif typ == EventType.SLIDER_INPUT:
                if len(message) >= 4:  # 1 byte for type + 3 bytes for payload
                    payload = TJCNumericInputPayload._make(struct.unpack("BBH", message[1:]))
                    self._schedule_event_message_handler(EventType(typ), payload)
                else:
                    raise ValueError(f"Invalid message length for SLIDER_INPUT: {len(message)}")
            else:
                super().event_message_handler(message)
        except struct.error as e:
            logging.error(f"Error unpacking message {message}: {e}")
        except ValueError as e:
            logging.error(f"Invalid message: {message} - {e}")

    async def reconnect(self):
        async with self._lock:
            if not self._connection.is_closing():
                await self._connection.close()
            self.is_reconnecting = True
            await self.connect()

    async def connect(self) -> None:
        async with self._lock:
            try:
                # Attempt connection with a timeout to prevent hanging indefinitely
                await asyncio.wait_for(self._try_connect_on_different_baudrates(), timeout=10.0)

                try:
                    await self._command("bkcmd=3", attempts=1)
                except CommandTimeout:
                    logging.warning("CommandTimeout during initial connect, proceeding anyway.")
                    pass  # it is fine

                await self._update_sleep_status()
                if self.is_reconnecting:
                    self.is_reconnecting = False
                    self._schedule_event_message_handler(EventType.RECONNECTED, None)
            except asyncio.TimeoutError:
                logging.error("Connection attempt timed out.")
                raise ConnectionFailed("Connection attempt timed out.")
            except ConnectionFailed:
                logging.error("ConnectionFailed: Unable to connect to the device.")
                raise
            except asyncio.CancelledError:
                logging.warning("Connection task was cancelled.")
                raise
            except Exception as e:
                logging.exception(f"Unexpected error during connection: {e}")
                raise
