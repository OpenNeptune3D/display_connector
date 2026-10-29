import logging
from unittest.mock import AsyncMock, patch
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
    communicator.write.assert_awaited_once_with(
        "page 1",
        blocked_key="__nav__",
        auto_unblock=False,
    )


@pytest.mark.asyncio
async def test_update_data_keeps_latest_status(communicator):
    # Partial Moonraker updates must be merged, so required_fields formatters see current values
    communicator.data_mapping = {}
    await communicator.update_data({"print_stats": {"info": {"total_layer": 125, "current_layer": 0}}})
    await communicator.update_data({"print_stats": {"info": {"current_layer": 13}}})
    assert communicator.current_data == {"print_stats": {"info": {"total_layer": 125, "current_layer": 13}}}


def test_encoding_is_passed_to_client_constructor():
    # nextion 3.x reads the encoding only at construction; setting .encoding afterwards is a no-op
    with patch("src.communicator.TJCClient") as client:
        DisplayCommunicator(logging, "N4", "/dev/not-opened", None)
    client.assert_called_once_with("/dev/not-opened", 115200, None, encoding="utf-8")
