import json
import sys
import logging
import pathlib
import requests
import re
import os
import os.path
import time
import io
import asyncio
import traceback
import aiohttp
from PIL import Image

from src.config import TEMP_DEFAULTS, ConfigHandler
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
from math import ceil
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from src.tjc import EventType
from src.response_actions import response_actions, input_actions, custom_touch_actions
from src.lib_col_pic import parse_thumbnail
from src.communicator import DisplayCommunicator
from src.neptune4 import (
    MODEL_N4_REGULAR,
    MODEL_N4_PRO,
    MODEL_N4_PLUS,
    MODEL_N4_MAX,
    MODELS_N4,
    ElegooNeptune4DisplayCommunicator,
    OpenNeptune4DisplayCommunicator
)
from src.elegoo_neptune3 import MODELS_N3, ElegooNeptune3DisplayCommunicator, OpenNeptune3DisplayCommunicator
from src.elegoo_custom import MODEL_CUSTOM, CustomDisplayCommunicator
from src.mapping import (
    build_format_filename,
    filename_regex_wrapper,
    PAGE_MAIN,
    PAGE_FILES,
    PAGE_PREPARE_MOVE,
    PAGE_PREPARE_TEMP,
    PAGE_PREPARE_EXTRUDER,
    PAGE_SETTINGS_TEMPERATURE_SET,
    PAGE_LEVELING,
    PAGE_LEVELING_SCREW_ADJUST,
    PAGE_LEVELING_Z_OFFSET_ADJUST,
    PAGE_CONFIRM_PRINT,
    PAGE_PRINTING,
    PAGE_PRINTING_KAMP,
    PAGE_PRINTING_PAUSE,
    PAGE_PRINTING_STOP,
    PAGE_PRINTING_EMERGENCY_STOP,
    PAGE_PRINTING_COMPLETE,
    PAGE_PRINTING_FILAMENT,
    PAGE_PRINTING_SPEED,
    PAGE_PRINTING_ADJUST,
    PAGE_OVERLAY_LOADING,
    format_time,
)
from src.colors import BACKGROUND_SUCCESS, BACKGROUND_WARNING

log_file = os.path.expanduser("~/printer_data/logs/display_connector.log")
logger = logging.getLogger(__name__)
ch_log = logging.StreamHandler(sys.stdout)
ch_log.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
ch_log.setFormatter(formatter)
logger.addHandler(ch_log)
file_log = logging.FileHandler(log_file)
file_log.setLevel(logging.ERROR)
file_log.setFormatter(formatter)
logger.addHandler(file_log)
logger.setLevel(logging.DEBUG)

comms_directory = os.path.expanduser("~/printer_data/comms")
config_file = os.path.expanduser("~/printer_data/config/display_connector.cfg")

PRINTING_PAGES = [
    PAGE_PRINTING,
    PAGE_PRINTING_FILAMENT,
    PAGE_PRINTING_PAUSE,
    PAGE_PRINTING_STOP,
    PAGE_PRINTING_EMERGENCY_STOP,
    PAGE_PRINTING_FILAMENT,
    PAGE_PRINTING_SPEED,
    PAGE_PRINTING_ADJUST,
]

TABBED_PAGES = [
    PAGE_PREPARE_EXTRUDER,
    PAGE_PREPARE_MOVE,
    PAGE_PREPARE_TEMP,
    PAGE_PRINTING_ADJUST,
    PAGE_PRINTING_FILAMENT,
    PAGE_PRINTING_SPEED,
]

TRANSITION_PAGES = [PAGE_OVERLAY_LOADING]

SUPPORTED_PRINTERS = [MODEL_N4_REGULAR, MODEL_N4_PRO, MODEL_N4_PLUS, MODEL_N4_MAX]


def get_communicator(display, model) -> DisplayCommunicator:
    if display == "openneptune":
        if model == MODEL_CUSTOM:
            return CustomDisplayCommunicator
        elif model in MODELS_N4:
            return OpenNeptune4DisplayCommunicator
        elif model in MODELS_N3:
            return OpenNeptune3DisplayCommunicator
    else:
        if model == MODEL_CUSTOM:
            return CustomDisplayCommunicator
        elif model in MODELS_N4:
            return ElegooNeptune4DisplayCommunicator
        elif model in MODELS_N3:
            return ElegooNeptune3DisplayCommunicator


SOCKET_LIMIT = 20 * 1024 * 1024


