import asyncio
import re
import subprocess
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src import wifi
from src.colors import TEXT_HIGHLIGHT, TEXT_NORMAL, TEXT_SUCCESS
from src.communicator import DisplayCommunicator
from src.controller.display_events import DisplayEventsMixin
from src.controller.wifi_settings import WifiSettingsMixin
from src.elegoo_display import ElegooDisplayMapper
from src.elegoo_display import wifi_screens
from src.elegoo_display.wifi_screens import ElegooWifiScreensMixin
from src.mapping import (
    PAGE_OVERLAY_LOADING,
    PAGE_SETTINGS_WIFI,
    PAGE_SETTINGS_WIFI_CONFIRM,
    PAGE_SETTINGS_WIFI_ERROR,
    PAGE_SETTINGS_WIFI_MENU,
    PAGE_SETTINGS_WIFI_MESSAGE,
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


def fake_nmcli(active="Home", profiles="Home:802-11-wireless:yes", connect_error=None,
               profile_after_attempt=None, up_ok=True):
    """subprocess.run standing in for nmcli; returns (run, calls)."""
    calls = []

    def run(args, **kwargs):
        args = args[1:]
        calls.append(args)
        if args[:3] == ["dev", "wifi", "connect"]:
            if connect_error:
                return _completed(returncode=4, stderr=connect_error)
            return _completed("Device 'wlan0' successfully activated")
        if args[:3] == ["-t", "-f", "GENERAL.CONNECTION"]:
            return _completed(f"GENERAL.CONNECTION:{active or ''}")
        if args[:3] == ["-t", "-f", "NAME,TYPE,AUTOCONNECT"]:
            attempted = any(c[:3] == ["dev", "wifi", "connect"] for c in calls)
            if attempted and profile_after_attempt:
                return _completed(f"{profiles}\n{profile_after_attempt}")
            return _completed(profiles)
        if args[:2] == ["connection", "up"]:
            return _completed() if up_ok else _completed(returncode=4, stderr="no network")
        return _completed()

    return run, calls


def test_connect_failure_deletes_new_profile_and_goes_back_to_the_previous_network():
    run, calls = fake_nmcli(
        connect_error="Secrets were required, but not provided",
        profile_after_attempt="Office:802-11-wireless:yes",  # nmcli left one behind
    )
    with patch.object(wifi.subprocess, "run", side_effect=run):
        ok, message, fallback = wifi.connect_wifi("Office", "wrong")
    assert not ok
    assert "Secrets" in message
    assert ["dev", "wifi", "connect", "Office", "password", "wrong", "ifname", "wlan0"] in calls
    assert ["connection", "delete", "id", "Office"] in calls
    assert ["connection", "up", "id", "Home"] in calls
    assert fallback == "Home"


def test_connect_failure_keeps_existing_profile():
    run, calls = fake_nmcli(active=None, profiles="Home:802-11-wireless:yes", connect_error="timeout")
    with patch.object(wifi.subprocess, "run", side_effect=run):
        ok, _, fallback = wifi.connect_wifi("Home")
    assert not ok and fallback is None
    assert ["connection", "delete", "id", "Home"] not in calls
    assert not any(c[:2] == ["connection", "up"] for c in calls)  # nothing to go back to


def test_connect_failure_reports_no_fallback_when_the_previous_network_is_gone():
    run, _ = fake_nmcli(connect_error="timeout", up_ok=False)
    with patch.object(wifi.subprocess, "run", side_effect=run):
        assert wifi.connect_wifi("Office", "secret123")[2] is None


def test_connect_success_has_no_fallback():
    run, calls = fake_nmcli()
    with patch.object(wifi.subprocess, "run", side_effect=run):
        assert wifi.connect_wifi("Office", "secret123") == (True, "Device 'wlan0' successfully activated", None)
    assert not any(c[:2] == ["connection", "up"] for c in calls)


def test_saved_profiles_with_autoconnect():
    output = "Home:802-11-wireless:yes\nWired:802-3-ethernet:yes\nCafe\\:2:802-11-wireless:no"
    with patch.object(wifi.subprocess, "run", return_value=_completed(output)):
        assert wifi.saved_wifi_profiles() == {"Home": True, "Cafe:2": False}
        assert wifi.saved_wifi_connections() == {"Home", "Cafe:2"}


@pytest.mark.parametrize("enabled, value", [(True, "yes"), (False, "no")])
def test_set_autoconnect(enabled, value):
    run, calls = fake_nmcli()
    with patch.object(wifi.subprocess, "run", side_effect=run):
        assert wifi.set_wifi_autoconnect("Home", enabled) is True
    assert calls == [["connection", "modify", "id", "Home", "connection.autoconnect", value]]


def test_forget():
    run, calls = fake_nmcli()
    with patch.object(wifi.subprocess, "run", side_effect=run):
        assert wifi.forget_wifi("Home") is True
    assert calls == [["connection", "delete", "id", "Home"]]


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
        self.display.draw_wifi_menu = AsyncMock()
        self._init_wifi_settings()

    async def _navigate_to_page(self, page):
        self.history.append(page)

    async def _go_back(self):
        self.history.pop()

    async def run(self, action):
        """Handle a touch screen action and wait for the WiFi work it starts."""
        self.handle_wifi_action(action)
        if self._wifi_task is not None:
            await self._wifi_task

    def message(self):
        return self.display.stage_wifi_message.call_args.args


NETWORKS = [
    {"ssid": "Home", "signal": 70, "secured": True, "in_use": True},
    {"ssid": "Office", "signal": 60, "secured": True, "in_use": False},
    {"ssid": "Cafe", "signal": 50, "secured": False, "in_use": False},
]


@contextmanager
def nm(profiles=None, connect=(True, "", None), networks=NETWORKS, permitted=True):
    """Stand-ins for the nmcli helpers wifi_settings uses."""
    mocks = SimpleNamespace(
        saved_wifi_profiles=MagicMock(return_value={"Home": True} if profiles is None else profiles),
        scan_networks=MagicMock(side_effect=lambda rescan=True: [dict(n) for n in networks]),
        connect_wifi=MagicMock(side_effect=connect) if callable(connect) else MagicMock(return_value=connect),
        wifi_radio_enabled=MagicMock(return_value=True),
        get_wlan0_ip=MagicMock(return_value="10.0.0.2"),
        wifi_permitted=MagicMock(return_value=permitted),
        set_wifi_autoconnect=MagicMock(return_value=True),
        forget_wifi=MagicMock(return_value=True),
    )
    with ExitStack() as stack:
        for name, mock in vars(mocks).items():
            stack.enter_context(patch(f"src.controller.wifi_settings.{name}", mock))
        yield mocks


async def list_controller(**nm_args):
    controller = FakeController()
    with nm(**nm_args):
        await controller._wifi_scan()
    return controller


@pytest.mark.asyncio
async def test_scan_marks_saved_networks():
    controller = await list_controller(profiles={"Home": True, "Office": False})
    assert [(n["saved"], n["autoconnect"]) for n in controller.wifi_networks] == [
        (True, True), (True, False), (False, None),
    ]


@pytest.mark.asyncio
async def test_secured_unknown_network_asks_for_password_then_connects():
    controller = await list_controller()
    with nm() as mocks:
        await controller.run("wifi_select_1")
        assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_PASSWORD]
        controller.display.stage_wifi_password.assert_called_once_with("Office")

        controller.handle_wifi_password("secret123")
        await controller._wifi_task
        mocks.connect_wifi.assert_called_once_with("Office", "secret123")
        assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_MESSAGE]
        assert controller.message() == ("Office", ["Connected"], False)

        await controller.run("wifi_message_ok")
    assert controller.history == [PAGE_SETTINGS_WIFI]


