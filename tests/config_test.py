import pytest
import logging
import os
from configparser import NoSectionError

from src.config import ConfigHandler

logger = logging.getLogger(__name__)


def test_initializing(tmp_path):
    config = ConfigHandler(str(tmp_path) + "/test_config.ini", logger)
    assert config.file == str(tmp_path) + "/test_config.ini"
    assert os.path.exists(str(tmp_path) + "/test_config.ini")


def test_reload_config(tmp_path):
    config = ConfigHandler(str(tmp_path) + "/test_config.ini", logger)
    with pytest.raises(NoSectionError):
        config.get("test", "test")
    with open(str(tmp_path) + "/test_config.ini", "w") as f:
        f.write("[test]\ntest = test2")
    config.reload_config()
    assert config.get("test", "test") == "test2"


def test_write_changes(tmp_path):
    config = ConfigHandler(str(tmp_path) + "/test_config.ini", logger)
    with open(str(tmp_path) + "/test_config.ini", "r") as f:
        assert "[test]\ntest = test" not in f.read()
    config.add_section("test")
    config.set("test", "test", "test")
    config.write_changes()
    with open(str(tmp_path) + "/test_config.ini", "r") as f:
        assert "[test]\ntest = test" in f.read()


def test_does_not_overwrite_existing_config(tmp_path):
    with open(str(tmp_path) + "/test_config.ini", "w") as f:
        f.write("[test]\ntest = test")
    ConfigHandler(str(tmp_path) + "/test_config.ini", logger)
    with open(str(tmp_path) + "/test_config.ini", "r") as f:
        assert "[test]\ntest = test" in f.read()

def test_reading_none_light_config(tmp_path):
    with open(str(tmp_path) + "/test_config.ini", "w") as f:
        f.write("[test]\nt = t")
    config = ConfigHandler(str(tmp_path) + "/test_config.ini", logger)

    lights = config.get_lights()
    assert lights is None

def test_reading_one_light_config(tmp_path):
    with open(str(tmp_path) + "/test_config.ini", "w") as f:
        f.write("[light Frame_Light]\ntype = output_pin")
    config = ConfigHandler(str(tmp_path) + "/test_config.ini", logger)

    lights = config.get_lights()
    assert len(lights) == 1
    assert lights[0]["name"] == "Frame_Light"

def test_reading_multiple_lights_config(tmp_path):
    with open(str(tmp_path) + "/test_config.ini", "w") as f:
        f.write("[light Part_Light]\ntype = output_pin\n")
        f.write("[light Frame_Light]\ntype = led\n")
        f.write("[light Warning_Light]\ntype = output_pin\n")
    config = ConfigHandler(str(tmp_path) + "/test_config.ini", logger)

    lights = config.get_lights()
    assert len(lights) == 3
    assert lights[0]["name"] == "Part_Light"
    assert lights[0]["type"] == "output_pin"
    assert lights[1]["name"] == "Frame_Light"
    assert lights[1]["type"] == "led"