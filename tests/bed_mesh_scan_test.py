import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

import display as display_module
from src.config import ConfigHandler
from src.mapping import (
    PAGE_MAIN,
    PAGE_PRINTING,
    PAGE_PRINTING_KAMP,
    filename_regex_wrapper,
)
from src.neptune4 import MODEL_N4_PRO

logger = logging.getLogger(__name__)


@pytest_asyncio.fixture
async def controller(tmp_path):
    original_filename_regex = dict(filename_regex_wrapper)
    try:
        config = ConfigHandler(str(tmp_path / "test_config.ini"), logger)
        if "general" not in config:
            config.add_section("general")
        config.set("general", "printer_model", MODEL_N4_PRO)
        config.write_changes()

        loop = asyncio.get_running_loop()
        controller = display_module.DisplayController(config, loop)
        controller.display.navigate_to = AsyncMock()
        controller.display.update_kamp_text = AsyncMock()
        controller.display.show_bed_mesh_final = AsyncMock()
        controller.load_thumbnail_for_page = AsyncMock()
        yield controller
    finally:
        filename_regex_wrapper.clear()
        filename_regex_wrapper.update(original_filename_regex)


@pytest.mark.asyncio
async def test_touch_home_activates_rapid_scan_mode(controller):
    controller.history = [PAGE_PRINTING]
    await controller.handle_gcode_response("Touch home at (239.750, 194.550) adjusted z by -0.067 mm")
    await asyncio.sleep(0.01)

    assert controller._rapid_scan_mode is True
    assert controller._bed_leveling_complete is False
    assert controller.history[-1] == PAGE_PRINTING_KAMP


@pytest.mark.asyncio
async def test_bed_mesh_moonraker_update_completes_leveling(controller):
    controller.history = [PAGE_PRINTING_KAMP]
    controller._rapid_scan_mode = True
    controller._bed_leveling_complete = False
    controller.current_state = "printing"

    # Simulate Moonraker sending notify_status_update with bed_mesh
    await controller.handle_status_update({"bed_mesh": {"profile_name": "adaptive-mesh"}})
    await asyncio.sleep(0.05)

    assert controller._rapid_scan_mode is False
    assert controller.history[-1] == PAGE_PRINTING


@pytest.mark.asyncio
async def test_smart_park_and_kamp_purge_complete_leveling(controller):
    controller.history = [PAGE_PRINTING_KAMP]
    controller._rapid_scan_mode = True
    controller._bed_leveling_complete = False
    controller.current_state = "printing"

    await controller.handle_gcode_response("// Smart Park location: 98.774,170.377.")
    await asyncio.sleep(0.05)

    assert controller._rapid_scan_mode is False
    assert controller.history[-1] == PAGE_PRINTING


@pytest.mark.asyncio
async def test_progress_watchdog_restores_printing_page(controller):
    controller.history = [PAGE_PRINTING_KAMP]
    controller._rapid_scan_mode = True
    controller._bed_leveling_complete = False
    controller.current_state = "printing"

    # Simulate progress advancing while screen was somehow stuck on KAMP
    await controller.handle_status_update({"display_status": {"progress": 0.12}})
    await asyncio.sleep(0.05)

    assert controller._rapid_scan_mode is False
    assert controller.history[-1] == PAGE_PRINTING


@pytest.mark.asyncio
async def test_legacy_cartographer_scan_complete_message(controller):
    controller.history = [PAGE_PRINTING_KAMP]
    controller._rapid_scan_mode = True
    controller._bed_leveling_complete = False
    controller.current_state = "printing"

    await controller.handle_gcode_response("Mesh calibration complete")
    await asyncio.sleep(0.05)

    assert controller._rapid_scan_mode is False
    assert controller.history[-1] == PAGE_PRINTING