@pytest.mark.asyncio
async def test_saved_network_opens_its_menu():
    controller = await list_controller(profiles={"Home": True, "Office": False})
    with nm(profiles={"Home": True, "Office": False}) as mocks:
        await controller.run("wifi_select_1")
        assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_MENU]
        controller.display.stage_wifi_menu.assert_called_once_with("Office", False, False)

        await controller.run("wifi_menu_connect")
    mocks.connect_wifi.assert_called_once_with("Office", None)
    assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_MESSAGE]
    assert controller.message() == ("Office", ["Connected"], False)


@pytest.mark.asyncio
async def test_connected_network_menu_does_not_reconnect():
    controller = await list_controller()
    with nm() as mocks:
        await controller.run("wifi_select_0")
        controller.display.stage_wifi_menu.assert_called_once_with("Home", True, True)
        await controller.run("wifi_menu_connect")
    mocks.connect_wifi.assert_not_called()
    assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_MENU]


@pytest.mark.asyncio
async def test_menu_toggles_autoconnect():
    controller = await list_controller(profiles={"Home": True, "Office": False})
    with nm(profiles={"Home": True, "Office": False}) as mocks:
        await controller.run("wifi_select_1")
        await controller.run("wifi_menu_autoconnect")
        mocks.set_wifi_autoconnect.assert_called_once_with("Office", True)
        assert controller.display.draw_wifi_menu.await_args.args[:3] == ("Office", False, True)
        await controller.run("wifi_menu_autoconnect")
        mocks.set_wifi_autoconnect.assert_called_with("Office", False)
    assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_MENU]


