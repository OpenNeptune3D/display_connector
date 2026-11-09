"""Logger, page groups and helpers shared by the DisplayController modules."""

import logging
import os
import sys

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
    PAGE_PREPARE_MOVE,
    PAGE_PREPARE_TEMP,
    PAGE_PREPARE_EXTRUDER,
    PAGE_PRINTING,
    PAGE_PRINTING_KAMP,
    PAGE_PRINTING_PAUSE,
    PAGE_PRINTING_STOP,
    PAGE_PRINTING_EMERGENCY_STOP,
    PAGE_PRINTING_FILAMENT,
    PAGE_PRINTING_SPEED,
    PAGE_PRINTING_ADJUST,
    PAGE_OVERLAY_LOADING,
)


log_file = os.path.expanduser("~/printer_data/logs/display_connector.log")
logger = logging.getLogger("display_connector")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
ch_log = logging.StreamHandler(sys.stdout)
# delay=True: the file is opened on the first record, so importing this module has no side effects.
file_log = logging.FileHandler(log_file, delay=True)


def setup_logging():
    """Attach the console and file handlers; called once by display.py at startup."""
    ch_log.setLevel(logging.DEBUG)
    ch_log.setFormatter(formatter)
    logger.addHandler(ch_log)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    file_log.setLevel(logging.ERROR)
    file_log.setFormatter(formatter)
    logger.addHandler(file_log)
    logger.setLevel(logging.DEBUG)


PRINTING_PAGES = [
    PAGE_PRINTING,
    PAGE_PRINTING_KAMP,
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


def _deep_merge_dicts(target: dict, source: dict) -> None:
    """Merge source into target in-place, recursing into nested dicts.

    Used to coalesce consecutive Moonraker delta updates so that no field
    change is lost when a new status notification arrives before the previous
    update_data task has finished processing.
    """
    for key, value in source.items():
        if key in target and isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge_dicts(target[key], value)
        else:
            target[key] = value
