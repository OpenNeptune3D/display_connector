import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

import display as display_module
from src.config import ConfigHandler
from src.mapping import PAGE_PRINTING_COMPLETE, PAGE_PRINTING_KAMP, filename_regex_wrapper
from src.neptune4 import MODEL_N4_PRO

logger = logging.getLogger(__name__)


@pytest_asyncio.fixture
async def controller(tmp_path):
    # A fresh ConfigHandler writes a default clean_filename_regex, and
    # DisplayController.__init__ -> _handle_config() compiles it straight into
    # the module-level filename_regex_wrapper in src/mapping.py. Save/restore
    # it so this doesn't leak into other test modules in the same session.
    original_filename_regex = dict(filename_regex_wrapper)
    try:
        config = ConfigHandler(str(tmp_path / "test_config.ini"), logger)
        if "general" not in config:
            config.add_section("general")
        config.set("general", "printer_model", MODEL_N4_PRO)
        config.write_changes()

        loop = asyncio.get_running_loop()
        controller = display_module.DisplayController(config, loop)
        # No real display attached in tests - avoid touching serial I/O.
        controller.display.write = AsyncMock()
        yield controller
    finally:
        filename_regex_wrapper.clear()
        filename_regex_wrapper.update(original_filename_regex)


@pytest.mark.asyncio
async def test_rapid_scan_marks_bed_leveling_complete(controller):
    # Cartographer/Eddy/Beacon probes announce their scan with this message and
    # never reliably send the "// Mesh Bed Leveling Complete" (or KAMP
    # scanning-path) text this module otherwise waits for to clear the flag.
    await controller.handle_gcode_response("Beginning rapid surface scan")
    await asyncio.sleep(0)  # let the create_task()-scheduled navigation run

    assert controller._rapid_scan_mode is True
    assert controller._bed_leveling_complete is True


@pytest.mark.asyncio
async def test_rapid_scan_does_not_freeze_navigation_away_from_kamp_page(controller):
    # Reproduces https://github.com/OpenNeptune3D/display_connector/issues/62:
    # a rapid-scan probe starts a mesh, the screen parks on printing_kamp, and
    # the print later finishes ("Status Update: complete" in the issue's log)
    # while the display is still trying to navigate off that page.
    await controller.handle_gcode_response("Beginning rapid surface scan")
    await asyncio.sleep(0)
    controller.history = [PAGE_PRINTING_KAMP]

    await controller._navigate_to_page(PAGE_PRINTING_COMPLETE)

    assert controller.history[-1] == PAGE_PRINTING_COMPLETE


@pytest.mark.asyncio
async def test_pre_fix_behavior_would_freeze_navigation(controller):
    # Documents the bug this fix addresses: with the flag left False (the
    # pre-fix behavior when no completion message ever arrives), the guard in
    # _navigate_to_page() blocks leaving printing_kamp indefinitely.
    controller._rapid_scan_mode = True
    controller._bed_leveling_complete = False
    controller.history = [PAGE_PRINTING_KAMP]

    await controller._navigate_to_page(PAGE_PRINTING_COMPLETE)

    assert controller.history[-1] == PAGE_PRINTING_KAMP