class DisplayController:
    last_config_change = 0
    filament_sensor_name = "filament_sensor"

    def __init__(self, config, loop):
        self._loop = loop
        self._filename_lock = asyncio.Lock()
        self.pending_reqs_lock = asyncio.Lock()
        self.config = config
        self._handle_config()
        self.connected = False

        display_type = self.config.safe_get("general", "display_type")
        printer_model = self.get_printer_model()
        self.display = get_communicator(display_type, printer_model)(
            logger,
            printer_model,
            event_handler=self.display_event_handler,
            port=self.config.safe_get("general", "serial_port"),
        )
        self._handle_display_config()

        # Initialize lock for current_filename
        self._filename_lock = asyncio.Lock()
        self.current_filename = None

        self.part_light_state = False
        self.frame_light_state = False
        self.fan_state = False
        self.filament_sensor_state = False

        self.move_distance = "1"
        self.xy_move_speed = 130
        self.z_move_speed = 10
        self.z_offset_distance = "0.01"
        self.out_fd = sys.stdout.fileno()
        os.set_blocking(self.out_fd, False)
        self.pending_req = {}
        self.pending_reqs = {}
        self.history = []
        self.current_state = "booting"

        self.dir_contents = []
        self.current_dir = ""
        self.files_page = 0

        self.printing_selected_heater = "extruder"
        self.printing_target_temps = {
            "extruder": 0,
            "heater_bed": 0,
            "heater_bed_outer": 0,
        }
        self.printing_selected_temp_increment = "10"
        self.printing_selected_speed_type = "print"
        self.printing_target_speeds = {"print": 1.0, "flow": 1.0, "fan": 1.0}
        self.printing_selected_speed_increment = "10"

        self.extrude_amount = 50
        self.extrude_speed = 300

        self.temperature_preset_material = "pla"
        self.temperature_preset_step = 10
        self.temperature_preset_extruder = 0
        self.temperature_preset_bed = 0

        self.leveling_mode = None
        self.screw_probe_count = 0
        self.screw_levels = {}
        self.z_probe_step = "0.1"
        self.z_probe_distance = "0.0"

        self.full_bed_leveling_counts = [0, 0]
        self.bed_leveling_counts = [0, 0]
        self.bed_leveling_probed_count = 0
        self.bed_leveling_last_position = None

        self.klipper_restart_event = asyncio.Event()

    def pathname2url(self, path):
        return quote(path.replace("\\", "/"))

    def handle_config_change(self):
        if self.last_config_change + 5 > time.time():
            return
        self.last_config_change = time.time()
        logger.info("Config file changed, Reloading")
        self._loop.create_task(self._navigate_to_page(PAGE_OVERLAY_LOADING))
        self.config.reload_config()
        self._handle_config()
        self._loop.create_task(self._go_back())

    def _handle_config(self):
        logger.info("Loading config")
        if "general" in self.config:
            if "clean_filename_regex" in self.config["general"]:
                filename_regex_wrapper["default"] = re.compile(
                    self.config["general"]["clean_filename_regex"]
                )
            if "filament_sensor_name" in self.config["general"]:
                self.filament_sensor_name = self.config["general"][
                    "filament_sensor_name"
                ]

        if "LOGGING" in self.config:
            if "file_log_level" in self.config["LOGGING"]:
                file_log.setLevel(self.config["LOGGING"]["file_log_level"])
                logger.setLevel(logging.DEBUG)
        if "prepare" in self.config:
            prepare = self.config["prepare"]
            if "move_distance" in prepare:
                distance = prepare["move_distance"]
                if distance in ["0.1", "1", "10"]:
                    self.move_distance = distance
            self.xy_move_speed = prepare.getint("xy_move_speed", fallback=130)
            self.z_move_speed = prepare.getint("z_move_speed", fallback=10)
            self.extrude_amount = prepare.getint("extrude_amount", fallback=50)
            self.extrude_speed = prepare.getint("extrude_speed", fallback=300)

    def _handle_display_config(self):
        self.display.mapper.set_filament_sensor_name(self.filament_sensor_name)
        if "main_screen" in self.config:
            if "display_name" in self.config["main_screen"]:
                self.display.display_name_override = self.config["main_screen"][
                    "display_name"
                ]
            if "display_name_line_color" in self.config["main_screen"]:
                self.display.display_name_line_color = self.config["main_screen"][
                    "display_name_line_color"
                ]
        if "print_screen" in self.config:
            if "z_display" in self.config["print_screen"]:
                self.display.mapper.set_z_display(
                    self.config["print_screen"]["z_display"]
                )
            if "clean_filename_regex" in self.config["print_screen"]:
                filename_regex_wrapper["printing"] = re.compile(
                    self.config["print_screen"]["clean_filename_regex"]
                )

    def get_printer_model(self):
        if "general" in self.config:
            if "printer_model" in self.config["general"]:
                return self.config["general"]["printer_model"]
        try:
            with open("/boot/.OpenNept4une.txt", "r") as file:
                for line in file:
                    if line.startswith(tuple(SUPPORTED_PRINTERS)):
                        model_part = line.split("-")[0].strip()
                        return model_part
        except FileNotFoundError:
            logger.error("File not found")
        except Exception as e:
            logger.error(f"Error reading file: {e}")
        return None

    async def special_page_handling(self, current_page):
        if current_page == PAGE_FILES:
            await self.display.show_files_page(
                self.current_dir, self.dir_contents, self.files_page
            )
        elif current_page == PAGE_PREPARE_MOVE:
            await self.display.update_prepare_move_ui(self.move_distance)
        elif current_page == PAGE_PREPARE_EXTRUDER:
            await self.display.update_prepare_extrude_ui(
                self.extrude_amount, self.extrude_speed
            )
        elif current_page == PAGE_SETTINGS_TEMPERATURE_SET:
            await self.display.update_preset_temp_ui(
                self.temperature_preset_step,
                self.temperature_preset_extruder,
                self.temperature_preset_bed,
            )
        elif current_page == PAGE_CONFIRM_PRINT:
            self._loop.create_task(self.set_data_prepare_screen(self.current_filename))
        elif current_page == PAGE_PRINTING_FILAMENT:
            await self.display.update_printing_heater_settings_ui(
                self.printing_selected_heater,
                self.printing_target_temps[self.printing_selected_heater],
            )
            await self.display.update_printing_temperature_increment_ui(
                self.printing_selected_temp_increment
            )
        elif current_page == PAGE_PRINTING_ADJUST:
            await self.display.update_printing_zoffset_increment_ui(
                self.z_offset_distance
            )
        elif current_page == PAGE_PRINTING_SPEED:
            await self.display.update_printing_speed_settings_ui(
                self.printing_selected_speed_type,
                self.printing_target_speeds[self.printing_selected_speed_type],
            )
            await self.display.update_printing_speed_increment_ui(
                self.printing_selected_speed_increment
            )
        elif current_page == PAGE_LEVELING:
            self.leveling_mode = None
        elif current_page == PAGE_LEVELING_SCREW_ADJUST:
            await self.display.draw_initial_screw_leveling()
            self._loop.create_task(self.handle_screw_leveling())
        elif current_page == PAGE_LEVELING_Z_OFFSET_ADJUST:
            await self.display.draw_initial_zprobe_leveling(self.z_probe_step, self.z_probe_distance)
            self._loop.create_task(self.handle_zprobe_leveling())
        elif current_page == PAGE_PRINTING_KAMP:
            await self.display.draw_kamp_page(self.bed_leveling_counts)
            return

        await self.display.special_page_handling(current_page)

    async def send_gcodes_async(self, gcodes):
        for gcode in gcodes:
            logger.debug("Sending GCODE: " + gcode)
            await self._send_moonraker_request(
                "printer.gcode.script", {"script": gcode}
            )
            await asyncio.sleep(0.1)

    def send_gcode(self, gcode):
        logger.debug("Sending GCODE: " + gcode)
        self._loop.create_task(
            self._send_moonraker_request("printer.gcode.script", {"script": gcode})
        )

    def move_axis(self, axis, distance):
        speed = self.xy_move_speed if axis in ["X", "Y"] else self.z_move_speed
        self.send_gcode(f"G91\nG1 {axis}{distance} F{int(speed) * 60}\nG90")

    async def _navigate_to_page(self, page, clear_history=False):
        # 1) Special case: if you want KAMP but aren’t already on a PRINTING page,
        #    first go to PRINTING (respecting clear_history), then fall through to KAMP.
        if page == PAGE_PRINTING_KAMP and (not self.history or self.history[-1] not in PRINTING_PAGES):
            # navigate to PRINTING first
            if clear_history:
                self.history.clear()
            self.history.append(PAGE_PRINTING)
            mapped_printing = self.display.mapper.map_page(PAGE_PRINTING)
            await self.display.navigate_to(mapped_printing)
            logger.debug(f"Navigating to {PAGE_PRINTING}")
            # run any printing-page special logic (if you have any)
            await self.special_page_handling(PAGE_PRINTING)
            # now proceed to the real target: KAMP
            # (do NOT clear_history a second time)
        
        # 2) The normal navigation path (skips if you’re already on `page`)
        if not self.history or self.history[-1] != page:
            # Handle page navigation within tabbed pages
            if page in TABBED_PAGES and self.history and self.history[-1] in TABBED_PAGES:
                self.history[-1] = page
            else:
                if clear_history and page != PAGE_PRINTING_KAMP:
                    # only clear history here if it wasn't already the printing step above
                    self.history.clear()
                self.history.append(page)

            # map & navigate
            mapped = self.display.mapper.map_page(page)
            await self.display.navigate_to(mapped)
            logger.debug(f"Navigating to {page}")

            # finally, invoke your per-page overlays or fallback
            await self.special_page_handling(page)

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
            current_speed = self.printing_target_speeds[
                self.printing_selected_speed_type
            ]
            change = int(self.printing_selected_speed_increment) * (
                1 if direction == "+" else -1
            )
            self.send_speed_update(
                self.printing_selected_speed_type,
                (current_speed + (change / 100.0)) * 100,
            )
        elif action == "speed_reset":
            self.send_speed_update(self.printing_selected_speed_type, 1.0)
        elif action.startswith("files_page_"):
            parts = action.split("_")
            direction = parts[2]
            self.files_page = int(
                max(
                    0,
                    min(
                        (len(self.dir_contents) / 5),
                        self.files_page + (1 if direction == "next" else -1),
                    ),
                )
            )
            self._loop.create_task(
            self.display.show_files_page(self.current_dir, self.dir_contents, self.files_page)
            )
        elif action.startswith("open_file_"):
            parts = action.split("_")
            index = int(parts[2])
            selected = self.dir_contents[(self.files_page * 5) + index]
            if selected["type"] == "dir":
                self.current_dir = selected["path"]
                self.files_page = 0
                self._loop.create_task(self._load_files())
            else:
                self.current_filename = selected["path"]
                self._loop.create_task(self._navigate_to_page(PAGE_CONFIRM_PRINT))
        elif action == "print_opened_file":
            self._loop.create_task(self._go_back())
            self._loop.create_task(self._navigate_to_page(PAGE_OVERLAY_LOADING))
            self._loop.create_task(
                self._send_moonraker_request(
                    "printer.print.start", {"filename": self.current_filename}
                )
            )
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
            if self.current_state != "printing":  # Check if the state is not 'printing'
                parts = action.split("_")
                direction = parts[1]
                loadtype = "LOAD" if direction == "+" else "UNLOAD"
                # Send GCODE commands in sequence:
                gcode_sequence = f"""
                {loadtype}_FILAMENT
                """
                # Send the full GCODE sequence
                self._loop.create_task(self.send_gcodes_async(gcode_sequence.strip().split('\n')))
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
            speed = int(parts[2])
            self.send_speed_update("print", speed)
        elif action.startswith("set_flow_"):
            parts = action.split("_")
            speed = int(parts[2])
            self.send_speed_update("flow", speed)
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

    async def _handle_pause_resume(self):
        if self.current_state == "paused":
            logger.info("Resuming print")
            await self._send_moonraker_request("printer.print.resume")
        else:
            await self._go_back()
            await self._navigate_to_page(PAGE_PRINTING_PAUSE)

    async def _handle_pause_confirm(self):
        await self._go_back()
        logger.info("Pausing print")
        await self._send_moonraker_request("printer.print.pause")

    def _set_light(self, light_name, new_state):
        gcode = f"{light_name}_{'ON' if new_state else 'OFF'}"
        self.send_gcode(gcode)

    def _toggle_filament_sensor(self, state):
        gcode = f"SET_FILAMENT_SENSOR SENSOR={self.filament_sensor_name} ENABLE={'1' if state else '0'}"
        self.send_gcode(gcode)

    def save_temp_preset(self):
        if "temperatures." + self.temperature_preset_material not in self.config:
            self.config["temperatures." + self.temperature_preset_material] = {}
        self.config.set(
            "temperatures." + self.temperature_preset_material,
            "extruder",
            str(self.temperature_preset_extruder),
        )
        self.config.set(
            "temperatures." + self.temperature_preset_material,
            "heater_bed",
            str(self.temperature_preset_bed),
        )
        self.config.write_changes()
        self._loop.create_task(self._go_back())

    def send_speed_update(self, speed_type, new_speed):
        if new_speed != 1.0:                        
            if speed_type == "print":
                self.send_gcode(f"M220 S{new_speed:.0f}")
            elif speed_type == "flow":
                self.send_gcode(f"M221 S{new_speed:.0f}")
            elif speed_type == "fan":
                new_speed = int(new_speed)          
                value = min(max(((new_speed) / 100) * 255, 0), 255) 
                self.send_gcode(f"M106 S{value}")
        else:                                       
            if speed_type == "print":               
                self.send_gcode("M220 S100")        
            elif speed_type == "flow":              
                self.send_gcode("M221 S100")        
            elif speed_type == "fan":               
                self.send_gcode("M106 S0")         
        #edited for more stable print interface

    def _toggle_fan(self, state):
        gcode = f"M106 S{'255' if state else '0'}"
        self.send_gcode(gcode)

    def _build_path(self, *components):
        path = ""
        for component in components:
            if component is None or component == "" or component == "/":
                continue
            path += f"/{component}"
        return path[1:]

    def sort_dir_contents(self, dir_contents):
        key = "modified"
        reverse = True
        if "files" in self.config:
            files_config = self.config["files"]
            if "sort_by" in files_config:
                key = files_config["sort_by"]
            if "sort_order" in files_config:
                reverse = files_config["sort_order"] == "desc"
        return sorted(dir_contents, key=lambda k: k[key], reverse=reverse)

    async def _load_files(self):
        data = await self._send_moonraker_request(
            "server.files.get_directory",
            {"path": "/".join(["gcodes", self.current_dir])},
        )
        dir_info = data["result"]
        self.dir_contents = []
        dirs = []
        for item in dir_info["dirs"]:
            if not item["dirname"].startswith("."):
                dirs.append(
                    {
                        "type": "dir",
                        "path": self._build_path(self.current_dir, item["dirname"]),
                        "size": item["size"],
                        "modified": item["modified"],
                        "name": item["dirname"],
                    }
                )
        files = []
        for item in dir_info["files"]:
            if item["filename"].endswith(".gcode"):
                files.append(
                    {
                        "type": "file",
                        "path": self._build_path(self.current_dir, item["filename"]),
                        "size": item["size"],
                        "modified": item["modified"],
                        "name": build_format_filename()(item["filename"]),
                    }
                )
        sort_folders_first = True
        if "files" in self.config:
            sort_folders_first = self.config["files"].getboolean(
                "sort_folders_first", fallback=True
            )
        if sort_folders_first:
            self.dir_contents = self.sort_dir_contents(dirs) + self.sort_dir_contents(
                files
            )
        else:
            self.dir_contents = self.sort_dir_contents(dirs + files)
        await self.display.show_files_page(
            self.current_dir, self.dir_contents, self.files_page
        )

    def _page_id(self, page):
        return self.display.mapper.map_page(page)

    async def _go_back(self):
        if len(self.history) > 1:
            # 1) If we’re in FILES and can step up a directory, do that first
            if self._get_current_page() == PAGE_FILES and self.current_dir != "":
                # pop one level
                self.current_dir = "/".join(self.current_dir.split("/")[:-1])
                self.files_page = 0
                # await the reload completely before returning
                await self._load_files()
                return

            # 2) Otherwise pop any transition pages and step back
            self.history.pop()
            while len(self.history) > 1 and self.history[-1] in TRANSITION_PAGES:
                self.history.pop()
            back_page = self.history[-1]

            # 3) Navigate and then run any special handling, strictly in sequence
            mapped = self.display.mapper.map_page(back_page)
            await self.display.navigate_to(mapped)
            logger.debug(f"Navigating back to {back_page}")
            await self.special_page_handling(back_page)
        else:
            logger.debug("Already at the main page.")

    def start_listening(self):
        self._loop.create_task(self.listen())

    async def listen(self):
        await self.display.connect()
        await self.display.check_valid_version()
        await self.connect_moonraker()
        ret = await self._send_moonraker_request(
            "printer.objects.subscribe",
            {
                "objects": {
                    "gcode_move": ["extrude_factor", "speed_factor", "homing_origin"],
                    "motion_report": ["live_position", "live_velocity"],
                    "fan": ["speed"],
                    "heater_bed": ["temperature", "target"],
                    "extruder": ["temperature", "target"],
                    "heater_generic heater_bed_outer": ["temperature", "target"],
                    "display_status": ["progress"],
                    "print_stats": [
                        "state",
                        "print_duration",
                        "filename",
                        "total_duration",
                        "info",
                    ],
                    "output_pin Part_Light": ["value"],
                    "output_pin Frame_Light": ["value"],
                    "configfile": ["config"],
                    f"filament_switch_sensor {self.filament_sensor_name}": ["enabled"],
                }
            },
        )
        data = ret["result"]["status"]
        logger.info("Display Type: " + str(self.display.get_display_type_name()))
        logger.info("Printer Model: " + str(self.display.get_device_name()))
        await self.display.initialize_display()
        await self.handle_status_update(data)

    async def _send_moonraker_request(self, method, params=None):
        if params is None:
            params = {}
        message = self._make_rpc_msg(method, **params)
        fut = self._loop.create_future()
        async with self.pending_reqs_lock:
            self.pending_reqs[message["id"]] = fut
        data = json.dumps(message).encode() + b"\x03"
        try:
            self.writer.write(data)
            await self.writer.drain()
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close()
        return await fut

    def _find_ips(self, network):
        ips = []
        for key in network:
            if "ip_addresses" in network[key]:
                for ip in network[key]["ip_addresses"]:
                    if ip["family"] == "ipv4":
                        ips.append(ip["address"])
        return ips

    async def connect_moonraker(self) -> None:
        sockfile = os.path.expanduser("~/printer_data/comms/moonraker.sock")
        sockpath = pathlib.Path(sockfile).expanduser().resolve()
        logger.info(f"Connecting to Moonraker at {sockpath}")
        while True:
            try:
                reader, writer = await asyncio.open_unix_connection(
                    sockpath, limit=SOCKET_LIMIT
                )
                self.writer = writer
                self._loop.create_task(self._process_stream(reader))
                self.connected = True
                logger.info("Connected to Moonraker")

                try:
                    software_version_response = await self._send_moonraker_request(
                        "printer.info"
                    )
                    software_version = software_version_response["result"][
                        "software_version"
                    ]
                    software_version = "-".join(
                        software_version.split("-")[:2]
                    )  # clean up version string
                    # Process the software_version...
                    logger.info(f"Software Version: {software_version}")
                    await self.display.update_klipper_version_ui(software_version)
                    break

                except KeyError:
                    logger.error(
                        "KeyError encountered in software_version_response. Attempting to reconnect."
                    )
                    await asyncio.sleep(5)  # Wait before reconnecting
                    continue  # Retry the connection loop

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error connecting to Moonraker: {e}")
                await asyncio.sleep(5)  # Wait before reconnecting
                continue

        ret = await self._send_moonraker_request(
            "server.connection.identify",
            {
                "client_name": "OpenNept4une Display Connector",
                "version": "0.0.1",
                "type": "other",
                "url": "https://github.com/halfbearman/opennept4une",
            },
        )
        logger.debug(
            f"Client Identified With Moonraker: {ret['result']['connection_id']}"
        )

        system = (await self._send_moonraker_request("machine.system_info"))["result"][
            "system_info"
        ]
        self.display.ips = ", ".join(self._find_ips(system["network"]))

    def _make_rpc_msg(self, method: str, **kwargs):
        msg = {"jsonrpc": "2.0", "method": method}
        uid = id(msg)
        msg["id"] = uid
        self.pending_req = msg
        if kwargs:
            msg["params"] = kwargs
        return msg

    def handle_response(self, page, component):
        if page in response_actions:
            if component in response_actions[page]:
                self.execute_action(response_actions[page][component])
                return
        if component == 0:
            self._loop.create_task(self._go_back())
            return
        logger.info(f"Unhandled Response: {page} {component}")

    def handle_input(self, page, component, value):
        if page in input_actions:
            if component in input_actions[page]:
                self.execute_action(
                    input_actions[page][component].replace("$", str(value))
                )
                return
        logger.info(f"Unhandled Input: {page} {component} {value}")

    def handle_custom_touch(self, x, y):
        if self._get_current_page() in custom_touch_actions:
            actions = custom_touch_actions[self._get_current_page()]
            for key in actions:
                min_x, min_y, max_x, max_y = key
                if min_x < x and x < max_x and min_y < y and y < max_y:
                    self.execute_action(actions[key])
                    return

    async def display_event_handler(self, type, data):
        if type == EventType.TOUCH:
            self.handle_response(data.page_id, data.component_id)
        elif type == EventType.TOUCH_COORDINATE:
            if data.touch_event == 0:
                self.handle_custom_touch(data.x, data.y)
        elif type == EventType.SLIDER_INPUT:
            self.handle_input(data.page_id, data.component_id, data.value)
        elif type == EventType.NUMERIC_INPUT:
            self.handle_input(data.page_id, data.component_id, data.value)
        elif type == EventType.RECONNECTED:
            logger.info("Reconnected to Display")
            self.history = []
            await self.display.initialize_display()
            await self._navigate_to_page(PAGE_MAIN, clear_history=True)
        else:
            logger.info(f"Unhandled Event: {type} {data}")

    async def _process_stream(self, reader: asyncio.StreamReader) -> None:
        errors_remaining: int = 10
        while not reader.at_eof():
            if self.klipper_restart_event.is_set():
                await self._attempt_reconnect()
                self.klipper_restart_event.clear()
            try:
                data = await reader.readuntil(b"\x03")
                decoded = data[:-1].decode(encoding="utf-8")
                item = json.loads(decoded)
            except (ConnectionError, asyncio.IncompleteReadError):
                await self._attempt_reconnect()
                break
            except asyncio.CancelledError:
                raise
            except Exception:
                errors_remaining -= 1
                if not errors_remaining or not self.connected:
                    await self._attempt_reconnect()
                continue
            errors_remaining = 10
            if "id" in item:
                async with self.pending_reqs_lock:
                    fut = self.pending_reqs.pop(item["id"], None)
                if fut is not None:
                    fut.set_result(item)
            elif item["method"] == "notify_status_update":
                await self.handle_status_update(item["params"][0])
            elif item["method"] == "notify_gcode_response":
                self.handle_gcode_response(item["params"][0])
        logger.info("Unix Socket Disconnection from _process_stream()")
        await self.close()

    def handle_machine_config_change(self, new_data):
        max_x, max_y, max_z = 0, 0, 0
        if "config" in new_data:
            if "stepper_x" in new_data["config"]:
                if "position_max" in new_data["config"]["stepper_x"]:
                    max_x = int(new_data["config"]["stepper_x"]["position_max"])
            if "stepper_y" in new_data["config"]:
                if "position_max" in new_data["config"]["stepper_x"]:
                    max_y = int(new_data["config"]["stepper_y"]["position_max"])
            if "stepper_z" in new_data["config"]:
                if "position_max" in new_data["config"]["stepper_x"]:
                    max_z = int(new_data["config"]["stepper_z"]["position_max"])

            if max_x > 0 and max_y > 0 and max_z > 0:
                logger.info(f"Machine Size: {max_x}x{max_y}x{max_z}")
                self._loop.create_task(
                    self.display.update_machine_size_ui(max_x, max_y, max_z)
                )
            if "bed_mesh" in new_data["config"]:
                if "probe_count" in new_data["config"]["bed_mesh"]:
                    parts = new_data["config"]["bed_mesh"]["probe_count"].split(",")
                    self.full_bed_leveling_counts = [int(parts[0]), int(parts[1])]
                    self.bed_leveling_counts = self.full_bed_leveling_counts

    async def _attempt_reconnect(self):
        logger.info("Attempting to reconnect to Moonraker...")
        await asyncio.sleep(1)  # A delay before attempting to reconnect
        self.start_listening()

    def _get_current_page(self):
        if len(self.history) > 0:
            return self.history[-1]
        return None

    async def set_data_prepare_screen(self, filename):
        async with self._filename_lock:
            metadata = await self.load_metadata(filename)
            await self.display.set_data_prepare_screen(filename, metadata)
            await self.load_thumbnail_for_page(
                filename, self._page_id(PAGE_CONFIRM_PRINT), metadata
            )

    async def load_metadata(self, filename):
        metadata = await self._send_moonraker_request(
            "server.files.metadata", {"filename": filename}
        )
        return metadata["result"]

    async def load_thumbnail_for_page(self, filename, page_number, metadata=None):
        logger.info("Loading thumbnail for " + filename)

        if metadata is None:
            metadata = await self.load_metadata(filename)
        
        best_thumbnail = self.find_best_thumbnail(metadata)
        if not best_thumbnail:
            logger.warning(f"No suitable thumbnail found for {filename}")
            if self._get_current_page() == page_number:
                await self.display.hide_thumbnail()
            return

        path = self.construct_thumbnail_path(filename, best_thumbnail["relative_path"])
        image = await self.fetch_and_parse_thumbnail(path)

        if image is None:
            await self.display.hide_thumbnail()
            return
        
        logger.info("Displaying the thumbnail")
        await self.display.display_thumbnail(page_number, image)
        logger.info("Thumbnail displayed successfully")

    def find_best_thumbnail(self, metadata):
        best_thumbnail = None
        for thumbnail in metadata["thumbnails"]:
            if thumbnail["width"] == 160:
                return thumbnail
            if best_thumbnail is None or thumbnail["width"] > best_thumbnail["width"]:
                best_thumbnail = thumbnail
        return best_thumbnail

    def construct_thumbnail_path(self, filename, relative_path):
        path = "/".join(filename.split("/")[:-1])
        if path != "":
            path = path + "/"
        return path + relative_path

    async def fetch_and_parse_thumbnail(self, path):
        url = f"{self.config.safe_get('general', 'moonraker_url', 'http://localhost:7125')}/server/files/gcodes/{self.pathname2url(path)}"
        try:
            logger.info(f"Fetching thumbnail image from {url}")
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as resp:
                    if resp.status != 200:
                        raise aiohttp.ClientError(f"Failed to fetch thumbnail, status code: {resp.status}")
                    img_data = await resp.read()
            logger.info("Thumbnail image fetched successfully")
            thumbnail = Image.open(io.BytesIO(img_data))
            logger.info("Thumbnail image opened successfully")
        except (aiohttp.ClientError, IOError) as e:
            logger.error(f"Failed to fetch or open thumbnail image: {e}")
            return None

        try:
            background = self.config["thumbnails"].get("background_color", "29354a")
            logger.info("Starting thumbnail parsing")
            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor(max_workers=2) as pool:
                image = await loop.run_in_executor(pool, parse_thumbnail, thumbnail, 160, 160, background)
            logger.info("Thumbnail parsing completed")
            return image
        except Exception as e:
            logger.error(f"Error in thumbnail parsing: {e}")
            return None

    async def handle_status_update(self, new_data, data_mapping=None):
        if data_mapping is None:
            data_mapping = self.display.mapper.data_mapping

        if "print_stats" in new_data:
            filename = new_data["print_stats"].get("filename")
            if filename:
                async with self._filename_lock:
                    self.current_filename = filename
                self._loop.create_task(
                    self.load_thumbnail_for_page(self.current_filename, self._page_id(PAGE_PRINTING))
                )

            state = new_data["print_stats"].get("state")
            if state:
                self.current_state = state
                logger.info(f"Status Update: {state}")
                current_page = self._get_current_page()

                if state in ["printing", "paused"]:
                    await self.display.update_printing_state_ui(state)
                    if current_page is None or current_page not in PRINTING_PAGES:
                        await self._navigate_to_page(PAGE_PRINTING, clear_history=True)
                elif state == "complete":
                    if current_page is None or current_page != PAGE_PRINTING_COMPLETE:
                        await self._navigate_to_page(PAGE_PRINTING_COMPLETE)
                else:
                    if (
                        current_page is None
                        or current_page in PRINTING_PAGES
                        or current_page == PAGE_PRINTING_COMPLETE
                        or current_page == PAGE_OVERLAY_LOADING
                    ):
                        await self._navigate_to_page(PAGE_MAIN, clear_history=True)

        if "print_duration" in new_data.get("print_stats", {}):
            self.current_print_duration = new_data["print_stats"]["print_duration"]

        progress = new_data.get("display_status", {}).get("progress", 0)
        if progress > 0 and "print_duration" in new_data.get("print_stats", {}):
            total_time = self.current_print_duration / progress
            remaining_time = format_time(total_time - self.current_print_duration)
            self._loop.create_task(self.display.update_time_remaining(remaining_time))

        self._update_misc_states(new_data, data_mapping)

    def _update_misc_states(self, new_data, data_mapping):
        # Handle other updates: lights, fans, filament sensor, etc.
        if (
            "output_pin Part_Light" in new_data
            and new_data["output_pin Part_Light"]["value"] is not None
        ):
            self.part_light_state = int(new_data["output_pin Part_Light"]["value"]) == 1

        if (
            "output_pin Frame_Light" in new_data
            and new_data["output_pin Frame_Light"]["value"] is not None
        ):
            self.frame_light_state = (
                int(new_data["output_pin Frame_Light"]["value"]) == 1
            )

        if "fan" in new_data:
            self.fan_state = float(new_data["fan"]["speed"]) > 0
            self.printing_target_speeds["fan"] = float(new_data["fan"]["speed"])
            self._loop.create_task(
                self.display.update_printing_speed_settings_ui(
                    self.printing_selected_speed_type,
                    self.printing_target_speeds[self.printing_selected_speed_type],
                )
            )

        # Update other heating values, sensors, etc.
        if f"filament_switch_sensor {self.filament_sensor_name}" in new_data:
            sensor_data = new_data[f"filament_switch_sensor {self.filament_sensor_name}"]
            self.filament_sensor_state = int(sensor_data.get("enabled", 0)) == 1

        if "configfile" in new_data:
            self.handle_machine_config_change(new_data["configfile"])

        if "extruder" in new_data:
            target = new_data["extruder"].get("target")
            if target is not None:
                self.printing_target_temps["extruder"] = target
                self.printer_heating_value_changed("extruder", target)

        if "heater_bed" in new_data:
            target = new_data["heater_bed"].get("target")
            if target is not None:
                self.printing_target_temps["heater_bed"] = target
                self.printer_heating_value_changed("heater_bed", target)

        if "heater_generic heater_bed_outer" in new_data:
            target = new_data["heater_generic heater_bed_outer"].get("target")
            if target is not None:
                self.printing_target_temps["heater_bed_outer"] = target
                self.printer_heating_value_changed("heater_bed_outer", target)

        if "gcode_move" in new_data:
            extrude_factor = new_data["gcode_move"].get("extrude_factor")
            if extrude_factor is not None:
                self.printing_target_speeds["flow"] = float(extrude_factor)
                self._loop.create_task(
                    self.display.update_printing_speed_settings_ui(
                        self.printing_selected_speed_type,
                        self.printing_target_speeds[self.printing_selected_speed_type],
                    )
                )

            speed_factor = new_data["gcode_move"].get("speed_factor")
            if speed_factor is not None:
                self.printing_target_speeds["print"] = float(speed_factor)
                self._loop.create_task(
                    self.display.update_printing_speed_settings_ui(
                        self.printing_selected_speed_type,
                        self.printing_target_speeds[self.printing_selected_speed_type],
                    )
                )

        self._loop.create_task(self.display.update_data(new_data, data_mapping))

    def printer_heating_value_changed(self, heater, new_value):
            if heater == self.printing_selected_heater:
                self._loop.create_task(
                    self.display.update_printing_heater_settings_ui(
                        self.printing_selected_heater,
                        new_value,
                    )
                )

    async def close(self):
        if not self.connected:
            return
        self.connected = False
        self.writer.close()
        await self.writer.wait_closed()

    async def handle_screw_leveling(self):
        self.leveling_mode = "screw"
        self.screw_levels = {}
        self.screw_probe_count = 0
        await self._send_moonraker_request(
            "printer.gcode.script", {"script": "BED_LEVEL_SCREWS_TUNE"}
        )
        await self.display.draw_completed_screw_leveling(self.screw_levels)

    async def handle_zprobe_leveling(self):
        if self.leveling_mode == "zprobe":
            return
        self.leveling_mode = "zprobe"
        self.z_probe_step = "0.1"
        self.z_probe_distance = "0.0"
        await self._navigate_to_page(PAGE_OVERLAY_LOADING)
        await self._send_moonraker_request(
            "printer.gcode.script", {"script": "CALIBRATE_PROBE_Z_OFFSET"}
        )
        await self._go_back()

    def handle_gcode_response(self, response):
        if self.leveling_mode == "screw":
            if "probe at" in response:
                self.screw_probe_count += 1
                self._loop.create_task(
                    self.display.update_screw_level_description(
                        f"Probing Screw No. ({ceil(self.screw_probe_count/3)})..."
                    )
                )
            if "screw (base) :" in response:
                self.screw_levels[response.split("screw")[0][3:].strip()] = "base"
            if "screw :" in response:
                self.screw_levels[
                    response.split("screw")[0][3:].strip()
                ] = response.split("adjust")[1].strip()
        elif self.leveling_mode == "zprobe":
            if "Z position:" in response:
                self.z_probe_distance = response.split("->")[1].split("<-")[0].strip()
                self._loop.create_task(
                    self.display.update_zprobe_leveling_ui(
                        self.z_probe_step, self.z_probe_distance
                    )
                )
        elif "Adapted probe count:" in response:
            parts = response.split(":")[1].split(",")
            x_count = int(parts[0].strip(" ()"))
            y_count = int(parts[1][:-1].strip(" ()"))
            self.bed_leveling_counts = [x_count, y_count]
        elif response.startswith("// Adapted mesh bounds"):
            self.bed_leveling_probed_count = 0
            if self._get_current_page() != PAGE_PRINTING_KAMP:
                self._loop.create_task(self._navigate_to_page(PAGE_PRINTING_KAMP, clear_history=True))
        elif response.startswith("// probe at"):
            if self._get_current_page() != PAGE_PRINTING_KAMP:
                # We are not leveling, likely response came from manual probe e.g. from console,
                # Skip updating the state, otherwise it messes up bed leveling screen when printing
                return
            new_position = response.split(" ")[3]
            if self.bed_leveling_last_position != new_position:
                self.bed_leveling_last_position = new_position
                if self.bed_leveling_probed_count > 0:
                    self._loop.create_task(
                        self.display.draw_kamp_box_index(
                            self.bed_leveling_probed_count - 1,
                            BACKGROUND_SUCCESS,
                            self.bed_leveling_counts,
                        )
                    )
                self.bed_leveling_probed_count += 1
                self._loop.create_task(
                    self.display.draw_kamp_box_index(
                        self.bed_leveling_probed_count - 1,
                        BACKGROUND_WARNING,
                        self.bed_leveling_counts,
                    )
                )
                self._loop.create_task(
                    self.display.update_kamp_text(
                        f"Probing... ({self.bed_leveling_probed_count}/{self.bed_leveling_counts[0]*self.bed_leveling_counts[1]})"
                    )
                )
        elif response.startswith("// Mesh Bed Leveling Complete"):
            self.bed_leveling_probed_count = 0
            self.bed_leveling_counts = self.full_bed_leveling_counts
            if self._get_current_page() == PAGE_PRINTING_KAMP:
                if self.leveling_mode == "full_bed":
                    self._loop.create_task(self.display.show_bed_mesh_final())
                else:
                    self._loop.create_task(self._go_back())

    async def run_shutdown_sequence(self):
        await self.display.show_shutdown_screens()
        await asyncio.sleep(1)
        await self._send_moonraker_request("machine.shutdown")



