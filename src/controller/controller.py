"""DisplayController: wires the touch screen to Klipper via Moonraker.

The behaviour lives in the mixins imported below, one area per module.
"""

import sys
import logging
import re
import os
import os.path
import time
import asyncio

from src.neptune4 import (
    MODEL_N4_REGULAR
)
from src.mapping import (
    filename_regex_wrapper,
    PAGE_OVERLAY_LOADING,
)
from src.controller.common import (
    logger,
    file_log,
    SUPPORTED_PRINTERS,
    get_communicator,
)
from src.controller.resources import ResourceManager
from src.controller.navigation import NavigationMixin
from src.controller.actions import ActionsMixin
from src.controller.printer_commands import PrinterCommandsMixin
from src.controller.files import FilesMixin
from src.controller.thumbnails import ThumbnailsMixin
from src.controller.moonraker import MoonrakerMixin
from src.controller.listener import ListenerMixin
from src.controller.display_events import DisplayEventsMixin
from src.controller.status import StatusMixin
from src.controller.gcode_responses import GcodeResponseMixin


class DisplayController(
    NavigationMixin,
    ActionsMixin,
    PrinterCommandsMixin,
    FilesMixin,
    ThumbnailsMixin,
    MoonrakerMixin,
    ListenerMixin,
    DisplayEventsMixin,
    StatusMixin,
    GcodeResponseMixin,
):
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
        self._rapid_scan_mode = False

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
        self._speed_ui_task = None
        self._update_data_task = None
        self._ips_retry_task = None
        self._pending_update_data = None

        self._is_reconnecting = False
        self._listen_task = None
        self._is_listening = False
        self._process_stream_task = None

        self._history_lock = asyncio.Lock()
        self._reconnect_lock = asyncio.Lock()

        self._files_lock = asyncio.Lock()

        self._last_page_check_time = 0
        self._cached_page = None
        self._page_check_lock = asyncio.Lock()

        self._http_session = None

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

    async def close(self):
        if not self.connected:
            return
        self.connected = False

        # Cancel all pending request futures       
        async with self.pending_reqs_lock:
            for fut, _ in list(self.pending_reqs.values()):
                if not fut.done():
                    fut.set_exception(ConnectionError("Connection closed"))
            self.pending_reqs.clear()
        
        # Cancel process_stream task only if it's not the current task (avoid self-cancellation)
        current_task = asyncio.current_task()
        if self._process_stream_task and not self._process_stream_task.done():
            if self._process_stream_task is not current_task:
                self._process_stream_task.cancel()
                try:
                    await self._process_stream_task
                except asyncio.CancelledError:
                    pass
        
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self._cleanup_task = None

        if self._speed_ui_task and not self._speed_ui_task.done():
            self._speed_ui_task.cancel()
        self._speed_ui_task = None

        if self._ips_retry_task and not self._ips_retry_task.done():
            self._ips_retry_task.cancel()
        self._ips_retry_task = None

        if self._update_data_task and not self._update_data_task.done():
            self._update_data_task.cancel()
        self._update_data_task = None
        self._pending_update_data = None

        if self._http_session and not self._http_session.closed:
            await self._http_session.close()
        self._http_session = None

        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

        await self.resources.cleanup()

    async def run_shutdown_sequence(self):
        await self.display.show_shutdown_screens()
        await asyncio.sleep(1)
        await self._send_moonraker_request("machine.shutdown")
