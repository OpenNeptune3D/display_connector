"""Printer status updates from Moonraker pushed to the display for DisplayController."""

import time
import asyncio

from src.mapping import (
    PAGE_MAIN,
    PAGE_PRINTING,
    PAGE_PRINTING_COMPLETE,
    PAGE_PRINTING_KAMP,
    PAGE_OVERLAY_LOADING,
    format_time,
)
from src.controller.common import (
    logger,
    PRINTING_PAGES,
    _deep_merge_dicts,
)


class StatusMixin:
    """Printer status updates from Moonraker pushed to the display."""

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

    async def handle_status_update(self, new_data, data_mapping=None):
        if data_mapping is None:
            data_mapping = self.display.mapper.data_mapping
        
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
                        
                        # Cancel existing task under lock
                        task_to_cancel = None
                        async with self._filename_lock:
                            if self._thumbnail_task and not self._thumbnail_task.done():
                                task_to_cancel = self._thumbnail_task
                                self._thumbnail_task = None
                        
                        if task_to_cancel:
                            task_to_cancel.cancel()
                            try:
                                await task_to_cancel
                            except asyncio.CancelledError:
                                pass
                        
                        async with self._filename_lock:
                            self._thumbnail_task = self._loop.create_task(
                                self.load_thumbnail_for_page(
                                    thumbnail_filename,
                                    thumbnail_page_id
                                )
                            )
                        
                elif state_to_process == "complete":
                    self._last_thumbnail_request = None
                    if current_page is None or current_page != PAGE_PRINTING_COMPLETE:
                        await self._navigate_to_page(PAGE_PRINTING_COMPLETE)
                        self._cached_page = None

                else:
                    self._last_thumbnail_request = None
                    if (current_page is None or
                        current_page in PRINTING_PAGES or
                        current_page == PAGE_PRINTING_COMPLETE or
                        current_page == PAGE_OVERLAY_LOADING):
                        await self._navigate_to_page(PAGE_MAIN, clear_history=True)
                        self._cached_page = None
                    elif current_page == PAGE_MAIN:
                        # Already on main (e.g. after Klipper firmware restart while idle).
                        # _navigate_to_page is a no-op when current_page == target, so call
                        # special_page_handling directly to redraw wifi icon, model name, and
                        # custom bar without issuing an unnecessary page-switch to the HMI.
                        try:
                            await self.special_page_handling(PAGE_MAIN)
                        except Exception as e:
                            logger.error(f"Error refreshing main page after reconnect: {e}")

        if "print_duration" in new_data.get("print_stats", {}):
            self.current_print_duration = new_data["print_stats"]["print_duration"]

        if "bed_mesh" in new_data:
            if self._rapid_scan_mode or current_page == PAGE_PRINTING_KAMP:
                logger.info("Bed mesh update received from Moonraker - bed leveling complete")
                if self._rapid_scan_mode:
                    self._loop.create_task(
                        self.display.update_kamp_text("Scan complete!")
                    )
                self.bed_leveling_probed_count = 0
                self.bed_leveling_counts = self.full_bed_leveling_counts
                self._rapid_scan_mode = False
                self._bed_leveling_complete = True
                if self.leveling_mode == "full_bed" and self.current_state not in ("printing", "paused"):
                    self._loop.create_task(self.display.show_bed_mesh_final())
                else:
                    self._loop.create_task(self._handle_bed_leveling_complete())

        progress = new_data.get("display_status", {}).get("progress", 0)
        if progress > 0.001 and current_page == PAGE_PRINTING_KAMP:
            logger.info("Print progress > 0 while on KAMP page - restoring printing page")
            self.bed_leveling_probed_count = 0
            self.bed_leveling_counts = self.full_bed_leveling_counts
            self._rapid_scan_mode = False
            self._bed_leveling_complete = True
            self._loop.create_task(self._handle_bed_leveling_complete())

        try:
            if progress > 0.001 and "print_duration" in new_data.get("print_stats", {}):
                total_time = self.current_print_duration / progress
                remaining_time = format_time(total_time - self.current_print_duration)
                await self.display.update_time_remaining(remaining_time)
        except (ZeroDivisionError, ValueError) as e:
            logger.warning(f"Error calculating remaining time: {e}")

        self._update_misc_states(new_data, data_mapping)

    async def _run_coalesced_update(self, initial_data, data_mapping):
        """Process initial_data then drain any deltas that accumulated while running."""
        await self.display.update_data(initial_data, data_mapping)
        while self._pending_update_data is not None:
            pending = self._pending_update_data
            self._pending_update_data = None
            await self.display.update_data(pending, data_mapping)

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

        needs_speed_ui_update = False

        if "fan" in new_data:
            self.fan_state = float(new_data["fan"]["speed"]) > 0
            self.printing_target_speeds["fan"] = float(new_data["fan"]["speed"])
            needs_speed_ui_update = True

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
                needs_speed_ui_update = True

            speed_factor = new_data["gcode_move"].get("speed_factor")
            if speed_factor is not None:
                self.printing_target_speeds["print"] = float(speed_factor)
                needs_speed_ui_update = True

        if needs_speed_ui_update:
            if self._speed_ui_task and not self._speed_ui_task.done():
                self._speed_ui_task.cancel()
            self._speed_ui_task = self._loop.create_task(
                self.display.update_printing_speed_settings_ui(
                    self.printing_selected_speed_type,
                    self.printing_target_speeds[self.printing_selected_speed_type],
                )
            )

        if self._update_data_task and not self._update_data_task.done():
            # Task is still running — accumulate the delta so no field change is lost.
            # Moonraker sends only changed fields per notification; cancelling the running
            # task and starting fresh would silently discard fields (e.g. light pin state,
            # progress) that won't appear in subsequent notifications if they don't change again.
            if self._pending_update_data is None:
                self._pending_update_data = {}
            _deep_merge_dicts(self._pending_update_data, new_data)
        else:
            self._pending_update_data = None
            self._update_data_task = self._loop.create_task(
                self._run_coalesced_update(new_data, data_mapping)
            )

    def printer_heating_value_changed(self, heater, new_value):
            if heater == self.printing_selected_heater:
                self._loop.create_task(
                    self.display.update_printing_heater_settings_ui(
                        self.printing_selected_heater,
                        new_value,
                    )
                )
