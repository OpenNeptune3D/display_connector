import logging
from unittest.mock import AsyncMock, call

import pytest
from src.neptune4 import MODEL_N4_MAX, MODEL_N4_PLUS, MODEL_N4_PRO, MODEL_N4_REGULAR, ElegooNeptune4DisplayCommunicator, ElegooNeptune4Mapper, ElegooNeptune4MaxMapper, ElegooNeptune4PlusMapper, ElegooNeptune4ProMapper
from src.mapping import PAGE_PREPARE_TEMP, PAGE_PRINTING_FILAMENT


def test_n4_pro_mapping():
    mapper = ElegooNeptune4ProMapper()
    assert mapper.map_page(PAGE_PREPARE_TEMP) == "pretemp"
    assert mapper.map_page(PAGE_PRINTING_FILAMENT) == "adjusttemp_pro"


def test_get_mapper_4():
    communicator = ElegooNeptune4DisplayCommunicator(None, MODEL_N4_REGULAR, None)
    assert isinstance(communicator.mapper, ElegooNeptune4Mapper)


def test_get_mapper_pro():
    communicator = ElegooNeptune4DisplayCommunicator(None, MODEL_N4_PRO, None)
    assert isinstance(communicator.mapper, ElegooNeptune4ProMapper)


def test_get_mapper_plus():
    communicator = ElegooNeptune4DisplayCommunicator(None, MODEL_N4_PLUS, None)
    assert isinstance(communicator.mapper, ElegooNeptune4PlusMapper)


def test_get_mapper_max():
    communicator = ElegooNeptune4DisplayCommunicator(None, MODEL_N4_MAX, None)
    assert isinstance(communicator.mapper, ElegooNeptune4MaxMapper)


def test_get_mapper_invalid():
    communicator = ElegooNeptune4DisplayCommunicator(logging, "abc", None)
    assert isinstance(communicator.mapper, ElegooNeptune4Mapper)


@pytest.mark.asyncio
async def test_initializing():
    communicator = ElegooNeptune4DisplayCommunicator(logging, MODEL_N4_REGULAR, None)
    communicator.display.command = AsyncMock()
    await communicator.initialize_display()
    assert communicator.mapper is not None
    communicator.display.command.assert_has_calls([
        call("sendxy=1", 5),
        call("main.q4.picc=213", 5)
        ])
    

@pytest.mark.asyncio
async def test_initializing_pro():
    communicator = ElegooNeptune4DisplayCommunicator(logging, MODEL_N4_PRO, None)
    communicator.display.command = AsyncMock()
    await communicator.initialize_display()
    assert communicator.mapper is not None
    communicator.display.command.assert_has_calls([
        call("sendxy=1", 5),
        call('main.disp_q5.val=1', 5),
        call("main.q4.picc=214", 5)
        ])
    

@pytest.mark.asyncio
async def test_initializing_plus():
    communicator = ElegooNeptune4DisplayCommunicator(logging, MODEL_N4_PLUS, None)
    communicator.display.command = AsyncMock()
    await communicator.initialize_display()
    assert communicator.mapper is not None
    communicator.display.command.assert_has_calls([
        call("sendxy=1", 5),
        call("main.q4.picc=313", 5)
        ])
    

@pytest.mark.asyncio
async def test_initializing_max():
    communicator = ElegooNeptune4DisplayCommunicator(logging, MODEL_N4_MAX, None)
    communicator.display.command = AsyncMock()
    await communicator.initialize_display()
    assert communicator.mapper is not None
    communicator.display.command.assert_has_calls([
        call("sendxy=1", 5),
        call("main.q4.picc=314", 5)
        ])