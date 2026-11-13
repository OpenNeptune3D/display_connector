import asyncio
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import wifi
from src.controller.display_events import DisplayEventsMixin
from src.controller.wifi_settings import WifiSettingsMixin
from src.mapping import (
    PAGE_OVERLAY_LOADING,
    PAGE_SETTINGS_WIFI,
    PAGE_SETTINGS_WIFI_PASSWORD,
)


def _completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout.encode(), stderr.encode())


def test_split_terse_handles_escaped_colons():
    assert wifi._split_terse(r"*:My\:Net\\x:67:WPA2") == ["*", "My:Net\\x", "67", "WPA2"]


def test_scan_networks_dedupes_and_sorts():
    output = "\n".join([
        " :Neighbour:40:WPA2",
        " :Neighbour:80:WPA2",   # same SSID on another access point, stronger
        " ::90:WPA2",            # hidden network
        "*:Home:55:WPA2",
        " :Cafe:70:",            # open
        " :Guest:20:--",         # open
    ])
    with patch.object(wifi.subprocess, "run", return_value=_completed(output)) as run:
        networks = wifi.scan_networks(rescan=True)
    assert "yes" in run.call_args.args[0]
    assert [n["ssid"] for n in networks] == ["Home", "Neighbour", "Cafe", "Guest"]
    assert networks[0]["in_use"] is True
    assert networks[1]["signal"] == 80
    assert [n["secured"] for n in networks] == [True, True, False, False]


def test_scan_networks_failure_returns_empty():
    with patch.object(wifi.subprocess, "run", return_value=_completed(returncode=1, stderr="Not authorized")):
        assert wifi.scan_networks() == []


def test_connect_failure_deletes_new_profile():
    calls = []

    def run(args, **kwargs):
        calls.append(args[1:])
        if args[1:3] == ["dev", "wifi"]:
            return _completed(returncode=4, stderr="Secrets were required, but not provided")
        if args[1:4] == ["-t", "-f", "NAME,TYPE"]:
            # before the attempt there is no profile, afterwards nmcli left one behind
            existing = "Home:802-11-wireless" if any(c[:2] == ["dev", "wifi"] for c in calls) else ""
            return _completed(existing)
        return _completed()

    with patch.object(wifi.subprocess, "run", side_effect=run):
        ok, message = wifi.connect_wifi("Home", "wrong")
    assert not ok
    assert "Secrets" in message
    assert ["dev", "wifi", "connect", "Home", "password", "wrong", "ifname", "wlan0"] in calls
    assert ["connection", "delete", "id", "Home"] in calls


def test_connect_failure_keeps_existing_profile():
    calls = []

    def run(args, **kwargs):
        calls.append(args[1:])
        if args[1:3] == ["dev", "wifi"]:
            return _completed(returncode=4, stderr="timeout")
        if args[1:4] == ["-t", "-f", "NAME,TYPE"]:
            return _completed("Home:802-11-wireless")
        return _completed()

    with patch.object(wifi.subprocess, "run", side_effect=run):
        wifi.connect_wifi("Home")
    assert ["connection", "delete", "id", "Home"] not in calls


def test_clean_wifi_password_maps_curly_quotes():
    assert wifi.clean_wifi_password("a“b”c") == 'a"b"c'


def test_clean_wifi_password_keeps_printable_ascii():
    every_symbol = " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
    assert wifi.clean_wifi_password("Abc123" + every_symbol) == "Abc123" + every_symbol


@pytest.mark.parametrize("password", ["pass€word", "pass、word", "pass…", "cafépass"])
def test_clean_wifi_password_rejects_non_ascii(password):
    assert wifi.clean_wifi_password(password) is None


def test_wifi_permitted_needs_all_permissions():
    granted = "\n".join([
        "org.freedesktop.NetworkManager.network-control:yes",
        "org.freedesktop.NetworkManager.settings.modify.system:yes",
        "org.freedesktop.NetworkManager.wifi.scan:yes",
    ])
    with patch.object(wifi.subprocess, "run", return_value=_completed(granted)):
        assert wifi.wifi_permitted() is True
    with patch.object(wifi.subprocess, "run", return_value=_completed(granted.replace("scan:yes", "scan:auth"))):
        assert wifi.wifi_permitted() is False


class FakeController(WifiSettingsMixin):
    def __init__(self, page=PAGE_SETTINGS_WIFI):
        self._loop = asyncio.get_running_loop()
        self._history_lock = asyncio.Lock()
        self.history = [page]
        self.display = MagicMock()
        self.display.draw_wifi_list = AsyncMock()
        self.display.draw_wifi_password = AsyncMock()
        self._init_wifi_settings()

    async def _navigate_to_page(self, page):
        self.history.append(page)

    async def _go_back(self):
        self.history.pop()


NETWORKS = [
    {"ssid": "Home", "signal": 70, "secured": True, "in_use": True},
    {"ssid": "Office", "signal": 60, "secured": True, "in_use": False},
    {"ssid": "Cafe", "signal": 50, "secured": False, "in_use": False},
]


