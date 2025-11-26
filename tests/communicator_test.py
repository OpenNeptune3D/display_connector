import logging
from unittest.mock import AsyncMock
import pytest

from src.communicator import DisplayCommunicator


@pytest.fixture
def communicator():
    # event_handler can be None for these unit tests, since we patch out I/O
    return DisplayCommunicator(logging, "N3", "/dev/ttyS0", None)


def test_get_device_name(communicator):
    # Simple sanity check: constructor stores the model name
    assert communicator.get_device_name() == "N3"


def test_get_display_type_name(communicator):
    # Should just be the class name
    assert communicator.get_display_type_name() == "DisplayCommunicator"


@pytest.mark.asyncio
async def test_navigate(communicator):
    # We don't want real I/O here, so patch write
    communicator.write = AsyncMock()

    await communicator.navigate_to("1")

    # navigate_to blocks other writes with a blocked_key="__nav__"
    communicator.write.assert_awaited_once_with("page 1", blocked_key="__nav__")
