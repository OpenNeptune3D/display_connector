import logging
from unittest.mock import AsyncMock
import pytest
from src.communicator import DisplayCommunicator


@pytest.mark.asyncio
async def test_valid_version():
    communicator = DisplayCommunicator(logging, None, None, None)
    communicator.get_firmware_version = AsyncMock(return_value="1.0")
    communicator.supported_firmware_versions = ["1.0"]
    is_valid = await communicator.check_valid_version()
    communicator.get_firmware_version.assert_awaited_once()
    assert is_valid

@pytest.mark.asyncio
async def test_invalid_version():
    communicator = DisplayCommunicator(logging, None, None, None)
    communicator.get_firmware_version = AsyncMock(return_value="1.0")
    communicator.supported_firmware_versions = ["2.0"]
    is_valid = await communicator.check_valid_version()
    communicator.get_firmware_version.assert_awaited_once()
    assert not is_valid

@pytest.mark.asyncio
async def test_navigate():
    communicator = DisplayCommunicator(logging, None, None, None)
    communicator.write = AsyncMock()
    await communicator.navigate_to("1")
    communicator.write.assert_awaited_once_with("page 1")