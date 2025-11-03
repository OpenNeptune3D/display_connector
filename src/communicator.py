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
        # Check if currently blocked by another operation
        if self.blocked_by and self.blocked_by != blocked_key:
            self.blocked_buffer.append(data)
            return
        
        # Set blocked state if a blocking key is provided
        if blocked_key and not self.blocked_by:
            self.blocked_by = blocked_key

        try:
            await self.display.command(data, timeout if timeout is not None else self.timeout)
        except CommandFailed as e:
            # This is expected when components don't exist on the current page
            # For example, trying to update printing page components while on KAMP page
            self.logger.debug(f"Display command failed (component may not exist on current page): {e}")
        except Exception as e:
            # Other errors should still be logged but not crash
            self.logger.warning(f"Unexpected error writing to display: {e}")
        finally:
            # If this was a blocking operation, unblock afterwards
            if blocked_key:
                await self.unblock(blocked_key)

    async def unblock(self, blocked_key):
        if self.blocked_by == blocked_key:
            self.blocked_by = None
            if self.blocked_buffer:
                next_command = self.blocked_buffer.pop(0)
                await self.write(next_command)

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
        await self.write(f"page {page_id}")
        await asyncio.sleep(0.5)  # Small delay to ensure the page change is processed

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
