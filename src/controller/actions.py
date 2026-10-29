"""Dispatch of touch-screen actions to printer and display operations for DisplayController."""

from src.config import TEMP_DEFAULTS

from src.neptune4 import (
    MODEL_N4_PRO
)
from src.mapping import (
    PAGE_FILES,
    PAGE_SETTINGS_TEMPERATURE_SET,
    PAGE_CONFIRM_PRINT,
    PAGE_PRINTING_KAMP,
    PAGE_OVERLAY_LOADING,
)
from src.controller.common import (
    logger,
)


class ActionsMixin:
    """Dispatch of touch-screen actions to printer and display operations."""

    def execute_action(self, action):
        if action.startswith("move_"):
            parts = action.split("_")
            axis = parts[1].upper()
            direction = parts[2]
            self.move_axis(axis, direction + self.move_distance)
        elif action.startswith("set_distance_"):
            parts = action.split("_")
            self.move_distance = parts[2]
            self._loop.create_task(
                self.display.update_prepare_move_ui(self.move_distance)
            )
        if action.startswith("zoffset_"):
            parts = action.split("_")
            direction = parts[1]
            self.send_gcode(
                f"SET_GCODE_OFFSET Z_ADJUST={direction}{self.z_offset_distance} MOVE=1"
            )
        elif action.startswith("zoffsetchange_"):
            parts = action.split("_")
            self.z_offset_distance = parts[1]
            self._loop.create_task(
                self.display.update_printing_zoffset_increment_ui(
                    self.z_offset_distance
                )
            )
        elif action == "toggle_part_light":
            self.part_light_state = not self.part_light_state
            self._set_light("Part_Light", self.part_light_state)
        elif action == "toggle_frame_light":
            self.frame_light_state = not self.frame_light_state
            self._set_light("Frame_Light", self.frame_light_state)
        elif action == "toggle_filament_sensor":
            self.filament_sensor_state = not self.filament_sensor_state
            self._toggle_filament_sensor(self.filament_sensor_state)
        elif action == "toggle_fan":
            self.fan_state = not self.fan_state
            self._toggle_fan(self.fan_state)
        elif action.startswith("printer.send_gcode"):
            gcode = action.split("'")[1]
            self.send_gcode(gcode)
        elif action == "go_back":
            self._loop.create_task(self._go_back())
        elif action.startswith("page"):
            self._loop.create_task(self._navigate_to_page(action.split(" ")[1]))
        elif action == "emergency_stop":
            logger.info("Executing emergency stop!")
            self._loop.create_task(
                self._send_moonraker_request("printer.emergency_stop")
            )
        elif action == "pause_print_button":
            self._loop.create_task(self._handle_pause_resume())
        elif action == "pause_print_confirm":
            self._loop.create_task(self._handle_pause_confirm())
        elif action == "stop_print":
            self._loop.create_task(self._go_back())
            self._loop.create_task(self._navigate_to_page(PAGE_OVERLAY_LOADING))
            logger.info("Stopping print")
            self._loop.create_task(self._send_moonraker_request("printer.print.cancel"))
        elif action == "files_picker":
            self._loop.create_task(self._navigate_to_page(PAGE_FILES))
            self._loop.create_task(self._load_files())

        elif action.startswith("temp_heater_"):
            parts = action.split("_")
            self.printing_selected_heater = "_".join(parts[2:])
            self._loop.create_task(
                self.display.update_printing_heater_settings_ui(
                    self.printing_selected_heater,
                    self.printing_target_temps[self.printing_selected_heater],
                )
            )
        elif action.startswith("temp_increment_"):
            parts = action.split("_")
            self.printing_selected_temp_increment = parts[2]
            self._loop.create_task(
                self.display.update_printing_temperature_increment_ui(
                    self.printing_selected_temp_increment
                )
            )
        elif action.startswith("temp_adjust_"):
            parts = action.split("_")
            direction = parts[2]
            current_temp = self.printing_target_temps[self.printing_selected_heater]
            self.send_gcode(
                "SET_HEATER_TEMPERATURE HEATER="
                + self.printing_selected_heater
                + " TARGET="
                + str(
                    current_temp
                    + (
                        int(self.printing_selected_temp_increment)
                        * (1 if direction == "+" else -1)
                    )
                )
            )
        elif action == "temp_reset":
            self.send_gcode(
                "SET_HEATER_TEMPERATURE HEATER="
                + self.printing_selected_heater
                + " TARGET=0"
            )
        elif action.startswith("speed_type_"):
            parts = action.split("_")
            self.printing_selected_speed_type = parts[2]
            self._loop.create_task(
                self.display.update_printing_speed_settings_ui(
                    self.printing_selected_speed_type,
                    self.printing_target_speeds[self.printing_selected_speed_type],
                )
            )
        elif action.startswith("speed_increment_"):
            parts = action.split("_")
            self.printing_selected_speed_increment = parts[2]
            self._loop.create_task(
                self.display.update_printing_speed_increment_ui(
                    self.printing_selected_speed_increment
                )
            )
        elif action.startswith("speed_adjust_"):
            parts = action.split("_")
            direction = parts[2]
            current_speed = self.printing_target_speeds[self.printing_selected_speed_type]  # factor
            change = int(self.printing_selected_speed_increment) * (
                1 if direction == "+" else -1
            )
            new_speed = current_speed + (change / 100.0)  # factor math only
            self._loop.create_task(
                self.send_speed_update(self.printing_selected_speed_type, new_speed)
            )

        elif action == "speed_reset":
            # for fan you might prefer 0.0 instead of 1.0
            reset_value = 1.0 if self.printing_selected_speed_type != "fan" else 0.0
            self._loop.create_task(
                self.send_speed_update(self.printing_selected_speed_type, reset_value)
            )
        elif action.startswith("files_page_"):
            parts = action.split("_")
            direction = parts[2]
            async def _change_files_page():
                async with self._files_lock:
                    self.files_page = int(
                        max(
                            0,
                            min(
                                (len(self.dir_contents) / 5),
                                self.files_page + (1 if direction == "next" else -1),
                            ),
                        )
                    )
                await self.display.show_files_page(
                    self.current_dir, self.dir_contents, self.files_page
                )   
            self._loop.create_task(_change_files_page())
        elif action.startswith("open_file_"):
            parts = action.split("_")
            index = int(parts[2])
            async def _handle_file_selection():
                async with self._files_lock:
                    selected = self.dir_contents[(self.files_page * 5) + index]
                    is_dir = selected["type"] == "dir"
                    file_path = selected["path"]
                    if is_dir:
                        self.current_dir = file_path
                        self.files_page = 0
                if is_dir:
                    await self._load_files()
                else:
                    async with self._filename_lock:
                        self.current_filename = file_path
                    await self._navigate_to_page(PAGE_CONFIRM_PRINT)
            self._loop.create_task(_handle_file_selection())
        elif action == "print_opened_file":
            # Create async task that safely reads filename under lock
            async def _navigate_and_print():
                await self._navigate_to_page(PAGE_OVERLAY_LOADING, clear_history=True)
                async with self._filename_lock:
                    filename_to_print = self.current_filename
                await self._send_moonraker_request(
                    "printer.print.start", {"filename": filename_to_print}
                )
            
            self._loop.create_task(_navigate_and_print())
        elif action == "confirm_complete":
            logger.info("Clearing SD Card")
            self.send_gcode("SDCARD_RESET_FILE")
        elif action.startswith("set_temp"):
            parts = action.split("_")
            target = parts[-1]
            heater = "_".join(parts[2:-1])
            self.send_gcode(
                "SET_HEATER_TEMPERATURE HEATER=" + heater + " TARGET=" + target
            )
        elif action.startswith("set_preset_temp"):
            parts = action.split("_")
            material = parts[3].lower()

            if "temperatures." + material in self.config:
                extruder = self.config["temperatures." + material]["extruder"]
                heater_bed = self.config["temperatures." + material]["heater_bed"]
            else:
                extruder = TEMP_DEFAULTS[material][0]
                heater_bed = TEMP_DEFAULTS[material][1]
            gcodes = [
                f"SET_HEATER_TEMPERATURE HEATER=extruder TARGET={extruder}",
                f"SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET={heater_bed}",
            ]
            if self.display.model == MODEL_N4_PRO:
                gcodes.append(
                    f"SET_HEATER_TEMPERATURE HEATER=heater_bed_outer TARGET={heater_bed}"
                )
            self._loop.create_task(self.send_gcodes_async(gcodes))
        elif action.startswith("set_extrude_amount"):
            self.extrude_amount = int(action.split("_")[3])
            self._loop.create_task(
                self.display.update_prepare_extrude_ui(self.extrude_amount, self.extrude_speed)
            )
        elif action.startswith("set_extrude_speed"):
            self.extrude_speed = int(action.split("_")[3])
            self._loop.create_task(
                self.display.update_prepare_extrude_ui(self.extrude_amount, self.extrude_speed)
            )
        elif action.startswith("extrude_"):
            async def _handle_extrude():
                async with self._filename_lock:  # Reuse existing lock or create _state_lock
                    is_not_printing = (self.current_state != "printing")
                
                if is_not_printing:
                    parts = action.split("_")
                    direction = parts[1]
                    loadtype = "LOAD" if direction == "+" else "UNLOAD"
                    gcode_sequence = f"{loadtype}_FILAMENT"
                    await self.send_gcodes_async(gcode_sequence.strip().split('\n'))
            
            self._loop.create_task(_handle_extrude())
        elif action.startswith("start_temp_preset_"):
            material = action.split("_")[3]
            self.temperature_preset_material = material
            if "temperatures." + material in self.config:
                self.temperature_preset_extruder = int(
                    self.config["temperatures." + material]["extruder"]
                )
                self.temperature_preset_bed = int(
                    self.config["temperatures." + material]["heater_bed"]
                )
            else:
                self.temperature_preset_extruder = TEMP_DEFAULTS[material][0]
                self.temperature_preset_bed = TEMP_DEFAULTS[material][1]
            self._loop.create_task(self._navigate_to_page(PAGE_SETTINGS_TEMPERATURE_SET))
        elif action.startswith("preset_temp_step_"):
            size = int(action.split("_")[3])
            self.temperature_preset_step = size
        elif action.startswith("preset_temp_"):
            parts = action.split("_")
            heater = parts[2]
            change = (
                self.temperature_preset_step
                if parts[3] == "up"
                else -self.temperature_preset_step
            )
            if heater == "extruder":
                self.temperature_preset_extruder += change
            else:
                self.temperature_preset_bed += change
            self._loop.create_task(
                self.display.update_preset_temp_ui(
                    self.temperature_preset_step,
                    self.temperature_preset_extruder,
                    self.temperature_preset_bed,
                )
            )
        elif action == "save_temp_preset":
            logger.info("Saving temp preset")
            self.save_temp_preset()
        elif action == "retry_screw_leveling":
            self._loop.create_task(self.display.draw_initial_screw_leveling())
            self._loop.create_task(self.handle_screw_leveling())
        elif action == "begin_full_bed_level":
            self.leveling_mode = "full_bed"
            self._loop.create_task(self._navigate_to_page(PAGE_PRINTING_KAMP))
            self.send_gcode("AUTO_FULL_BED_LEVEL")
        elif action.startswith("zprobe_step_"):
            parts = action.split("_")
            self.z_probe_step = parts[2]
            self._loop.create_task(
                self.display.update_zprobe_leveling_ui(
                    self.z_probe_step, self.z_probe_distance
                )
            )
        elif action.startswith("zprobe_"):
            parts = action.split("_")
            direction = parts[1]
            self.send_gcode(f"TESTZ Z={direction}{self.z_probe_step}")
        elif action == "abort_zprobe":
            self.send_gcode("ABORT")
            self._loop.create_task(self._go_back())
        elif action == "save_zprobe":
            self.send_gcode("ACCEPT")
            self.send_gcode("SAVE_CONFIG")
            self._loop.create_task(self._go_back())
        elif action == "save_config":
            self.send_gcode("SAVE_CONFIG")
            self._loop.create_task(self._go_back())
        elif action.startswith("set_speed_"):
            parts = action.split("_")
            percent = int(parts[2])
            self._loop.create_task(
                self.send_speed_update("print", percent / 100.0)
            )
        elif action.startswith("set_flow_"):
            parts = action.split("_")
            percent = int(parts[2])
            self._loop.create_task(
                self.send_speed_update("flow", percent / 100.0)
            )
        elif action == "reboot_host":
            logger.info("Rebooting Host")
            self._loop.create_task(self._go_back())
            self._loop.create_task(self._navigate_to_page(PAGE_OVERLAY_LOADING))
            self._loop.create_task(self._send_moonraker_request("machine.reboot"))
        elif action == "shutdown_host":
            logger.info("Shutting down Host")
            self._loop.create_task(self.run_shutdown_sequence())
        elif action == "reboot_klipper":
            logger.info("Rebooting Klipper")
            self._loop.create_task(
                self._send_moonraker_request(
                    "machine.services.restart", {"service": "klipper"}
                )
            )
            self._loop.create_task(self._go_back())
            self._loop.create_task(self._navigate_to_page(PAGE_OVERLAY_LOADING))
        elif action == "firmware_restart":
            logger.info("Firmware Restart")
            self._loop.create_task(self._send_moonraker_request("printer.firmware_restart"))
            self._loop.create_task(self._go_back())
            self._loop.create_task(self._navigate_to_page(PAGE_OVERLAY_LOADING))