@pytest.mark.asyncio
async def test_forget_asks_first():
    controller = await list_controller(profiles={"Home": True, "Office": True})
    with nm(profiles={"Home": True, "Office": True}) as mocks:
        await controller.run("wifi_select_1")
        await controller.run("wifi_menu_forget")
        assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_CONFIRM]
        controller.display.stage_wifi_confirm.assert_called_once_with("Forget?", "Forget Office")
        mocks.forget_wifi.assert_not_called()

        await controller.run("wifi_confirm_yes")
    mocks.forget_wifi.assert_called_once_with("Office")
    assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_MESSAGE]
    assert controller.message() == ("Office", ["Network forgotten"], False)


@pytest.mark.asyncio
async def test_forget_can_be_cancelled():
    controller = await list_controller(profiles={"Home": True, "Office": True})
    with nm(profiles={"Home": True, "Office": True}) as mocks:
        await controller.run("wifi_select_1")
        await controller.run("wifi_menu_forget")
        await controller.run("wifi_confirm_no")
    mocks.forget_wifi.assert_not_called()
    assert controller.history == [PAGE_SETTINGS_WIFI]


@pytest.mark.asyncio
async def test_open_network_asks_before_joining():
    controller = await list_controller()
    with nm() as mocks:
        await controller.run("wifi_select_2")
        assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_CONFIRM]
        controller.display.stage_wifi_confirm.assert_called_once_with("Open network", "Join Cafe")
        mocks.connect_wifi.assert_not_called()

        await controller.run("wifi_confirm_yes")
    mocks.connect_wifi.assert_called_once_with("Cafe", None)
    assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_MESSAGE]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["wifi_menu_forget", "wifi_menu_connect", "wifi_confirm_yes", "wifi_message_ok"])
