"""G-code console responses: screw/z-probe leveling and bed mesh progress for DisplayController."""

import asyncio

from math import ceil

from src.mapping import (
    PAGE_PRINTING,
    PAGE_PRINTING_KAMP,
    PAGE_OVERLAY_LOADING,
)
from src.colors import BACKGROUND_SUCCESS, BACKGROUND_WARNING
from src.controller.common import (
    logger,
)


class GcodeResponseMixin:
    """G-code console responses: screw/z-probe leveling and bed mesh progress."""

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
            if "probe: at" in response:
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
            self.bed_leveling_last_position = None
            self._bed_leveling_complete = False
            # Don't reset _rapid_scan_mode here - it may have been set by
            # "Beginning rapid surface scan" which can come before or after this message
            # Reset leveling_mode for KAMP during printing (not manual full bed level)
            if self.current_state in ("printing", "paused"):
                self.leveling_mode = None
            current_page = await self._get_current_page()
            if current_page != PAGE_PRINTING_KAMP:
                self._loop.create_task(self._navigate_to_page(PAGE_PRINTING_KAMP, clear_history=True))
        elif "Beginning rapid surface scan" in response or "Touch home at" in response:
            # Rapid scan mode (Eddy/Cartographer/Beacon) - these probes don't send
            # "Adapted mesh bounds" or "probe: at" messages, so we handle everything here
            self._rapid_scan_mode = True
            self.bed_leveling_probed_count = 0
            self.bed_leveling_last_position = None
            self._bed_leveling_complete = False
            # Reset leveling_mode for KAMP during printing
            if self.current_state in ("printing", "paused"):
                self.leveling_mode = None
            logger.info("Rapid scan mode detected - using simplified visualization")
            current_page = await self._get_current_page()
            if current_page != PAGE_PRINTING_KAMP:
                self._loop.create_task(self._navigate_to_page(PAGE_PRINTING_KAMP, clear_history=True))
            self._loop.create_task(
                self.display.update_kamp_text("Scanning bed surface...")
            )
        elif response.startswith("// probe: at"):
            # Skip all probe messages during rapid scan to avoid overwhelming the system
            if self._rapid_scan_mode:
                return
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

        elif (
            response.startswith("// Mesh Bed Leveling Complete")
            or "Collecting samples along the scanning path completed" in response
            or "Mesh calibration complete" in response
            or response.startswith("// Smart Park location")
            or "KAMP purge" in response
            or "LINE_PURGE" in response
        ):
            # If rapid scan mode was active, show completion
            # Draw boxes if we received probe counts (some probes send both rapid scan AND counts)
            if self._rapid_scan_mode:
                self._loop.create_task(
                    self.display.update_kamp_text("Scan complete!")
                )

            self.bed_leveling_probed_count = 0
            self.bed_leveling_counts = self.full_bed_leveling_counts
            self._rapid_scan_mode = False

            current_page = await self._get_current_page()
            if current_page == PAGE_PRINTING_KAMP:
                self._bed_leveling_complete = True
                # Only show bed mesh final for manual full bed leveling (not during printing)
                if self.leveling_mode == "full_bed" and self.current_state not in ("printing", "paused"):
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
