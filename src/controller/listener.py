"""Main listen loop and reconnection to Klipper/Moonraker for DisplayController."""

import asyncio
import traceback

from src.controller.common import (
    logger,
)


class ListenerMixin:
    """Main listen loop and reconnection to Klipper/Moonraker."""

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

            # Start cleanup task for stale requests (runs for the lifetime of this connection)
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = self._loop.create_task(self._cleanup_stale_requests())

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
                
                # Keep the listen task alive while the Moonraker stream reader runs.
                logger.info("Listen task now monitoring connection...")
                if self._process_stream_task:
                    await asyncio.shield(self._process_stream_task)
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

    async def _attempt_reconnect(self):
        async with self._reconnect_lock:
            if self._is_reconnecting:
                return
            self._is_reconnecting = True
            try:
                # Cancel existing listen task first
                if self._listen_task and not self._listen_task.done():
                    self._listen_task.cancel()
                    try:
                        await self._listen_task
                    except asyncio.CancelledError:
                        pass
                
                # Close existing connection
                await self.close()
                
                logger.info("Attempting to reconnect to Moonraker...")
                await asyncio.sleep(1)
                
                self._is_listening = False
                self.resources.allow_new_pool()
                self.start_listening()
            finally:
                self._is_reconnecting = False