async def test_dialog_actions_only_work_on_their_own_page(action):
    controller = await list_controller(profiles={"Home": True, "Office": True})
    controller.wifi_menu_network = controller.wifi_networks[1]
    controller._wifi_question = ("forget", "Office")
    with nm() as mocks:
        await controller.run(action)
    assert controller.history == [PAGE_SETTINGS_WIFI]
    mocks.connect_wifi.assert_not_called()
    mocks.forget_wifi.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("result, message", [
    ((False, "Error: Secrets were required, but not provided", None), ["Wrong password"]),
    ((False, "Error: 802-11-wireless-security.psk: property is invalid", None), ["Wrong password"]),
    ((False, "Error: Secrets were required, but not provided", "Home"), ["Wrong password", "Reconnected to Home"]),
    ((False, "Error: Connection activation failed: timeout", "Home"), ["Could not connect", "Reconnected to Home"]),
])
async def test_failed_connect_says_why(result, message):
    controller = keyboard_open_on("Office")
    with nm(connect=result):
        controller.handle_wifi_password("secret123")
        await controller._wifi_task
    assert controller.message() == ("Office", message, True)


@pytest.mark.asyncio
async def test_connect_without_permission_asks_for_a_restart():
    controller = keyboard_open_on("Office")
    with nm(connect=(False, "Error: Not authorized", None), permitted=False):
        controller.handle_wifi_password("secret123")
        await controller._wifi_task
    assert controller.message() == ("Office", ["Restart the printer", "to use WiFi settings"], True)


@pytest.mark.parametrize("component", [1, 2, 3, 8])
def test_keyboard_text_is_the_password_whatever_its_second_byte(component):
    controller = MagicMock()
    DisplayEventsMixin.handle_text_input(controller, 132, component, "secret123")
    controller.handle_wifi_password.assert_called_once_with("secret123")


@pytest.mark.asyncio
@pytest.mark.parametrize("x, y, action", [(140, 285, "wifi_message_ok"), (20, 20, "wifi_message_ok"), (140, 150, None)])
async def test_failure_page_ok_goes_by_position(x, y, action):
    """The stock button on the failure page sends no touch event."""
    controller = MagicMock()
    controller._get_current_page = AsyncMock(return_value=PAGE_SETTINGS_WIFI_ERROR)
    await DisplayEventsMixin.handle_custom_touch(controller, x, y)
    if action:
        controller.execute_action.assert_called_once_with(action)
    else:
        controller.execute_action.assert_not_called()


def test_back_event_on_the_failure_page_is_left_to_the_position_rule():
    controller = MagicMock()
    controller.history = [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_ERROR]
    controller.display.extra_response_actions = {}
    DisplayEventsMixin.handle_response(controller, 121, 0)
    controller._go_back.assert_not_called()  # else back would run twice


def test_text_from_other_pages_is_ignored():
    controller = MagicMock()
    DisplayEventsMixin.handle_text_input(controller, 77, 1, "secret123")
    controller.handle_wifi_password.assert_not_called()


def keyboard_open_on(ssid):
    controller = FakeController(page=PAGE_SETTINGS_WIFI_PASSWORD)
    controller.history = [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_PASSWORD]
    controller.wifi_selected_ssid = ssid
    return controller


@pytest.mark.asyncio
async def test_curly_quotes_from_keyboard_connect_as_straight_quotes():
    controller = keyboard_open_on("Office")
    with nm() as mocks:
        controller.handle_wifi_password("say“hi”")
        await controller._wifi_task
    mocks.connect_wifi.assert_called_once_with("Office", 'say"hi"')


@pytest.mark.asyncio
async def test_password_goes_from_keyboard_straight_to_the_loading_overlay():
    controller = keyboard_open_on("Office")
    seen = []

    def connect(ssid, password):
        seen.append(list(controller.history))
        return False, "Secrets were required", None

    with nm(connect=connect):
        controller.handle_wifi_password("secret123")
        await controller._wifi_task
    assert seen == [[PAGE_SETTINGS_WIFI, PAGE_OVERLAY_LOADING]]
    assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_ERROR]


@pytest.mark.asyncio
async def test_impossible_password_is_not_sent_to_nmcli():
    controller = keyboard_open_on("Office")
    with nm() as mocks:
        controller.handle_wifi_password("pass€word")
        await controller._wifi_task
    mocks.connect_wifi.assert_not_called()
    assert controller.message() == ("Office", ["Password has a character", "WiFi passwords can't have"], True)
    assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_ERROR]


