import json
import sys
import logging
import pathlib
import re
import os
import os.path
import time
import io
import asyncio
import traceback
import aiohttp
import signal
import systemd.daemon

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

# Global flag for graceful shutdown
_shutdown_requested = False

# Create module-level logger and placeholder for event loop
logger = logging.getLogger(__name__)
loop = None

def signal_handler(signum, frame):
    global _shutdown_requested, loop
    _shutdown_requested = True
    logger.info("Received signal %s, initiating graceful shutdown...", signum)
    try:
        # Only attempt to stop the loop if it exists and is running.
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
    except Exception:
        # Log the error instead of swallowing it silently
        logger.exception("Unexpected error in signal_handler")

# Register signal handlers
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

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
    # Normalize display name to avoid None/whitespace/case issues
    disp = (display or "").strip().lower()

    # OpenNeptune variants
    if disp == "openneptune":
        if model == MODEL_CUSTOM:
            return CustomDisplayCommunicator
        elif model in MODELS_N4:
            return OpenNeptune4DisplayCommunicator
        elif model in MODELS_N3:
            return OpenNeptune3DisplayCommunicator

    # Default to Elegoo-compatible communicators for everything else (including empty/None)
    if model == MODEL_CUSTOM:
        return CustomDisplayCommunicator
    elif model in MODELS_N4:
        return ElegooNeptune4DisplayCommunicator
    elif model in MODELS_N3:
        return ElegooNeptune3DisplayCommunicator

    # Final fallback to avoid returning None (log to make debugging easier)
    logger.warning(f"get_communicator: unknown display '{display}' or unsupported model '{model}', falling back to ElegooNeptune4DisplayCommunicator")
    return ElegooNeptune4DisplayCommunicator

SOCKET_LIMIT = 20 * 1024 * 1024

class ResourceManager:
    
    def __init__(self):
        self._thread_pool = None
        self._shutdown = False
        self._lock = asyncio.Lock()
    
    def get_thread_pool(self):
        """Get thread pool, creating it if necessary"""
        if self._thread_pool is None and not self._shutdown:
            logger.info("Creating new thread pool")
            self._thread_pool = ThreadPoolExecutor(max_workers=2)
        return self._thread_pool
    
    async def cleanup(self):
        if self._shutdown or not self._thread_pool:
            return
        
        self._shutdown = True
        tp = self._thread_pool
        self._thread_pool = None 
        
        try:
            tp.shutdown(wait=False, cancel_futures=True)
            logger.info("Thread pool shutdown initiated (non-blocking)")
        except Exception as e:
            logger.warning(f"Exception during thread pool shutdown: {e}")
    
    def allow_new_pool(self):
        """Allow creating a new thread pool after shutdown"""
        logger.info("Allowing new thread pool creation")
        self._shutdown = False