loop = asyncio.get_event_loop()
config_observer = Observer()

try:
    # load config and inject the loop
    config = ConfigHandler(config_file, logger)
    controller = DisplayController(config, loop)

    # called when the config file changes
    def handle_wd_callback(notifier):
        controller.handle_config_change()

    # called when the klipper/moonraker socket appears
    def handle_sock_changes(notifier):
        if notifier.event_type == "created":
            logger.info(
                f"{notifier.src_path.split('/')[-1]} created. Attempting to reconnect..."
            )
            controller.klipper_restart_event.set()

    # watch the config file
    config_patterns = ["display_connector.cfg"]
    config_event_handler = PatternMatchingEventHandler(
        patterns=config_patterns,
        ignore_patterns=None,
        ignore_directories=True,
        case_sensitive=True,
    )
    config_event_handler.on_modified = handle_wd_callback
    config_event_handler.on_created = handle_wd_callback
    config_observer.schedule(
        config_event_handler, config.file, recursive=False
    )

    # watch the socket directory
    socket_patterns = ["klippy.sock", "moonraker.sock"]
    socket_event_handler = PatternMatchingEventHandler(
        patterns=socket_patterns,
        ignore_patterns=None,
        ignore_directories=True,
        case_sensitive=True,
    )
    socket_event_handler.on_modified = handle_sock_changes
    socket_event_handler.on_created = handle_sock_changes
    socket_event_handler.on_deleted = handle_sock_changes
    config_observer.schedule(
        socket_event_handler, comms_directory, recursive=False
    )

    # start watching files
    config_observer.start()

    # after one second, start pumping display events
    loop.call_later(1, controller.start_listening)

    # hand control over to asyncio
    loop.run_forever()

except Exception as e:
    logger.error("Error communicating...: " + str(e))
    logger.error(traceback.format_exc())
finally:
    config_observer.stop()
    if config_observer.is_alive():
        config_observer.join()
    loop.close()
