import asyncio
from logging import Logger
from src.tjc import TJCClient
from nextion.exceptions import CommandFailed

class DisplayCommunicator:
    def __init__(
        self,
        logger: Logger,
        model: str,
        port: str,
        event_handler,
        baudrate: int = 115200,
        timeout: int = 5,
    ) -> None:
        self.logger = logger
        self.model = model
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

        self.display_name_override = None
        self.display_name_line_color = None
        self.z_display = "mm"

        self.current_data = {}
        self.blocked_by = None
        self.blocked_buffer = []
        self.ips = "--"
        
        # ADD: Lock for write operations
        self._write_lock = asyncio.Lock()

        # Ensure TJCClient is properly instantiated
        self.display = TJCClient(port, baudrate, event_handler)
        self.display.encoding = "utf-8"

    async def connect(self):
        try:
            await self.display.connect()
        except Exception as e:
            self.logger.error(f"Failed to connect to display: {str(e)}")
            raise

    async def write(self, data, timeout=None, blocked_key=None):
        # Fast path: decide blocking under lock
        async with self._write_lock:
            # If someone else is blocking, queue this command
            if self.blocked_by and self.blocked_by != blocked_key:
                self.blocked_buffer.append((data, timeout))
                return

            # Claim the block if caller provided a key and none is set
            if blocked_key and not self.blocked_by:
                self.blocked_by = blocked_key

        # Execute the command outside the lock
        try:
            effective_timeout = self.timeout if timeout is None else timeout
            await asyncio.wait_for(
                self.display.command(data, effective_timeout),
                timeout=effective_timeout + 1  # slight cushion over device timeout
            )
        except asyncio.TimeoutError:
            self.logger.warning(f"Display write timed out for command: {data}")
            # Quick, robust recovery: re-sync the panel and bail out of this burst
            try:
                # If your client exposes .reconnect(), use it; otherwise call whatever
                # you use on initial connect/init (bkcmd, sleep=0, sendme, etc.).
                await self.display.reconnect()
            except Exception as e:
                self.logger.warning(f"Display reconnect failed after timeout: {e}")
            return
        except CommandFailed as e:
            # Expected if we target a control not present on the current page
            self.logger.debug(
                f"Display command failed (component may not exist on current page): {e}"
            )
        except Exception as e:
            # Any other error: log and continue
            self.logger.warning(f"Unexpected error writing to display: {e}")
        finally:
            # If this was a blocking op, release block and send the next queued command (if any)
            if blocked_key:
                await self.unblock(blocked_key)

    async def unblock(self, blocked_key):
        next_item = None
        async with self._write_lock:
            if self.blocked_by == blocked_key:
                self.blocked_by = None
                if self.blocked_buffer:
                    # pop the next queued command (FIFO)
                    next_item = self.blocked_buffer.pop(0)

        # Send the next queued command outside the lock to avoid deadlocks
        if next_item is not None and self.blocked_by is None:
            data, timeout = next_item
            await self.write(data, timeout=timeout)
        
    def get_device_name(self):
        return self.model
    
    def get_display_type_name(self):
        return self.__class__.__name__

    async def retrieve_nested_data(self, path):
        current = self.current_data
        for key in path:
            current = current.get(key)
            if current is None:
                return None
        return current

    async def navigate_to(self, page_id):
        # Block other writes while we switch pages
        await self.write(f"page {page_id}", blocked_key="__nav__")
        await asyncio.sleep(0.25)  # give the HMI time to swap pages
        await self.unblock("__nav__")

    async def update_data(self, new_data, data_mapping=None, current_data=None):
        if data_mapping is None:
            data_mapping = self.data_mapping  # Ensure `self.data_mapping` is set elsewhere
        if current_data is None:
            current_data = self.current_data
            if not current_data:
                self.current_data = new_data
        
        try:
            await self._update_data_recursive(new_data, data_mapping, current_data)
        except Exception as e:
            # Don't let display update failures crash the entire update loop
            self.logger.debug(f"Error updating display data: {e}")

    async def _update_data_recursive(self, new_data, data_mapping, current_data):
        is_dict = isinstance(new_data, dict)
        keys_to_iterate = list(new_data.keys()) if is_dict else range(len(new_data))
        
        for key in keys_to_iterate:
            if key in data_mapping:
                value = new_data[key]
                mapping_value = data_mapping[key]
                if isinstance(mapping_value, dict):
                    mapping_current = current_data.setdefault(key, {})
                    await self._update_data_recursive(value, mapping_value, mapping_current)
                elif isinstance(mapping_value, list):
                    await self._update_data_leaf(value, mapping_value)

    async def _update_data_leaf(self, value, mapping_value):
        for mapping_leaf in mapping_value:
            try:
                formatted = await self._format_value(mapping_leaf, value)
                for mapped_key in mapping_leaf.fields:
                    command = (
                        f'{mapped_key}.{mapping_leaf.field_type}="{formatted}"'
                        if mapping_leaf.field_type == "txt"
                        else f"{mapped_key}.{mapping_leaf.field_type}={formatted}"
                    )
                    await self.write(command)
                    await asyncio.sleep(0.05)  # Small delay to ensure each command is processed
            except Exception as e:
                # Log but continue processing other mappings
                self.logger.debug(f"Failed to update display leaf: {e}")

    async def _format_value(self, mapping_leaf, value):
        if not mapping_leaf.required_fields:
            return mapping_leaf.format(value)
        else:
            required_values = [
                await self.retrieve_nested_data(required_field)
                for required_field in mapping_leaf.required_fields
            ]
            return mapping_leaf.format_with_required(value, *required_values)
