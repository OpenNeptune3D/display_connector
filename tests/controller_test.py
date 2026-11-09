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


def test_find_best_thumbnail_without_thumbnails():
    for metadata in ({}, {"thumbnails": None}, None):
        assert DisplayController.find_best_thumbnail(None, metadata) is None
    thumbs = [{"width": 32}, {"width": 300}]
    assert DisplayController.find_best_thumbnail(None, {"thumbnails": thumbs}) == {"width": 300}


def test_import_does_not_attach_handlers():
    assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)


def test_openneptune_main_page_temp_and_light_tiles():
    from src.neptune4 import (
        ElegooNeptune4DisplayCommunicator,
        OpenNeptune4DisplayCommunicator,
    )
    from src.mapping import PAGE_PREPARE_TEMP, PAGE_LIGHTS

    class Fake:
        handle_response = DisplayController.handle_response

        def __init__(self, display):
            self.display = display
            self.actions = []

        def execute_action(self, action):
            self.actions.append(action)

    slate = Fake(OpenNeptune4DisplayCommunicator)
    slate.handle_response(1, 5)
    slate.handle_response(1, 6)
    slate.handle_response(1, 1)
    assert slate.actions == ["page " + PAGE_PREPARE_TEMP, "page " + PAGE_LIGHTS, "files_picker"]

    # the stock Elegoo firmware keeps the old mapping
    stock = Fake(ElegooNeptune4DisplayCommunicator)
    stock.handle_response(1, 1)
    assert stock.actions == ["files_picker"]
    assert ElegooNeptune4DisplayCommunicator.extra_response_actions == {}
