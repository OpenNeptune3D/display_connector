"""Entry point for the display service (run by display.service).

The controller itself lives in src/controller/; this file sets up logging, signal
handling and file watchers, then runs the asyncio loop.
"""

import os
import asyncio
import traceback
import signal
import systemd.daemon

from src.config import ConfigHandler
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

from src.controller import DisplayController
from src.controller.common import logger, setup_logging

# Global flag for graceful shutdown
_shutdown_requested = False

# Placeholder for event loop
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


setup_logging()

comms_directory = os.path.expanduser("~/printer_data/comms")
config_file = os.path.expanduser("~/printer_data/config/display_connector.cfg")

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
    
    # Best-effort controller shutdown before closing the loop.
    if "controller" in locals() and not loop.is_closed():
        try:
            loop.run_until_complete(controller.close())
        except Exception as e:
            logger.error(f"Error during controller close(): {e}")

    # Ensure all tasks are cancelled and given time to handle CancelledError.
    try:
        pending = {t for t in asyncio.all_tasks(loop=loop) if not t.done()}
    except Exception:
        pending = set()

    for task in list(pending):
        task.cancel()

    if pending and not loop.is_closed():
        try:
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
            loop.run_until_complete(loop.shutdown_asyncgens())
        except RuntimeError:
            # Loop may already be closed or not runnable here; best-effort shutdown.
            pass

    loop.close()
    logger.info("Service stopped")
