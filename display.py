"""Entry point for the display service (run by display.service).

The controller itself lives in src/controller/; this file sets up logging, signal
handling and file watchers, then runs the asyncio loop.
"""

import os
import asyncio
import traceback
import signal

from src import sd_notify
from src.config import ConfigHandler
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from src.controller import DisplayController
from src.controller.common import logger, setup_logging


class FileNameEventHandler(FileSystemEventHandler):
    """Pass on events for files with one of the given names, in any watchdog version.

    Recent watchdog releases (7.1 here) match PatternMatchingEventHandler patterns
    against the whole path (PurePath.full_match), so a bare name like "klippy.sock"
    never matches and the handler silently gets nothing. Compare file names instead.
    """

    def __init__(self, names):
        super().__init__()
        self._names = frozenset(names)

    def dispatch(self, event):
        if event.is_directory:
            return
        paths = (event.src_path, getattr(event, "dest_path", "") or "")
        if any(os.path.basename(os.fsdecode(path)) in self._names for path in paths if path):
            super().dispatch(event)


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
                # Runs on the watchdog thread; asyncio.Event isn't thread-safe
                loop.call_soon_threadsafe(controller.klipper_restart_event.set)
        except Exception as e:
            logger.error(f"Error handling socket change: {e}")
            logger.error(traceback.format_exc())

    # watch the config file
    config_event_handler = FileNameEventHandler(["display_connector.cfg"])
    config_event_handler.on_modified = handle_wd_callback
    config_event_handler.on_created = handle_wd_callback
    config_observer.schedule(
        config_event_handler, config.file, recursive=False
    )

    # watch the socket directory
    socket_event_handler = FileNameEventHandler(["klippy.sock", "moonraker.sock"])
    socket_event_handler.on_modified = handle_sock_changes
    socket_event_handler.on_created = handle_sock_changes
    socket_event_handler.on_deleted = handle_sock_changes
    config_observer.schedule(
        socket_event_handler, comms_directory, recursive=False
    )

    # start watching files
    config_observer.start()

    # Notify systemd we're ready
    if sd_notify.notify('READY=1'):
        logger.info("Service ready, notified systemd")

    # Watchdog ping task
    async def watchdog_ping():
        while not _shutdown_requested:
            sd_notify.notify('WATCHDOG=1')
            await asyncio.sleep(30)  # Ping every 30 seconds (WatchdogSec=60)

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
    sd_notify.notify('STOPPING=1')
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