@pytest.mark.asyncio
async def test_secured_unknown_network_asks_for_password_then_connects():
    controller = FakeController()
    controller.wifi_networks = list(NETWORKS)
    with patch("src.controller.wifi_settings.saved_wifi_connections", return_value={"Home"}), \
         patch("src.controller.wifi_settings.connect_wifi", return_value=(True, "")) as connect, \
         patch("src.controller.wifi_settings.scan_networks", return_value=NETWORKS), \
         patch("src.controller.wifi_settings.wifi_radio_enabled", return_value=True), \
         patch("src.controller.wifi_settings.get_wlan0_ip", return_value="10.0.0.2"):
        controller.handle_wifi_action("wifi_select_1")
        await controller._wifi_task
        assert controller.history[-1] == PAGE_SETTINGS_WIFI_PASSWORD
        controller.display.draw_wifi_password.assert_awaited_once_with("Office")

        controller.handle_wifi_password("secret123")
        await controller._wifi_task
    connect.assert_called_once_with("Office", "secret123")
    assert controller.history == [PAGE_SETTINGS_WIFI]
    assert controller.wifi_status == "Connected"


@pytest.mark.parametrize("component", [1, 2, 3, 8])
def test_keyboard_text_is_the_password_whatever_its_second_byte(component):
    controller = MagicMock()
    DisplayEventsMixin.handle_text_input(controller, 132, component, "secret123")
    controller.handle_wifi_password.assert_called_once_with("secret123")


def test_text_from_other_pages_is_ignored():
    controller = MagicMock()
    DisplayEventsMixin.handle_text_input(controller, 77, 1, "secret123")
    controller.handle_wifi_password.assert_not_called()


@pytest.mark.asyncio
async def test_curly_quotes_from_keyboard_connect_as_straight_quotes():
    controller = FakeController(page=PAGE_SETTINGS_WIFI_PASSWORD)
    controller.history = [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_PASSWORD]
    controller.wifi_selected_ssid = "Office"
    with patch("src.controller.wifi_settings.connect_wifi", return_value=(True, "")) as connect, \
         patch("src.controller.wifi_settings.scan_networks", return_value=NETWORKS), \
         patch("src.controller.wifi_settings.wifi_radio_enabled", return_value=True), \
         patch("src.controller.wifi_settings.get_wlan0_ip", return_value=None):
        controller.handle_wifi_password("say“hi”")
        await controller._wifi_task
    connect.assert_called_once_with("Office", 'say"hi"')


@pytest.mark.asyncio
async def test_impossible_password_is_not_sent_to_nmcli():
    controller = FakeController(page=PAGE_SETTINGS_WIFI_PASSWORD)
    controller.history = [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_PASSWORD]
    controller.wifi_selected_ssid = "Office"
    with patch("src.controller.wifi_settings.connect_wifi") as connect:
        controller.handle_wifi_password("pass€word")
        await asyncio.sleep(0)
    connect.assert_not_called()
    assert controller.wifi_status == "Invalid char"
    assert controller.history == [PAGE_SETTINGS_WIFI]


@pytest.mark.asyncio
async def test_open_network_connects_without_keyboard():
    controller = FakeController()
    controller.wifi_networks = list(NETWORKS)
    with patch("src.controller.wifi_settings.saved_wifi_connections", return_value=set()), \
         patch("src.controller.wifi_settings.connect_wifi", return_value=(False, "Secrets were required")) as connect, \
         patch("src.controller.wifi_settings.scan_networks", return_value=NETWORKS), \
         patch("src.controller.wifi_settings.wifi_radio_enabled", return_value=True), \
         patch("src.controller.wifi_settings.get_wlan0_ip", return_value=None):
        controller.handle_wifi_action("wifi_select_2")
        await controller._wifi_task
    connect.assert_called_once_with("Cafe", None)
    assert PAGE_OVERLAY_LOADING not in controller.history
    assert controller.wifi_status == "Wrong password"


@pytest.mark.asyncio
async def test_paging_stays_in_range():
    controller = FakeController()
    controller.wifi_networks = [dict(NETWORKS[1], ssid=f"Net{i}") for i in range(10)]
    with patch("src.controller.wifi_settings.wifi_radio_enabled", return_value=True), \
         patch("src.controller.wifi_settings.get_wlan0_ip", return_value=None):
        controller.handle_wifi_action("wifi_page_prev")
        assert controller.wifi_page == 0
        controller.handle_wifi_action("wifi_page_next")
        controller.handle_wifi_action("wifi_page_next")
        assert controller.wifi_page == 1
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_list_is_not_drawn_on_another_page():
    controller = FakeController(page=PAGE_OVERLAY_LOADING)
    await controller._draw_wifi_list()
    controller.display.draw_wifi_list.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("permitted, status", [(False, "Need reboot"), (True, "Scan failed")])
async def test_failed_scan_says_why(permitted, status):
    controller = FakeController()
    with patch("src.controller.wifi_settings.scan_networks", return_value=[]) as scan, \
         patch("src.controller.wifi_settings.wifi_permitted", return_value=permitted), \
         patch("src.controller.wifi_settings.wifi_radio_enabled", return_value=True), \
         patch("src.controller.wifi_settings.get_wlan0_ip", return_value=None):
        await controller._wifi_scan()
    assert controller.wifi_status == status
    # without permission nmcli would silently skip the rescan, so don't ask for one
    assert [c.args for c in scan.call_args_list] == ([(False,), (True,)] if permitted else [(False,)])
