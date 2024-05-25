from logging import Logger
from src.tjc import TJCClient


class DisplayCommunicator:
    supported_firmware_versions = []
    current_data = {}

    ips = "--"

    def __init__(
        self,
        logger: Logger,
        model: str,
        port: str,
        event_handler,
        baudrate: int = 115200,
        timeout: int = 5,
    ) -> None:
        self.display_name_override = None
        self.display_name_line_color = None
        self.z_display = "mm"

        self.logger = logger
        self.model = model
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

        self.display = TJCClient(port, baudrate, event_handler)
        self.display.encoding = "utf-8"

    async def connect(self):
        await self.display.connect()

    async def write(self, data, timeout=None):
        await self.display.command(data, timeout if timeout is not None else self.timeout)

    async def get_firmware_version(self) -> str:
        pass

    async def check_valid_version(self):
        version = await self.get_firmware_version()
        if version not in self.supported_firmware_versions:
            self.logger.error(
                "Unsupported firmware version. Things may not work as expected. Consider updating to a supported version: "
                + ", ".join(self.supported_firmware_versions)
            )
            return False
        return True

    def get_device_name(self):
        return self.model
    
    def get_display_type_name(self):
        return self.__class__.__name__

    def get_current_data(self, path):
        index = 0
        current = self.current_data
        while index < len(path) and path[index] in current:
            current = current[path[index]]
            index += 1
        if index < len(path):
            return None
        return current

    async def navigate_to(self, page_id):
        await self.write(f"page {page_id}")

    async def update_data(self, new_data, data_mapping=None, current_data=None):
        if data_mapping is None:
            data_mapping = self.data_mapping
        if current_data is None:
            if len(self.current_data) == 0:
                self.current_data = new_data
            current_data = self.current_data
        is_dict = isinstance(new_data, dict)
        for key in new_data if is_dict else range(len(new_data)):
            if key in data_mapping:
                value = new_data[key]
                mapping_value = data_mapping[key]
                if isinstance(mapping_value, dict):
                    mapping_current = current_data[key] if key in current_data else {}
                    await self.update_data(value, mapping_value, mapping_current)
                elif isinstance(mapping_value, list):
                    for mapping_leaf in mapping_value:
                        if mapping_leaf.required_fields is None:
                            formatted = mapping_leaf.format(value)
                        else:
                            required_values = [
                                self.get_current_data(required_field)
                                for required_field in mapping_leaf.required_fields
                            ]
                            formatted = mapping_leaf.format_with_required(
                                value, *required_values
                            )
                        for mapped_key in mapping_leaf.fields:
                            if mapping_leaf.field_type == "txt":
                                await self.write(
                                    f'{mapped_key}.{mapping_leaf.field_type}="{formatted}"'
                                )
                            else:
                                await self.write(
                                    f"{mapped_key}.{mapping_leaf.field_type}={formatted}"
                                )
