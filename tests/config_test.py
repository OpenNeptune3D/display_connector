import pytest
import logging
import os
from configparser import NoSectionError

from src.config import ConfigHandler, LEGACY_CLEAN_FILENAME_REGEX
from src.mapping import DEFAULT_CLEAN_FILENAME_REGEX

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

def test_safe_get(tmp_path):
    with open(str(tmp_path) + "/test_config.ini", "w") as f:
        f.write("[test]\nt = t")
    config = ConfigHandler(str(tmp_path) + "/test_config.ini", logger)

    assert config.safe_get("test", "t") == "t"
    assert config.safe_get("test", "t", "default") == "t"

def test_safe_get_no_section(tmp_path):
    with open(str(tmp_path) + "/test_config.ini", "w") as f:
        f.write("[test2]\nt = t")
    config = ConfigHandler(str(tmp_path) + "/test_config.ini", logger)

    assert config.safe_get("test", "t2") is None
    assert config.safe_get("test", "t2", "default") == "default"

def test_safe_get_no_option(tmp_path):
    with open(str(tmp_path) + "/test_config.ini", "w") as f:
        f.write("[test]\nt = t")
    config = ConfigHandler(str(tmp_path) + "/test_config.ini", logger)

    assert config.safe_get("test", "t2") is None
    assert config.safe_get("test", "t2", "default") == "default"


def test_new_config_uses_default_filename_regex(tmp_path):
    config = ConfigHandler(str(tmp_path) + "/test_config.ini", logger)
    assert config.get("general", "clean_filename_regex") == DEFAULT_CLEAN_FILENAME_REGEX


def test_migrates_legacy_filename_regex(tmp_path):
    path = str(tmp_path) + "/test_config.ini"
    with open(path, "w") as f:
        f.write(
            "[general]\n"
            "clean_filename_regex = " + LEGACY_CLEAN_FILENAME_REGEX + "\n"
            "\n; a user comment\n[files]\nsort_by = modified\n"
        )
    config = ConfigHandler(path, logger)
    assert config.get("general", "clean_filename_regex") == DEFAULT_CLEAN_FILENAME_REGEX
    with open(path, "r") as f:
        content = f.read()
    assert "; a user comment" in content
    assert LEGACY_CLEAN_FILENAME_REGEX not in content


def test_keeps_custom_filename_regex(tmp_path):
    path = str(tmp_path) + "/test_config.ini"
    custom = r"(.*)_custom\.gcode"
    with open(path, "w") as f:
        f.write("[general]\nclean_filename_regex = " + custom + "\n")
    config = ConfigHandler(path, logger)
    assert config.get("general", "clean_filename_regex") == custom
