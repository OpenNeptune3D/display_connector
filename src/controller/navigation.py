"""Page navigation and back-stack handling for DisplayController."""

import asyncio

from src.mapping import (
    PAGE_FILES,
    PAGE_SHUTDOWN_DIALOG,
    PAGE_PREPARE_MOVE,
    PAGE_PREPARE_EXTRUDER,
    PAGE_SETTINGS_TEMPERATURE_SET,
    PAGE_LEVELING,
    PAGE_LEVELING_SCREW_ADJUST,
    PAGE_LEVELING_Z_OFFSET_ADJUST,
    PAGE_CONFIRM_PRINT,
    PAGE_PRINTING,
    PAGE_PRINTING_KAMP,
    PAGE_PRINTING_FILAMENT,
    PAGE_PRINTING_SPEED,
    PAGE_PRINTING_ADJUST,
)
from src.controller.common import (
    logger,
    PRINTING_PAGES,
    TABBED_PAGES,
    TRANSITION_PAGES,
)


class NavigationMixin:
    """Page navigation and back-stack handling."""

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
            if not self._rapid_scan_mode:                                                       
                await self.display.draw_kamp_page(self.bed_leveling_counts)
            return  

        await self.display.special_page_handling(current_page)

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
            # For pages rendered entirely via raw draw commands (e.g. shutdown_dialog on
            # none_9), cancel any in-flight data-update task first. Its writes target
            # main-page components and compete for _serial_lock, delaying the dialog
            # content writes and leaving a blank screen longer than necessary.
            if page == PAGE_SHUTDOWN_DIALOG:
                if self._update_data_task and not self._update_data_task.done():
                    self._update_data_task.cancel()
                    self._update_data_task = None
                self._pending_update_data = None

            await self.display.navigate_to(mapped_page)
            logger.debug(f"Navigating to {page}")

            try:
                await self.special_page_handling(page)
            except Exception as e:
                logger.error(f"Error in special page handling for {page}: {e}")

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
                return
            
            # Get current page WITHOUT releasing lock (safe - no await)
            current_page = self.history[-1] if self.history else None
        
        # PHASE 2: Handle FILES special case (with proper file locking)
        if current_page == PAGE_FILES:
            should_load_files = False
            async with self._files_lock:
                if self.current_dir != "":
                    self.current_dir = "/".join(self.current_dir.split("/")[:-1])
                    self.files_page = 0
                    should_load_files = True
            if should_load_files:
                await self._load_files()
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
        
        # PHASE 4: Perform navigation (outside lock - I/O)
        if back_page is not None and mapped_page is not None:
            await self.display.navigate_to(mapped_page)
            logger.debug(f"Navigating back to {back_page}")
        
        # PHASE 5: Handle special page logic (outside lock - may do I/O)
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

    async def _get_current_page_unsafe(self):
        """Get current page WITHOUT lock - caller must hold _history_lock"""
        if len(self.history) > 0:
            return self.history[-1]
        return None

    async def _get_current_page(self):
        """Get current page safely with timeout protection"""
        async def locked():
            async with self._history_lock:
                return await self._get_current_page_unsafe()

        try:
            # asyncio.timeout() needs Python 3.11; wait_for works on every supported version
            return await asyncio.wait_for(locked(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error("DEADLOCK DETECTED in _get_current_page() - lock timeout after 5s")
            import traceback
            logger.error("Stack trace:\n" + "".join(traceback.format_stack()))
            return None
