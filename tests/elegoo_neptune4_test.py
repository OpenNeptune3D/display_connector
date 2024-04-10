import logging
from unittest.mock import AsyncMock, call

import pytest
from src.elegoo_neptune4 import MODEL_N4_MAX, MODEL_N4_PLUS, MODEL_N4_PRO, MODEL_N4_REGULAR, Neptune4DisplayCommunicator, Neptune4Mapper, Neptune4MaxMapper, Neptune4PlusMapper, Neptune4ProMapper
from src.mapping import PAGE_PREPARE_TEMP, PAGE_PRINTING_FILAMENT

def test_default_light_config():
    mapper = Neptune4Mapper()
    lights = mapper.configure_default_lights()
    assert len(lights) == 2
    assert lights[0]["name"] == "Part_Light"
    assert lights[1]["name"] == "Frame_Light"


def test_default_filament_sensor_name():
    mapper = Neptune4Mapper()
    assert mapper.data_mapping["filament_switch_sensor filament_sensor"] is not None


def test_n4_pro_mapping():
    mapper = Neptune4ProMapper()
    assert mapper.map_page(PAGE_PREPARE_TEMP) == "6"
    assert mapper.map_page(PAGE_PRINTING_FILAMENT) == "27"


def test_get_mapper_4():
    communicator = Neptune4DisplayCommunicator(None, MODEL_N4_REGULAR, None)
    assert isinstance(communicator.mapper, Neptune4Mapper)


def test_get_mapper_pro():
    communicator = Neptune4DisplayCommunicator(None, MODEL_N4_PRO, None)
    assert isinstance(communicator.mapper, Neptune4ProMapper)


def test_get_mapper_plus():
    communicator = Neptune4DisplayCommunicator(None, MODEL_N4_PLUS, None)
    assert isinstance(communicator.mapper, Neptune4PlusMapper)


def test_get_mapper_max():
    communicator = Neptune4DisplayCommunicator(None, MODEL_N4_MAX, None)
    assert isinstance(communicator.mapper, Neptune4MaxMapper)


def test_get_mapper_invalid():
    communicator = Neptune4DisplayCommunicator(logging, "abc", None)
    assert isinstance(communicator.mapper, Neptune4Mapper)


@pytest.mark.asyncio
async def test_initializing():
    communicator = Neptune4DisplayCommunicator(logging, MODEL_N4_REGULAR, None)
    communicator.display.command = AsyncMock()
    await communicator.initialize_display()
    assert communicator.mapper is not None
    communicator.display.command.assert_has_calls([
        call("sendxy=1", 5),
        call("p[1].q4.picc=213", 5)
        ])
    

@pytest.mark.asyncio
async def test_initializing_pro():
    communicator = Neptune4DisplayCommunicator(logging, MODEL_N4_PRO, None)
    communicator.display.command = AsyncMock()
    await communicator.initialize_display()
    assert communicator.mapper is not None
    communicator.display.command.assert_has_calls([
        call("sendxy=1", 5),
        call('p[1].disp_q5.val=1', 5),
        call("p[1].q4.picc=214", 5)
        ])
    

@pytest.mark.asyncio
async def test_initializing_plus():
    communicator = Neptune4DisplayCommunicator(logging, MODEL_N4_PLUS, None)
    communicator.display.command = AsyncMock()
    await communicator.initialize_display()
    assert communicator.mapper is not None
    communicator.display.command.assert_has_calls([
        call("sendxy=1", 5),
        call("p[1].q4.picc=313", 5)
        ])
    

@pytest.mark.asyncio
async def test_initializing_max():
    communicator = Neptune4DisplayCommunicator(logging, MODEL_N4_MAX, None)
    communicator.display.command = AsyncMock()
    await communicator.initialize_display()
    assert communicator.mapper is not None
    communicator.display.command.assert_has_calls([
        call("sendxy=1", 5),
        call("p[1].q4.picc=314", 5)
        ])