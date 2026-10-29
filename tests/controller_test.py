import logging

from src.controller import DisplayController
from src.controller.common import logger


def test_mixins_assembled():
    for name in (
        "execute_action",
        "handle_status_update",
        "connect_moonraker",
        "load_thumbnail_for_page",
        "handle_gcode_response",
        "display_event_handler",
        "_go_back",
    ):
        assert callable(getattr(DisplayController, name))


def test_import_does_not_attach_handlers():
    assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)
