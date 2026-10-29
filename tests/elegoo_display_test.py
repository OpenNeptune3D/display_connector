from types import SimpleNamespace
from unittest.mock import Mock

from src.elegoo_display import ElegooDisplayCommunicator, ElegooDisplayMapper
from src.tjc import TJCClient


def test_initializing():
    mapper = ElegooDisplayMapper()
    assert mapper.page_mapping is not None
    assert mapper.data_mapping is not None


def test_shutdown_write_supports_both_nextion_apis():
    write = ElegooDisplayCommunicator._write_without_response
    v2 = Mock(spec=["write_command"])  # nextion 2.x
    write(SimpleNamespace(display=v2), "cls BLACK")
    v2.write_command.assert_called_once_with("cls BLACK")
    v3 = Mock(spec=["_write_command_raw"])  # nextion 3.x
    write(SimpleNamespace(display=v3), "cls BLACK")
    v3._write_command_raw.assert_called_once_with(b"cls BLACK")


def test_installed_nextion_has_a_raw_write():
    assert hasattr(TJCClient, "_write_command_raw") or hasattr(TJCClient, "write_command")
