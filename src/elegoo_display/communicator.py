"""Communicator for the Elegoo touch-screen firmware."""

import asyncio
import time
from logging import Logger
from src.communicator import DisplayCommunicator
from src.mapping import (
    build_format_filename,
    PAGE_MAIN,
    PAGE_FILES,
    PAGE_PREPARE_MOVE,
    PAGE_PREPARE_EXTRUDER,
    PAGE_SETTINGS_TEMPERATURE_SET,
    PAGE_SETTINGS_ABOUT,
    PAGE_LEVELING,
    PAGE_CONFIRM_PRINT,
    PAGE_PRINTING,
    PAGE_PRINTING_COMPLETE,
    PAGE_PRINTING_FILAMENT,
    PAGE_PRINTING_SPEED,
    PAGE_PRINTING_ADJUST,
    PAGE_PRINTING_DIALOG_SPEED,
    PAGE_PRINTING_DIALOG_FLOW,
    PAGE_LIGHTS,
    PAGE_SHUTDOWN_DIALOG,
    format_time,
)
from src.colors import (
    BACKGROUND_DIALOG,
    BACKGROUND_GRAY,
    TEXT_WARNING,
)
from src.wifi import get_wlan0_status
from src.elegoo_display.screens import ElegooScreensMixin


class ElegooDisplayCommunicator(ElegooScreensMixin, DisplayCommunicator):
    supported_firmware_versions = ["1.2.11", "1.2.12", "1.2.13", "1.2.14", "1.2.14.1", "1.2.16", "1.2.17", "1.2.18", "1.2.22"]

    def __init__(self, logger: Logger, model: str, port: str, event_handler, baudrate: int = 115200, timeout: int = 5):
        # Call the base class constructor
        super().__init__(logger, model, port, event_handler, baudrate, timeout)

        # Firmware version attribute initialized
        self._firmware_version = None

    # Cache WiFi status to avoid delays
        self._cached_wifi_status = None
        self._last_wifi_check = 0
        self._wifi_check_interval = 30  # Only check WiFi every 30 seconds
        self._warning_task = None

    async def get_firmware_version(self) -> str:
        if self._firmware_version is None:  # Check if the firmware version is cached
            self._firmware_version = await self.display.get("information.lversion.txt", self.timeout)
        return self._firmware_version

    async def send_warning_message(self):
        try:
            await asyncio.sleep(0.6)  # Add delay if needed
            await self.write(
                f'xstr 0,464,320,16,2,{TEXT_WARNING},{BACKGROUND_GRAY},1,1,1,"WARNING: Unsupported Display Firmware Version"'
            )
        finally:
            self._warning_task = None

    async def check_valid_version(self):
        version = await self.get_firmware_version()
        version = version.strip()  # Ensure no extra spaces or characters
        self.logger.debug(f"Comparing '{version}' against supported versions: {self.supported_firmware_versions}")
        self.logger.info(f"Retrieved firmware version: {version}")

        if version not in self.supported_firmware_versions:
            self.logger.error(
                "Unsupported firmware version. Consider updating to a supported version: "
                + ", ".join(self.supported_firmware_versions)
            )
            if self._warning_task is None or self._warning_task.done():
                self._warning_task = asyncio.create_task(self.send_warning_message())
            return False
        return True

    async def special_page_handling(self, current_page):
        if current_page == PAGE_MAIN:
            has_wifi = await self.update_wifi_ui()
            if self.has_two_beds:
                await self.write("vis out_bedtemp,1")
            if self.display_name_override:
                display_name = self.display_name_override
                if display_name == "MODEL_NAME":
                    display_name = self.get_device_name()
                await self.write(
                    "xstr 12,20,180,20,1,65535,"
                    + str(BACKGROUND_GRAY)
                    + ',0,1,1,"'
                    + display_name
                    + '"'
                )
            if self.display_name_line_color:
                await self.write("fill 13,47,24,4," + str(self.display_name_line_color))

            await self.write(f"xpic {200 if has_wifi else 230},16,30,30,220,200,51")
        elif current_page == PAGE_SETTINGS_ABOUT:
            await self.write(
                self.mapper.map_page(PAGE_SETTINGS_ABOUT)
                + '.b[16].txt="'
                + self.ips
                + '"'
            )
            await self.write("fill 0,400,320,60," + str(BACKGROUND_GRAY))
            await self.write(
                "xstr 0,400,320,30,1,65535,"
                + str(BACKGROUND_GRAY)
                + ',1,1,1,"OpenNept4une"'
            )
            await self.write(
                "xstr 0,430,320,30,2,GRAY,"
                + str(BACKGROUND_GRAY)
                + ',1,1,1,"github.com/OpenNeptune3D"'
            )
        elif current_page == PAGE_LIGHTS:
            # Label writes intentionally disabled: writing English literals to t0/t1
            # breaks non-English TFT locales. Re-enable only with locale-aware labels
            # or after moving labels fully into the TFT assets.
            pass
        elif current_page == PAGE_PRINTING:
            await self.write("printvalue.xcen=0")
            await self.write("move printvalue,13,267,13,267,0,10")
            await self.write("vis b[16],0")
        elif current_page == PAGE_PRINTING_COMPLETE:
            await self.write('b[4].txt="Print Completed!"')
        elif current_page == PAGE_PRINTING_ADJUST:
            await self.write('t9.txt="' + self.ips + '"')
        elif current_page == PAGE_LEVELING:
            await self.write('b[12].txt="Leveling"')
            await self.write('b[18].txt="Screws Tilt Adjust"')
            await self.write('b[19].txt="Z-Probe Offset"')
            await self.write('b[20].txt="Full Bed Level"')
            self.leveling_mode = None
        elif current_page == PAGE_PRINTING_DIALOG_SPEED:
            await self.write("b[3].maxval=200")
        elif current_page == PAGE_PRINTING_DIALOG_FLOW:
            await self.write("b[3].maxval=200")
        elif current_page == PAGE_SHUTDOWN_DIALOG:
            await self.write("fill 20,100,232,290," + str(BACKGROUND_DIALOG))  # Increased height to 290
            await self.write('xstr 24,104,224,50,1,65535,10665,1,1,1,"Shut Down Host"')
            await self.write('xstr 24,158,224,50,1,65535,10665,1,1,1,"Reboot Host"')
            await self.write('xstr 24,212,224,50,1,65535,10665,1,1,1,"Reboot Klipper"')
            await self.write('xstr 24,266,224,50,1,65535,10665,1,1,1,"Firmware Restart"')  # New option added
            await self.write('xstr 24,320,224,50,1,65535,10665,1,1,1,"Back"')  # Position remains at 320

    async def update_printing_heater_settings_ui(
        self, printing_selected_heater, printing_target_temp
    ):
        if self.has_two_beds:
            await self.write(
                f"{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}.b0.picc="
                + str(90 if printing_selected_heater == "extruder" else 89)
            )
            await self.write(
                f"{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}.b1.picc="
                + str(90 if printing_selected_heater == "heater_bed" else 89)
            )
            await self.write(
                f"{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}.b2.picc="
                + str(90 if printing_selected_heater == "heater_bed_outer" else 89)
            )
            await self.write(
                f"{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}.targettemp.txt=\""
                + f"{printing_target_temp:.0f}\""
            )

        else:
            await self.write(
                f'{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}.b[13].pic={54 + ["extruder", "heater_bed"].index(printing_selected_heater)}'
            )
            await self.write(
                f'{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}.b[35].txt="'
                + f"{printing_target_temp:.0f}"
                + '"'
            )

    async def update_printing_temperature_increment_ui(
        self, printing_selected_temp_increment
    ):
        await self.write(
            f'{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}.p1.pic={56 + ["1", "5", "10"].index(printing_selected_temp_increment)}'
        )

    async def update_printing_speed_settings_ui(
        self, printing_selected_speed_type, printing_target_speed
    ):
        await self.write(
            f"{self.mapper.map_page(PAGE_PRINTING_SPEED)}.b0.picc="
            + str(59 if printing_selected_speed_type == "print" else 58)
        )
        await self.write(
            f"{self.mapper.map_page(PAGE_PRINTING_SPEED)}.b1.picc="
            + str(59 if printing_selected_speed_type == "flow" else 58)
        )
        await self.write(
            f"{self.mapper.map_page(PAGE_PRINTING_SPEED)}.b2.picc="
            + str(59 if printing_selected_speed_type == "fan" else 58)
        )
        await self.write(
            f"{self.mapper.map_page(PAGE_PRINTING_SPEED)}.targetspeed.val={printing_target_speed*100:.0f}"
        )

    async def update_printing_speed_increment_ui(
        self, printing_selected_speed_increment
    ):
        await self.write(
            f"{self.mapper.map_page(PAGE_PRINTING_SPEED)}.b[14].picc="
            + str(59 if printing_selected_speed_increment == "1" else 58)
        )
        await self.write(
            f"{self.mapper.map_page(PAGE_PRINTING_SPEED)}.b[15].picc="
            + str(59 if printing_selected_speed_increment == "5" else 58)
        )
        await self.write(
            f"{self.mapper.map_page(PAGE_PRINTING_SPEED)}.b[16].picc="
            + str(59 if printing_selected_speed_increment == "10" else 58)
        )

    async def update_printing_zoffset_increment_ui(self, z_offset_distance):
        await self.write(
            f"{self.mapper.map_page(PAGE_PRINTING_ADJUST)}.b[23].picc="
            + str(36 if z_offset_distance == "0.01" else 65)
        )
        await self.write(
            f"{self.mapper.map_page(PAGE_PRINTING_ADJUST)}.b[24].picc="
            + str(36 if z_offset_distance == "0.1" else 65)
        )
        await self.write(
            f"{self.mapper.map_page(PAGE_PRINTING_ADJUST)}.b[25].picc="
            + str(36 if z_offset_distance == "1" else 65)
        )

    async def update_preset_temp_ui(
        self,
        temperature_preset_step,
        temperature_preset_extruder,
        temperature_preset_bed,
    ):
        await self.write(
            f"{self.mapper.map_page(PAGE_SETTINGS_TEMPERATURE_SET)}.b[7].pic={56 + [1, 5, 10].index(temperature_preset_step)}"
        )
        await self.write(
            f'{self.mapper.map_page(PAGE_SETTINGS_TEMPERATURE_SET)}.b[18].txt="{temperature_preset_extruder}"'
        )
        await self.write(
            f'{self.mapper.map_page(PAGE_SETTINGS_TEMPERATURE_SET)}.b[19].txt="{temperature_preset_bed}"'
        )

    async def update_prepare_move_ui(self, move_distance):
        await self.write(
            f'{self.mapper.map_page(PAGE_PREPARE_MOVE)}.p0.pic={10 + ["0.1", "1", "10"].index(move_distance)}'
        )

    async def update_prepare_extrude_ui(self, extrude_amount, extrude_speed):
        await self.write(
            f'{self.mapper.map_page(PAGE_PREPARE_EXTRUDER)}.b[8].txt="{extrude_amount}"'
        )
        await self.write(
            f'{self.mapper.map_page(PAGE_PREPARE_EXTRUDER)}.b[9].txt="{extrude_speed}"'
        )

    async def update_wifi_ui(self):
        try:
            current_time = time.time()
            if self._cached_wifi_status is not None and (current_time - self._last_wifi_check) < self._wifi_check_interval:
                has_wifi, ssid, rssi_category = self._cached_wifi_status
            else:
                has_wifi, ssid, rssi_category = await asyncio.to_thread(get_wlan0_status)
                self._cached_wifi_status = (has_wifi, ssid, rssi_category)
                self._last_wifi_check = current_time
        except Exception:
            self.logger.debug("Failed to update WiFi UI", exc_info=True)
            return False

        if not has_wifi:
            await self.write("picq 230,0,42,42,214")
            return False
        if ssid is None:
            await self.write("picq 230,0,42,42,313")
        else:
            await self.write(f"picq 230,0,42,42,{313 + rssi_category}")
        return True

    async def show_files_page(self, current_dir, dir_contents, files_page):
        page_size = 5
        title = current_dir.split("/")[-1]
        if title == "":
            title = "Files"
        file_count = len(dir_contents)
        if file_count == 0:
            await self.write(
                f'{self.mapper.map_page(PAGE_FILES)}.b[11].txt="{title} (Empty)"'
            )
        else:
            await self.write(
                f'{self.mapper.map_page(PAGE_FILES)}.b[11].txt="{title} ({(files_page * page_size) + 1}-{min((files_page * page_size) + page_size, file_count)}/{file_count})"'
            )
        component_index = 0
        for index in range(
            files_page * page_size, min(len(dir_contents), (files_page + 1) * page_size)
        ):
            file = dir_contents[index]
            await self.write(
                f'{self.mapper.map_page(PAGE_FILES)}.b[{component_index + 18}].txt="{file["name"]}"'
            )
            if file["type"] == "dir":
                await self.write(
                    f"{self.mapper.map_page(PAGE_FILES)}.b[{component_index + 13}].pic=194"
                )
            else:
                await self.write(
                    f"{self.mapper.map_page(PAGE_FILES)}.b[{component_index + 13}].pic=193"
                )
            component_index += 1
        for index in range(component_index, page_size):
            await self.write(
                f"{self.mapper.map_page(PAGE_FILES)}.b[{index + 13}].pic=195"
            )
            await self.write(
                f'{self.mapper.map_page(PAGE_FILES)}.b[{index + 18}].txt=""'
            )

    async def update_printing_state_ui(self, state):
        if state == "printing":
            await self.write(f"{self.mapper.map_page(PAGE_PRINTING)}.b[44].pic=68")
        elif state == "paused":
            await self.write(f"{self.mapper.map_page(PAGE_PRINTING)}.b[44].pic=69")

    async def set_data_prepare_screen(self, filename, metadata):
        await self.write(f"{self.mapper.map_page(PAGE_CONFIRM_PRINT)}.b[3].font=2")
        await self.write(
            f'{self.mapper.map_page(PAGE_CONFIRM_PRINT)}.b[2].txt="{build_format_filename()(filename)}"'
        )
        info = []
        if "layer_height" in metadata:
            info.append(f"Layer: {metadata['layer_height']}mm")
        if "estimated_time" in metadata:
            info.append(f"Time: {format_time(metadata['estimated_time'])}")
        await self.write(
            f'{self.mapper.map_page(PAGE_CONFIRM_PRINT)}.b[3].txt="{" ".join(info)}"'
        )