class DisplayController:
    last_config_change = 0
    filament_sensor_name = "filament_sensor"

    def __init__(self, config, loop):
        self._loop = loop
        self.pending_reqs_lock = asyncio.Lock()
        self.config = config
        self._handle_config()
        self.connected = False

        self._cached_printer_model = None
        self._display_initialized = False
        
        display_type = self.config.safe_get("general", "display_type", "elegoo")
        printer_model = self.get_printer_model() 
        self.display = get_communicator(display_type, printer_model)(
            logger,
            printer_model,
            event_handler=self.display_event_handler,
            port=self.config.safe_get("general", "serial_port"),
        )
        self._handle_display_config()

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

        self.resources = ResourceManager()

        self._speed_lock = asyncio.Lock()

        self.REQUEST_TIMEOUT = 1200  # seconds 
        self._cleanup_task = None

        self._last_thumbnail_request = None
        self._thumbnail_retry_lock = asyncio.Lock()
        self._bed_leveling_complete = False
        self._thumbnail_displayed = False  
        self._thumbnail_task = None 

        self._is_reconnecting = False
        self._listen_task = None
        self._is_listening = False
        self._process_stream_task = None

        self._history_lock = asyncio.Lock()
        self._reconnect_lock = asyncio.Lock()

        self._files_lock = asyncio.Lock()


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
        if self._cached_printer_model is not None:
            return self._cached_printer_model
        
        # Check config first
        try:
            if "general" in self.config:
                if "printer_model" in self.config["general"]:
                    self._cached_printer_model = self.config["general"]["printer_model"]
                    return self._cached_printer_model
        except Exception as e:
            logger.warning(f"Error reading printer model from config: {e}")
        
        # Read from file
        try:
            with open("/boot/.OpenNept4une.txt", "r") as file:
                for line in file:
                    try:
                        if line.startswith(tuple(SUPPORTED_PRINTERS)):
                            model_part = line.split("-")[0].strip()
                            self._cached_printer_model = model_part
                            return self._cached_printer_model
                    except Exception as e:
                        logger.warning(f"Error parsing line '{line}': {e}")
                        continue
        except FileNotFoundError:
            logger.error("Printer model file not found at /boot/.OpenNept4une.txt")
        except Exception as e:
            logger.error(f"Error reading printer model file: {e}")
        
        # Default
        logger.info(f"Using default printer model: {MODEL_N4_REGULAR}")
        self._cached_printer_model = MODEL_N4_REGULAR
        return self._cached_printer_model

    async def special_page_handling(self, current_page):
        """Handle special page setup. Called after navigation completes."""
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
            # Safely get filename under lock
            async with self._filename_lock:
                filename = self.current_filename
            
            if filename:
                self._loop.create_task(self.set_data_prepare_screen(filename))
            else:
                logger.warning("PAGE_CONFIRM_PRINT reached but no filename set")
                
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
        """Navigate to a page without holding locks during I/O operations."""
        
        # Cancel any pending thumbnail task when navigating (outside lock)
        if self._thumbnail_task and not self._thumbnail_task.done():
            self._thumbnail_task.cancel()
            try:
                await self._thumbnail_task
            except asyncio.CancelledError:
                pass
        
        # PHASE 1: Check bed leveling block (under lock - DATA ONLY)
        async with self._history_lock:
            current_page = self.history[-1] if self.history else None
            
            if current_page == PAGE_PRINTING_KAMP and not self._bed_leveling_complete and page != PAGE_PRINTING:
                logger.info("Preventing navigation during bed leveling")
                return
        
        # PHASE 2: Handle KAMP special case
        async with self._history_lock:
            current_page = self.history[-1] if self.history else None
            need_printing_first = (
                page == PAGE_PRINTING_KAMP and 
                (not self.history or current_page not in PRINTING_PAGES)
            )
        
        if need_printing_first:
            async with self._history_lock:
                if clear_history:
                    self.history.clear()
                self.history.append(PAGE_PRINTING)
                # Do mapping under lock (fast dict lookup)
                mapped_printing = self.display.mapper.map_page(PAGE_PRINTING)
            
            # Navigate (outside lock - I/O)
            await self.display.navigate_to(mapped_printing)
            await asyncio.sleep(0.1)
            
            logger.debug(f"Navigating to {PAGE_PRINTING}")
            
            try:
                await self.special_page_handling(PAGE_PRINTING)
            except Exception as e:
                logger.error(f"Error in special page handling for PRINTING: {e}")
            
            await asyncio.sleep(0.1)
        
        # PHASE 3: Normal navigation path
        should_navigate = False
        mapped_page = None
        
        async with self._history_lock:
            current_page = self.history[-1] if self.history else None
            
            if not self.history or current_page != page:
                # Decide what to do with history
                if page in TABBED_PAGES and self.history and current_page in TABBED_PAGES:
                    self.history[-1] = page
                else:
                    if clear_history and page != PAGE_PRINTING_KAMP:
                        self.history.clear()
                    self.history.append(page)
                
                should_navigate = True
                # Do mapping under lock (fast)
                mapped_page = self.display.mapper.map_page(page)
        
        # Action phase (outside lock - I/O)
        if should_navigate:
            await self.display.navigate_to(mapped_page)
            logger.debug(f"Navigating to {page}")

            try:
                await self.special_page_handling(page)
            except Exception as e:
                logger.error(f"Error in special page handling for {page}: {e}")

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

    async def send_speed_update(self, speed_type, new_speed):
        """Update speed/flow/fan without holding lock during I/O."""
        gcode_script = None
        new_target_value = None

        if speed_type == "print":
            factor = float(new_speed)
            percent = factor * 100.0
            gcode_script = f"M220 S{percent:.0f}"
            new_target_value = factor

        elif speed_type == "flow":
            factor = float(new_speed)
            percent = factor * 100.0
            gcode_script = f"M221 S{percent:.0f}"
            new_target_value = factor

        elif speed_type == "fan":
            factor = min(max(float(new_speed), 0.0), 1.0)   # clamp 0–1
            value = int(round(factor * 255))
            gcode_script = f"M106 S{value}"
            new_target_value = factor

        try:
            if gcode_script:
                await self._send_moonraker_request(
                    "printer.gcode.script",
                    {"script": gcode_script},
                )

            async with self._speed_lock:
                if new_target_value is not None:
                    self.printing_target_speeds[speed_type] = new_target_value
                ui_speed_type = self.printing_selected_speed_type
                ui_speed_value = self.printing_target_speeds[ui_speed_type]

            await self.display.update_printing_speed_settings_ui(
                ui_speed_type,
                ui_speed_value,
            )
        except Exception as e:
            logger.error(f"Error updating speed: {e}")
            raise

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
        """Navigate back without holding locks during I/O operations."""
        
        # PHASE 0: Cancel any pending thumbnail task (outside lock - OK)
        if self._thumbnail_task and not self._thumbnail_task.done():
            self._thumbnail_task.cancel()
            try:
                await self._thumbnail_task
            except asyncio.CancelledError:
                pass
        
        # PHASE 1: Check if we have history (quick check under lock)
        async with self._history_lock:
            history_len = len(self.history)
            if history_len <= 1:
                logger.debug("Already at the main page.")
                return  # ← This is the ONLY place this message should appear
            
            # Get current page WITHOUT releasing lock (safe - no await)
            current_page = self.history[-1] if self.history else None
        
        # PHASE 2: Handle FILES special case (outside lock)
        if current_page == PAGE_FILES and self.current_dir != "":
            self.current_dir = "/".join(self.current_dir.split("/")[:-1])
            self.files_page = 0
            await self._load_files()  # I/O outside lock
            return
        
        # PHASE 3: Pop history and determine navigation (under lock - DATA ONLY)
        back_page = None
        mapped_page = None
        
        async with self._history_lock:
            if len(self.history) <= 1:
                return  # Double-check
            
            # Pop current page
            self.history.pop()
            
            # Pop any transition pages
            while len(self.history) > 1 and self.history[-1] in TRANSITION_PAGES:
                self.history.pop()
            
            # Get target page
            if len(self.history) > 0:
                back_page = self.history[-1]
                # Map page under lock (it's just a dict lookup - fast and safe)
                mapped_page = self.display.mapper.map_page(back_page)
        
        # PHASE 4: Navigate (outside lock - I/O)
        if back_page is None or mapped_page is None:
            logger.debug("No valid page to navigate back to.")
            return
        
        await self.display.navigate_to(mapped_page)
        logger.debug(f"Navigating back to {back_page}")
        
        # PHASE 5: Special page handling (outside lock - I/O)
        try:
            await self.special_page_handling(back_page)
        except Exception as e:
            logger.error(f"Error in special page handling: {e}")
        
        # PHASE 6: Handle thumbnail retry for printing page (outside lock)
        if back_page == PAGE_PRINTING:
            async with self._filename_lock:
                has_filename = self.current_filename is not None
                has_last_request = self._last_thumbnail_request is not None
                is_displayed = self._thumbnail_displayed
                filename = self.current_filename
            
            if has_filename and not is_displayed:
                if has_last_request:
                    self._thumbnail_task = self._loop.create_task(
                        self.retry_last_thumbnail()
                    )
                else:
                    self._thumbnail_task = self._loop.create_task(
                        self.load_thumbnail_for_page(
                            filename,
                            self._page_id(PAGE_PRINTING)
                        )
                    )

    def start_listening(self):
        # Don't start if already listening
        if self._is_listening and self._listen_task and not self._listen_task.done():
            logger.debug("Listen task already running, skipping...")
            return
        
        self._is_listening = True
        self._listen_task = self._loop.create_task(self.listen())

    async def listen(self):
        logger.info("Starting listen task")
        try:
            self._is_listening = True

            # Allow thread pool recreation after potential shutdown
            self.resources.allow_new_pool()

            
            # Connect to display
            try:
                await self.display.connect()
                await self.display.check_valid_version()
            except Exception as e:
                logger.error(f"Failed to connect to display: {e}")
                raise
            
            # Connect to Moonraker
            try:
                await self.connect_moonraker()
            except Exception as e:
                logger.error(f"Failed to connect to Moonraker: {e}")
                raise
            
            # Subscribe to printer objects
            try:
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
                
                # Safely extract data with error handling
                if "result" in ret and "status" in ret["result"]:
                    data = ret["result"]["status"]
                    logger.info("Display Type: " + str(self.display.get_display_type_name()))
                    logger.info("Printer Model: " + str(self.display.get_device_name()))
                    
                    # Only initialize display once
                    if not self._display_initialized:
                        await self.display.initialize_display()
                        self._display_initialized = True
                    
                    await self.handle_status_update(data)
                else:
                    logger.error(f"Unexpected response format from printer.objects.subscribe: {ret}")
                    raise Exception("Failed to subscribe to printer objects")
                
                # Now wait for the process_stream task to complete (keeps connection alive)
                logger.info("Listen task now monitoring connection...")
                if self._process_stream_task:
                    logger.info("Process stream task completed, connection closed")
                else:
                    logger.warning("No process_stream task found!")
                    
            except Exception as e:
                logger.error(f"Error in subscription or stream processing: {e}")
                raise
                
        except asyncio.CancelledError:
            logger.info("Listen task cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in listen(): {e}")
            logger.error(traceback.format_exc())
            # Trigger reconnection after a delay
            await asyncio.sleep(2)
            self._is_listening = False
            await self._attempt_reconnect()
        finally:
            self._is_listening = False
            logger.debug("Listen task exiting, _is_listening flag cleared")

    async def _cleanup_stale_requests(self):
        #Periodically clean up stale requests
        while True:
            try:
                current_time = time.time()
                async with self.pending_reqs_lock:
                    # Store request timestamps in a separate dict
                    stale_requests = [
                        req_id for req_id, (fut, timestamp) in self.pending_reqs.items()
                        if not fut.done() and (current_time - timestamp) > self.REQUEST_TIMEOUT
                    ]
                    for req_id in stale_requests:
                        fut, _ = self.pending_reqs.pop(req_id)
                        fut.set_exception(asyncio.TimeoutError(f"Request {req_id} timed out"))
                await asyncio.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
                await asyncio.sleep(60)

    async def _send_moonraker_request(self, method, params=None):
        if params is None:
            params = {}
        message = self._make_rpc_msg(method, **params)
        fut = self._loop.create_future()
        
        # Store request with timestamp
        async with self.pending_reqs_lock:
            self.pending_reqs[message["id"]] = (fut, time.time())
            
        # Start cleanup task if not running
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = self._loop.create_task(self._cleanup_stale_requests())
            
        try:
            data = json.dumps(message).encode() + b"\x03"
            self.writer.write(data)
            await self.writer.drain()
            return await asyncio.wait_for(fut, timeout=self.REQUEST_TIMEOUT)
        except asyncio.TimeoutError:
            async with self.pending_reqs_lock:
                self.pending_reqs.pop(message["id"], None)
            raise
        except Exception:
            logger.exception("Unexpected error _send_moonraker_request")
            await self.close()
            raise

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
                self._process_stream_task = self._loop.create_task(self._process_stream(reader))
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
                    break  # Exit the connection retry loop

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

        # Now identify with Moonraker - wrapped in try/except
        try:
            ret = await self._send_moonraker_request(
                "server.connection.identify",
                {
                    "client_name": "OpenNept4une Display Connector",
                    "version": "0.0.1",
                    "type": "other",
                    "url": "https://github.com/halfbearman/opennept4une",
                },
            )
            
            # Check for error response
            if "error" in ret:
                error_code = ret["error"].get("code")
                error_msg = ret["error"].get("message", "Unknown error")
                
                # Error 400 "already identified" is acceptable - just log and continue
                if error_code == 400 and "already identified" in error_msg.lower():
                    logger.warning(f"Connection already identified: {error_msg}")
                    # Continue execution - don't return or raise
                else:
                    # Other errors are logged but don't crash - we're already connected
                    logger.error(f"Failed to identify with Moonraker: {error_msg}")
                    # Don't raise - we can still function without identification
            elif "result" in ret:
                logger.debug(
                    f"Client Identified With Moonraker: {ret['result']['connection_id']}"
                )
        except Exception as e:
            logger.error(f"Exception during Moonraker identification: {e}")
            # Don't crash - we're already connected and can function

        # Get system info - also wrapped for safety
        try:
            system_response = await self._send_moonraker_request("machine.system_info")
            if "result" in system_response:
                system = system_response["result"]["system_info"]
                self.display.ips = ", ".join(self._find_ips(system["network"]))
            else:
                logger.warning("Could not retrieve system info")
        except Exception as e:
            logger.error(f"Error getting system info: {e}")
            # Continue anyway - not critical

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

    async def handle_custom_touch(self, x, y):
        current_page = await self._get_current_page()  
        if current_page in custom_touch_actions:
            actions = custom_touch_actions[current_page]
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
                await self.handle_custom_touch(data.x, data.y)
        elif type == EventType.SLIDER_INPUT:
            self.handle_input(data.page_id, data.component_id, data.value)
        elif type == EventType.NUMERIC_INPUT:
            self.handle_input(data.page_id, data.component_id, data.value)
        elif type == EventType.RECONNECTED:
            logger.info("Reconnected to Display")
            # Clear history so we don't fight with a stale page stack
            async with self._history_lock:
                self.history = []
            # Choose a page based on current printer state to avoid "variable name invalid"
            state = getattr(self, "current_state", None)
            target = PAGE_MAIN
            if state in ("printing", "paused") and not self._bed_leveling_complete:
                target = PAGE_PRINTING
            elif state == "complete":
                target = PAGE_PRINTING_COMPLETE
            await self._navigate_to_page(target, clear_history=True)
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
                    request_data = self.pending_reqs.pop(item["id"], None)
                    if request_data is not None:
                        fut, _ = request_data
                        fut.set_result(item)
            elif item["method"] == "notify_status_update":
                await self.handle_status_update(item["params"][0])
            elif item["method"] == "notify_gcode_response":
                await self.handle_gcode_response(item["params"][0])  
        logger.info("Unix Socket Disconnection from _process_stream()")
        await self.close()

    def handle_machine_config_change(self, new_data):
        def safe_int_convert(value, default=0):
            try:
                return int(float(value))  # Handle both string and float inputs
            except (ValueError, TypeError):
                logger.warning(f"Invalid position value: {value}")
                return default

        max_x, max_y, max_z = 0, 0, 0
        if "config" in new_data:
            if "stepper_x" in new_data["config"]:
                if "position_max" in new_data["config"]["stepper_x"]:
                    max_x = int(float(new_data["config"]["stepper_x"]["position_max"])) #added conversion from float numbers, stripping decimal part
            if "stepper_y" in new_data["config"]:
                if "position_max" in new_data["config"]["stepper_y"]:
                    max_y = int(float(new_data["config"]["stepper_y"]["position_max"])) #added conversion from float numbers, stripping decimal part
            if "stepper_z" in new_data["config"]:
                if "position_max" in new_data["config"]["stepper_z"]:
                    max_z = int(float(new_data["config"]["stepper_z"]["position_max"])) #added conversion from float numbers, stripping decimal part

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
        async with self._reconnect_lock:
            if self._is_reconnecting:
                logger.debug("Reconnection already in progress, skipping...")
                return
            self._is_reconnecting = True
            try:
                # Close existing connection
                if self.writer and not self.writer.is_closing():
                    try:
                        self.writer.close()
                        await self.writer.wait_closed()
                    except Exception as e:
                        logger.debug(f"Error closing writer: {e}")
                
                self.connected = False
                
                logger.info("Attempting to reconnect to Moonraker...")
                await asyncio.sleep(1)
                
                # Clear the listening flag if it's stuck
                self._is_listening = False

                # Allow thread pool recreation
                self.resources.allow_new_pool()
                
                self.start_listening()
            finally:
                self._is_reconnecting = False

    async def _get_current_page_unsafe(self):
        """Get current page WITHOUT lock - caller must hold _history_lock"""
        if len(self.history) > 0:
            return self.history[-1]
        return None

    async def _get_current_page(self):
        """Get current page safely with timeout protection"""
        try:
            async with asyncio.timeout(5.0):
                async with self._history_lock:
                    return await self._get_current_page_unsafe()
        except asyncio.TimeoutError:
            logger.error("DEADLOCK DETECTED in _get_current_page() - lock timeout after 5s")
            import traceback
            logger.error("Stack trace:\n" + "".join(traceback.format_stack()))
            return None

    async def set_data_prepare_screen(self, filename):
        """Set prepare screen data without holding lock during I/O."""
        
        # PHASE 1: Cancel existing task and store filename (under lock - DATA ONLY)
        task_to_cancel = None
        async with self._filename_lock:
            # Get reference to task to cancel
            if self._thumbnail_task and not self._thumbnail_task.done():
                task_to_cancel = self._thumbnail_task
                self._thumbnail_task = None
            
            # Store filename
            current_filename = filename
        
        # PHASE 2: Cancel task if needed (outside lock - ASYNC OPERATION)
        if task_to_cancel:
            task_to_cancel.cancel()
            try:
                await task_to_cancel
            except asyncio.CancelledError:
                pass
        
        # PHASE 3: Load metadata and update display (outside lock - NETWORK + DISPLAY I/O)
        metadata = await self.load_metadata(current_filename)
        await self.display.set_data_prepare_screen(current_filename, metadata)
        
        # PHASE 4: Create new thumbnail task (under lock - DATA ONLY)
        async with self._filename_lock:
            self._thumbnail_task = self._loop.create_task(
                self.load_thumbnail_for_page(
                    current_filename, self._page_id(PAGE_CONFIRM_PRINT), metadata
                )
            )

    async def load_metadata(self, filename):
        metadata = await self._send_moonraker_request(
            "server.files.metadata", {"filename": filename}
        )
        return metadata["result"]

    async def load_thumbnail_for_page(self, filename, page_number, metadata=None):
        logger.info(f"Loading thumbnail for {filename}")
        
        # Store the request details for potential retry
        self._last_thumbnail_request = {
            'filename': filename,
            'page_number': page_number,
            'metadata': metadata
        }
        self._thumbnail_displayed = False
        
        # Check if we're still on the correct page before starting
        current_page = await self._get_current_page()  
        current_page_id = self._page_id(current_page) if current_page else None
        
        if current_page_id != page_number:
            logger.info(f"Page changed before thumbnail load started (expected {page_number}, got {current_page_id})")
            return
        
        # Don't try to load thumbnail if we're in bed leveling
        if current_page == PAGE_PRINTING_KAMP:
            logger.info("Deferring thumbnail load during bed leveling")
            return

        if metadata is None:
            metadata = await self.load_metadata(filename)
        
        best_thumbnail = self.find_best_thumbnail(metadata)
        if not best_thumbnail:
            logger.warning(f"No suitable thumbnail found for {filename}")
            current_page = await self._get_current_page()  
            if current_page and self._page_id(current_page) == page_number:
                await self.display.hide_thumbnail()
            return

        path = self.construct_thumbnail_path(filename, best_thumbnail["relative_path"])
        
        async with self._thumbnail_retry_lock:
            try:
                image = await self.fetch_and_parse_thumbnail(path)
                if image is None:
                    await self.display.hide_thumbnail()
                    return
                
                # Double-check we're still on the correct page before displaying
                current_page = await self._get_current_page()  
                current_page_id = self._page_id(current_page) if current_page else None
                
                if current_page_id != page_number:
                    logger.info(f"Page changed during thumbnail load (expected {page_number}, got {current_page_id}), skipping display")
                    return
                
                logger.info("Displaying the thumbnail")
                await self.display.display_thumbnail(page_number, image)
                logger.info("Thumbnail displayed successfully")
                self._thumbnail_displayed = True
            except asyncio.CancelledError:
                logger.info("Thumbnail loading cancelled")
                raise
            except Exception as e:
                logger.error(f"Error displaying thumbnail: {e}")

    async def retry_last_thumbnail(self):
        #Retry loading the last thumbnail if there was one
        if self._last_thumbnail_request:
            async with self._thumbnail_retry_lock:
                try:
                    await self.load_thumbnail_for_page(
                        self._last_thumbnail_request['filename'],
                        self._last_thumbnail_request['page_number'],
                        self._last_thumbnail_request['metadata']
                    )
                except Exception as e:
                    logger.error(f"Error retrying thumbnail: {e}")

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
        thumbnail = None
        try:
            # Construct URL first
            url = f"{self.config.safe_get('general', 'moonraker_url', 'http://localhost:7125')}/server/files/gcodes/{self.pathname2url(path)}"
            
            logger.info(f"Fetching thumbnail image from {url}")
            
            # PHASE 1: Fetch image with timeout
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        raise aiohttp.ClientError(f"Failed to fetch thumbnail, status code: {resp.status}")
                    img_data = await resp.read()
            
            thumbnail = Image.open(io.BytesIO(img_data))
            
            # Safely access config
            background = "29354a"  # default color
            try:
                if "thumbnails" in self.config:
                    background = self.config["thumbnails"].get("background_color", background)
            except Exception as e:
                logger.warning(f"Error accessing thumbnail config: {e}")
            
            logger.info("Starting thumbnail parsing")
            loop = asyncio.get_running_loop()

            # Get thread pool (will be created if needed)
            thread_pool = self.resources.get_thread_pool()
            if thread_pool is None:
                logger.error("Thread pool unavailable (shutdown state)")
                return None
            
            # PHASE 2: Parse image with timeout (10 seconds max)
            try:
                image = await asyncio.wait_for(
                    loop.run_in_executor(
                        thread_pool,
                        parse_thumbnail,
                        thumbnail,
                        160,
                        160,
                        background
                    ),
                    timeout=10.0  # Timeout added!
                )
            except asyncio.TimeoutError:
                logger.error(f"Thumbnail parsing timed out after 10 seconds for {path}")
                return None
            
            logger.info("Thumbnail parsing completed")
            return image
            
        except asyncio.TimeoutError:
            logger.error(f"Thumbnail fetch timed out for {path}")
            return None
        except Exception as e:
            logger.error(f"Error in thumbnail processing: {e}")
            return None
        finally:
            if thumbnail is not None:
                try:
                    thumbnail.close()
                except Exception:
                    logger.exception("Unexpected error fetch_and_parse_thumbnail")
                    pass

    async def handle_status_update(self, new_data, data_mapping=None):
        if data_mapping is None:
            data_mapping = self.display.mapper.data_mapping
        
        # RATE LIMITING: Only check page max once per second
        if not hasattr(self, '_last_page_check_time'):
            self._last_page_check_time = 0
            self._cached_page = None
            self._page_check_lock = asyncio.Lock()  # NEW: Separate lock
        
        now = time.time()
        time_since_last_check = now - self._last_page_check_time
        
        # Determine if we need to check the page
        has_state_change = (
            "print_stats" in new_data and 
            new_data["print_stats"].get("state") is not None
        )
        
        # Check page if: state changed OR >1 second elapsed
        if has_state_change or time_since_last_check > 1.0:
            # Use dedicated lock to avoid blocking history operations
            async with self._page_check_lock:
                async with self._history_lock:
                    current_page = self.history[-1] if self.history else None
                self._cached_page = current_page
                self._last_page_check_time = now
        else:
            # Use cached value (no lock needed for read)
            current_page = self._cached_page
        
        if current_page == PAGE_MAIN:
            await asyncio.sleep(0.1)

        if "print_stats" in new_data:
            should_load_thumbnail = False
            thumbnail_filename = None
            thumbnail_page_id = None
            state_to_process = None
            needs_state_ui_update = False
            
            # PHASE 1: Read/update data under lock (DATA ONLY)
            async with self._filename_lock:
                filename = new_data["print_stats"].get("filename")
                if filename:
                    filename_changed = (self.current_filename != filename)
                    self.current_filename = filename
                    
                    if filename_changed:
                        self._thumbnail_displayed = False
                        logger.info(f"Filename changed to: {filename}")
                
                # FIX: If filename wasn't in this update but we have it stored, add it back
                # This ensures the mapping system always has the filename to display
                elif self.current_filename:
                    new_data["print_stats"]["filename"] = self.current_filename

                state = new_data["print_stats"].get("state")
                if state:
                    self.current_state = state
                    logger.info(f"Status Update: {state}")
                    state_to_process = state
                    
                    if state in ["printing", "paused"]:
                        needs_state_ui_update = True
                        
                        if (current_page is None or current_page not in PRINTING_PAGES) and not self._bed_leveling_complete:
                            pass  # Will navigate below
                            
                        elif current_page in PRINTING_PAGES:
                            if self.current_filename and not self._thumbnail_displayed:
                                if (not self._last_thumbnail_request or 
                                    self._last_thumbnail_request.get('filename') != self.current_filename):
                                    should_load_thumbnail = True
                                    thumbnail_filename = self.current_filename
                                    thumbnail_page_id = self._page_id(PAGE_PRINTING)
                                    
                    elif state == "complete":
                        if current_page is None or current_page != PAGE_PRINTING_COMPLETE:
                            pass  # Will navigate below
                            
                    else:
                        if (current_page is None or 
                            current_page in PRINTING_PAGES or 
                            current_page == PAGE_PRINTING_COMPLETE or 
                            current_page == PAGE_OVERLAY_LOADING):
                            pass  # Will navigate below
            
            # PHASE 2: Update UI if needed (outside lock - DISPLAY I/O)
            if needs_state_ui_update:
                await self.display.update_printing_state_ui(state_to_process)

            # PHASE 3: Handle navigation and thumbnail loading (outside lock - I/O)
            if state_to_process:
                # On state change, re-check page to be safe
                if has_state_change:
                    current_page = await self._get_current_page()
                    self._cached_page = current_page
                
                if state_to_process in ["printing", "paused"]:
                    # Navigate if not on a printing page
                    if (current_page is None or current_page not in PRINTING_PAGES) and not self._bed_leveling_complete:
                        # Reset thumbnail flag BEFORE navigation
                        self._thumbnail_displayed = False
                        
                        await self._navigate_to_page(PAGE_PRINTING, clear_history=True)
                        self._cached_page = None
                        
                        # After navigation, prepare thumbnail load
                        async with self._filename_lock:
                            if self.current_filename:
                                should_load_thumbnail = True
                                thumbnail_filename = self.current_filename
                                thumbnail_page_id = self._page_id(PAGE_PRINTING)
                    
                    # Load thumbnail if needed
                    if should_load_thumbnail and thumbnail_filename:
                        logger.info(f"Loading thumbnail for {thumbnail_filename} on printing page")
                        if self._thumbnail_task and not self._thumbnail_task.done():
                            self._thumbnail_task.cancel()
                            try:
                                await self._thumbnail_task
                            except asyncio.CancelledError:
                                pass
                        
                        self._thumbnail_task = self._loop.create_task(
                            self.load_thumbnail_for_page(
                                thumbnail_filename,
                                thumbnail_page_id
                            )
                        )
                        
                elif state_to_process == "complete":
                    if current_page is None or current_page != PAGE_PRINTING_COMPLETE:
                        await self._navigate_to_page(PAGE_PRINTING_COMPLETE)
                        self._cached_page = None
                        
                else:
                    if (current_page is None or 
                        current_page in PRINTING_PAGES or 
                        current_page == PAGE_PRINTING_COMPLETE or 
                        current_page == PAGE_OVERLAY_LOADING):
                        await self._navigate_to_page(PAGE_MAIN, clear_history=True)
                        self._cached_page = None

        if "print_duration" in new_data.get("print_stats", {}):
            self.current_print_duration = new_data["print_stats"]["print_duration"]

        progress = new_data.get("display_status", {}).get("progress", 0)
        try:
            if progress > 0.001 and "print_duration" in new_data.get("print_stats", {}):
                total_time = self.current_print_duration / progress
                remaining_time = format_time(total_time - self.current_print_duration)
                await self.display.update_time_remaining(remaining_time)
        except (ZeroDivisionError, ValueError) as e:
            logger.warning(f"Error calculating remaining time: {e}")

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
        
        # Cancel the process_stream task if it's still running
        if self._process_stream_task and not self._process_stream_task.done():
            self._process_stream_task.cancel()
            try:
                await self._process_stream_task
            except asyncio.CancelledError:
                pass
        
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        
        await self.resources.cleanup()

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

    async def handle_gcode_response(self, response):
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
            current_page = await self._get_current_page()  
            if current_page != PAGE_PRINTING_KAMP:
                self._loop.create_task(self._navigate_to_page(PAGE_PRINTING_KAMP, clear_history=True))
        elif response.startswith("// probe at"):
            current_page = await self._get_current_page()  
            if current_page != PAGE_PRINTING_KAMP:
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
            current_page = await self._get_current_page()  
            if current_page == PAGE_PRINTING_KAMP:
                self._bed_leveling_complete = True
                if self.leveling_mode == "full_bed":
                    self._loop.create_task(self.display.show_bed_mesh_final())
                else:
                    self._loop.create_task(self._handle_bed_leveling_complete())

    async def _handle_bed_leveling_complete(self):
        #Handle completion of bed leveling and ensure thumbnail is loaded
        try:
            logger.info("Bed leveling complete, returning to printing page")
            # Navigate back to printing page
            await self._navigate_to_page(PAGE_PRINTING, clear_history=True)
            
            # Give the UI time to settle and ensure we're on the printing page
            await asyncio.sleep(1)
            
            # Double check we're on the printing page before retrying thumbnail
            current_page = await self._get_current_page()  
            if current_page == PAGE_PRINTING and self._last_thumbnail_request and not self._thumbnail_displayed:
                logger.info("Retrying thumbnail load after bed leveling")
                await self.load_thumbnail_for_page(
                    self._last_thumbnail_request['filename'],
                    self._last_thumbnail_request['page_number'],
                    self._last_thumbnail_request['metadata']
                )
        except Exception as e:
            logger.error(f"Error handling bed leveling completion: {e}")
        finally:
            self._bed_leveling_complete = False

    async def run_shutdown_sequence(self):
        await self.display.show_shutdown_screens()
        await asyncio.sleep(1)
        await self._send_moonraker_request("machine.shutdown")



loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
config_observer = Observer()

try:
    # load config and inject the loop
    config = ConfigHandler(config_file, logger)
    controller = DisplayController(config, loop)

    # called when the config file changes
    def handle_wd_callback(notifier):
        try:
            controller.handle_config_change()
        except Exception as e:
            logger.error(f"Error handling config file change: {e}")
            logger.error(traceback.format_exc())

    # called when the klipper/moonraker socket appears
    def handle_sock_changes(notifier):
        try:
            if notifier.event_type == "created":
                logger.info(
                    f"{notifier.src_path.split('/')[-1]} created. Attempting to reconnect..."
                )
                controller.klipper_restart_event.set()
        except Exception as e:
            logger.error(f"Error handling socket change: {e}")
            logger.error(traceback.format_exc())

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

    # Notify systemd we're ready
    systemd.daemon.notify('READY=1')
    logger.info("Service ready, notified systemd")

    # Watchdog ping task
    async def watchdog_ping():
        while not _shutdown_requested:
            try:
                systemd.daemon.notify('WATCHDOG=1')
                await asyncio.sleep(30)  # Ping every 30 seconds (WatchdogSec=60)
            except Exception as e:
                logger.error(f"Watchdog ping failed: {e}")

    # Start watchdog ping
    loop.create_task(watchdog_ping())

    # after one second, start pumping display events
    loop.call_later(1, controller.start_listening)

    # hand control over to asyncio
    loop.run_forever()

except Exception as e:
    logger.error("Error communicating...: " + str(e))
    logger.error(traceback.format_exc())
finally:
    _shutdown_requested = True
    systemd.daemon.notify('STOPPING=1')
    logger.info("Shutting down service...")
    
    config_observer.stop()
    if config_observer.is_alive():
        config_observer.join(timeout=5)
    
    # Ensure all tasks are cancelled (Py 3.13 safe)
    try:
        asyncio.get_running_loop()   # raises if no loop is running
        pending = asyncio.all_tasks()
    except RuntimeError:
        pending = set()

    for task in list(pending):
        task.cancel()

    if pending:
        try:
            loop.run_until_complete(asyncio.wait(pending, timeout=5))
        except RuntimeError:
            # Loop may already be closed or not runnable here; best-effort shutdown.
            pass
    
    loop.close()
    logger.info("Service stopped")
