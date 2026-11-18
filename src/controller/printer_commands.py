"""G-code helpers and printer setting changes triggered from the display for DisplayController."""

import asyncio

from src.mapping import (
    PAGE_PRINTING_PAUSE,
)
from src.controller.common import (
    logger,
)


class PrinterCommandsMixin:
    """G-code helpers and printer setting changes triggered from the display."""

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