MODE_KEY = (0, 440, 60, 480)
MODE_TAP = (30, 460)
LETTER_TAP = (150, 400)


def keyboard_controller(mode_key=MODE_KEY, on_symbols=True):
    controller = FakeController(page=PAGE_SETTINGS_WIFI_PASSWORD)
    controller.wifi_keyboard_mode_key = mode_key
    controller.display.wifi_keyboard_on_symbols = AsyncMock(return_value=on_symbols)
    controller.display.show_wifi_keyboard_symbols = AsyncMock()
    return controller


async def tap(controller, press, release=None):
    await controller.handle_wifi_keyboard_touch(*press, pressed=True)
    await controller.handle_wifi_keyboard_touch(*(release or press), pressed=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("on_symbols", [True, False])
async def test_mode_key_tap_relabels_only_when_the_panel_shows_symbols(on_symbols):
    controller = keyboard_controller(on_symbols=on_symbols)
    with patch("src.controller.wifi_settings.KEYBOARD_LABEL_SETTLE", 0):
        await tap(controller, MODE_TAP)
    controller.display.wifi_keyboard_on_symbols.assert_awaited_once()
    assert controller.display.show_wifi_keyboard_symbols.await_count == int(on_symbols)


@pytest.mark.asyncio
async def test_mode_key_tap_that_slides_off_still_counts():
    controller = keyboard_controller()
    with patch("src.controller.wifi_settings.KEYBOARD_LABEL_SETTLE", 0):
        await tap(controller, MODE_TAP, release=LETTER_TAP)
    controller.display.show_wifi_keyboard_symbols.assert_awaited_once()


@pytest.mark.asyncio
async def test_other_keys_never_query_the_panel():
    controller = keyboard_controller()
    with patch("src.controller.wifi_settings.KEYBOARD_LABEL_SETTLE", 0):
        await tap(controller, LETTER_TAP)
        await tap(controller, MODE_TAP)
        await tap(controller, LETTER_TAP)  # e.g. OK, whose text must not meet a query
    assert controller.display.wifi_keyboard_on_symbols.await_count == 1


@pytest.mark.asyncio
async def test_stock_keyboard_and_other_pages_are_left_alone():
    controller = keyboard_controller(mode_key=None)
    await tap(controller, MODE_TAP)
    controller.display.wifi_keyboard_on_symbols.assert_not_awaited()
    controller = keyboard_controller()
    controller.history = [PAGE_SETTINGS_WIFI]
    await tap(controller, MODE_TAP)
    controller.display.wifi_keyboard_on_symbols.assert_not_awaited()


@pytest.mark.asyncio
async def test_relabel_failure_does_not_escape():
    controller = keyboard_controller()
    controller.display.wifi_keyboard_on_symbols = AsyncMock(side_effect=TimeoutError)
    with patch("src.controller.wifi_settings.KEYBOARD_LABEL_SETTLE", 0):
        await tap(controller, MODE_TAP)


@pytest.mark.asyncio
async def test_opening_the_keyboard_reads_its_mode_key():
    controller = await list_controller()
    controller.display.wifi_keyboard_mode_key = AsyncMock(return_value=MODE_KEY)
    with nm():
        await controller.run("wifi_select_1")
    assert controller.wifi_keyboard_mode_key == MODE_KEY


class FakeKeyboardPanel(ElegooWifiScreensMixin):
    """keybdA with a firmware version, mode key geometry and label; writes are recorded."""

    def __init__(self, firmware="1.2.16", mode_label="!?#"):
        self.firmware = firmware
        self.mode_label = mode_label
        self.mapper = ElegooDisplayMapper()
        self.timeout = 1
        self.writes = []
        self.display = MagicMock()
        self.display.get = AsyncMock(side_effect=self._get)
        self._serial_lock = asyncio.Lock()

    def _write_without_response(self, command):
        self.writes.append(command)

    async def write(self, command):
        self.writes.append(command)

    async def _execute_command(self, command, timeout=None):
        self.writes.append(command)

    async def get_firmware_version(self):
        return self.firmware

    async def _get(self, attribute, timeout):
        assert attribute.startswith("keybdA.b[30].")
        if attribute.endswith(".txt"):
            return self.mode_label
        return {"x": 0, "y": 440, "w": 60, "h": 40}[attribute[-1]]


@pytest.mark.asyncio
async def test_mode_key_comes_from_the_panel_geometry():
    assert await FakeKeyboardPanel().wifi_keyboard_mode_key() == MODE_KEY


@pytest.mark.asyncio
async def test_unknown_screen_firmware_keeps_the_stock_symbols():
    panel = FakeKeyboardPanel(firmware="1.2.11")
    assert await panel.wifi_keyboard_mode_key() is None
    panel.display.get.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("label, on_symbols", [("ABC", True), ("!?#", False)])
async def test_symbol_page_is_told_by_the_mode_key(label, on_symbols):
    assert await FakeKeyboardPanel(mode_label=label).wifi_keyboard_on_symbols() is on_symbols


@pytest.mark.asyncio
async def test_symbol_page_gets_the_missing_ascii_symbols():
    panel = FakeKeyboardPanel()
    await panel.show_wifi_keyboard_symbols()
    assert panel.writes[0] == "bkcmd=0"
    assert panel.writes[-1] == "bkcmd=3"
    labels = [re.fullmatch(r'keybdA\.b\[\d+\]\.txt="(.*)"', w)[1] for w in panel.writes[1:-1]]
    assert sorted(label for label in labels if label) == sorted(['[', ']', '`', '\\"', "'", '{', '}'])
    assert len(labels) == len(wifi_screens._KEYBOARD_SYMBOL_KEYS)


@pytest.mark.asyncio
async def test_saved_open_network_opens_its_menu_without_asking():
    controller = await list_controller(profiles={"Home": True, "Cafe": True})
    with nm(profiles={"Home": True, "Cafe": True}):
        await controller.run("wifi_select_2")
    assert controller.history == [PAGE_SETTINGS_WIFI, PAGE_SETTINGS_WIFI_MENU]
    controller.display.stage_wifi_confirm.assert_not_called()


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
async def test_list_status_shows_the_connected_network():
    controller = await list_controller()
    assert controller.display.draw_wifi_list.await_args.args[:4] == (controller.wifi_networks, 0, "Home", "10.0.0.2")


@pytest.mark.asyncio
async def test_list_draws_lock_signal_and_saved_colours():
    panel = FakeKeyboardPanel()
    networks = [
        dict(NETWORKS[0], saved=True),  # connected
        dict(NETWORKS[1], saved=True),  # saved
        dict(NETWORKS[2], signal=20, saved=False),  # open, weak
    ]
    await panel.draw_wifi_list(networks, 0, "Home", "10.0.0.2", AsyncMock(return_value=True))
    writes = panel.writes
    assert f"b[4].pco={TEXT_SUCCESS}" in writes
    assert f"b[7].pco={TEXT_HIGHLIGHT}" in writes
    assert f"b[10].pco={TEXT_NORMAL}" in writes
    assert ["b[32].picc=341", "b[33].picc=341", "b[34].picc=340"] == [
        w for w in writes if re.match(r"b\[3[2-4]\]\.picc", w)
    ]
    assert ["b[5].picc=343", "b[8].picc=343", "b[11].picc=341"] == [
        w for w in writes if re.match(r"b\[(5|8|11)\]\.picc", w)
    ]
    assert "vis b[12],0" in writes  # row 4 and later are empty


@pytest.mark.asyncio
@pytest.mark.parametrize("radio_on, picc", [(True, 348), (False, 339)])
async def test_wifi_switch_shows_the_radio_state(radio_on, picc):
    panel = FakeKeyboardPanel()
    await panel.draw_wifi_list([], 0, "WiFi off", None, AsyncMock(return_value=True), radio_on=radio_on)
    assert panel.writes[0] == f"b[41].picc={picc}"


@pytest.mark.asyncio
async def test_list_is_not_drawn_onto_the_page_a_back_tap_went_to():
    panel = FakeKeyboardPanel()
    await panel.draw_wifi_list(NETWORKS, 0, "Home", "10.0.0.2", AsyncMock(return_value=False))
    assert panel.writes == []


@pytest.mark.asyncio
async def test_list_is_drawn_as_one_block():
    panel = FakeKeyboardPanel()
    seen = []

    async def still_on_page():
        seen.append(panel._serial_lock.locked())
        return True

    await panel.draw_wifi_list(NETWORKS, 0, "Home", "10.0.0.2", still_on_page)
    assert seen == [True]  # checked with the serial line held for the whole block


@pytest.mark.asyncio
async def test_pages_get_their_texts_as_they_open():
    panel = FakeKeyboardPanel()
    await panel.draw_wifi_list([], 0, "Home", "10.0.0.2", AsyncMock(return_value=True))
    panel.stage_wifi_menu("Office", False, True)
    panel.stage_wifi_confirm("Forget?", "Forget Office")
    panel.stage_wifi_message("Office", ["Wrong password", "Reconnected to Home"], error=True)
    panel.stage_wifi_password("Office")
    assert panel.page_entry_commands("wifi_list") == [
        "b[41].picc=348", 'b[27].txt="Home"', 'b[28].txt="IP:10.0.0.2"',
    ]
    assert panel.page_entry_commands("134") == [
        'b[2].txt="Office"', 'b[4].txt="Connect"', 'b[7].txt="Auto-connect: On"', 'b[9].txt="Forget network"',
    ]
    assert panel.page_entry_commands("136") == [
        'b[2].txt="Forget?"', 'b[4].txt="Forget Office"', 'b[7].txt="Cancel"',
    ]
    assert panel.page_entry_commands("121") == [
        'b[1].txt="Office"', 'b[3].txt="Wrong password\\rReconnected to Home"', 'b[4].txt="OK"',
    ]
    assert panel.page_entry_commands("125") == []  # the success page wasn't staged
    assert panel.page_entry_commands("keybdA") == ['b[49].txt="Office"', 'b[35].txt=""', 'b[34].txt=""']
    assert panel.page_entry_commands("main") == []


@pytest.mark.asyncio
async def test_navigation_sends_page_entry_commands_before_anything_queued():
    sent = []

    class Panel:
        navigate_to = DisplayCommunicator.navigate_to

        def __init__(self):
            self._nav_lock = asyncio.Lock()

        async def write(self, command, blocked_key=None, auto_unblock=True):
            sent.append((command, blocked_key))

        async def unblock(self, key):
            sent.append(("unblock", key))

        def page_entry_commands(self, page_id):
            return ['b[27].txt="Home"'] if page_id == "wifi_list" else []

    with patch("src.communicator.asyncio.sleep", AsyncMock()):
        await Panel().navigate_to("wifi_list")
    assert sent == [
        ("page wifi_list", "__nav__"), ('b[27].txt="Home"', "__nav__"), ("unblock", "__nav__"),
    ]


@pytest.mark.asyncio
async def test_list_is_not_drawn_on_another_page():
    controller = FakeController(page=PAGE_OVERLAY_LOADING)
    await controller._draw_wifi_list()
    controller.display.draw_wifi_list.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_scan_with_wifi_off():
    controller = FakeController()
    with nm() as mocks:
        mocks.wifi_radio_enabled.return_value = False
        await controller._wifi_scan()
    mocks.scan_networks.assert_not_called()
    assert controller.wifi_status is None
    assert controller.display.draw_wifi_list.await_args.args[:4] == ([], 0, "WiFi off", None)


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
