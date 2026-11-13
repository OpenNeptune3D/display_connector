"""Touch screen WiFi settings (#17): scan, join and switch WiFi with nmcli for DisplayController."""

import asyncio

from src.mapping import (
    PAGE_OVERLAY_LOADING,
    PAGE_SETTINGS_WIFI,
    PAGE_SETTINGS_WIFI_PASSWORD,
    PAGE_SETTINGS_WIFI_MENU,
    PAGE_SETTINGS_WIFI_CONFIRM,
    PAGE_SETTINGS_WIFI_MESSAGE,
    PAGE_SETTINGS_WIFI_ERROR,
)
from src.wifi import (
    clean_wifi_password,
    connect_wifi,
    forget_wifi,
    get_wlan0_ip,
    saved_wifi_profiles,
    scan_networks,
    set_wifi_autoconnect,
    set_wifi_radio,
    wifi_permitted,
    wifi_radio_enabled,
)
from src.elegoo_display.wifi_screens import WIFI_ROWS_PER_PAGE
from src.controller.common import (
    logger,
)


# Time for the panel to put its own labels up after switching to the symbol page
KEYBOARD_LABEL_SETTLE = 0.1


def _inside(bounds, x, y):
    x0, y0, x1, y1 = bounds
    return x0 <= x < x1 and y0 <= y < y1


def _annotate(networks, profiles):
    """Mark which scanned networks have a saved profile, and its autoconnect."""
    for network in networks:
        network["saved"] = network["ssid"] in profiles
        network["autoconnect"] = profiles.get(network["ssid"])
    return networks


def _load_networks(rescan):
    """Scan (or list what NetworkManager knows) and mark the saved networks."""
    return _annotate(scan_networks(rescan), saved_wifi_profiles())


class WifiSettingsMixin:
    """WiFi network list, password entry, saved network menu and the WiFi toggle.

    Tapping a network opens its menu if it is saved (connect, autoconnect,
    forget), the keyboard if it needs a password, or a question if it is open.
    Results come up as a message with an OK button.
    """

    def _init_wifi_settings(self):
        self.wifi_networks = []
        self.wifi_page = 0
        self.wifi_status = None  # message replacing the connection status, if any
        self.wifi_selected_ssid = None  # network the keyboard is for
        self.wifi_menu_network = None  # saved network whose menu is shown
        self._wifi_question = None  # ("join" | "forget", ssid) asked on the confirm page
        self._wifi_task = None
        self.wifi_keyboard_mode_key = None  # its bounds; None leaves the keyboard stock
        self._wifi_mode_key_pressed = False

    def _wifi_busy(self):
        return self._wifi_task is not None and not self._wifi_task.done()

    def _run_wifi_task(self, coro):
        """Run one WiFi operation at a time; taps while one is running are ignored."""
        if self._wifi_busy():
            coro.close()
            return
        self._wifi_task = self._loop.create_task(coro)

    def handle_wifi_action(self, action):
        if action == "wifi_open":
            self.wifi_page = 0
            self.wifi_status = None
            self._loop.create_task(self._navigate_to_page(PAGE_SETTINGS_WIFI))
            self._run_wifi_task(self._wifi_scan())
        elif action == "wifi_refresh":
            self._run_wifi_task(self._wifi_scan())
        elif action in ("wifi_page_prev", "wifi_page_next"):
            last_page = max(0, (len(self.wifi_networks) - 1) // WIFI_ROWS_PER_PAGE)
            step = -1 if action == "wifi_page_prev" else 1
            self.wifi_page = min(max(self.wifi_page + step, 0), last_page)
            self._loop.create_task(self._draw_wifi_list())
        elif action.startswith("wifi_select_"):
            row = int(action.rsplit("_", 1)[1])
            index = self.wifi_page * WIFI_ROWS_PER_PAGE + row
            if index < len(self.wifi_networks):
                self._run_wifi_task(self._wifi_select(self.wifi_networks[index]))
        elif action == "wifi_toggle":
            self._run_wifi_task(self._wifi_toggle())
        elif action.startswith("wifi_menu_"):
            self._run_wifi_task(self._wifi_menu_action(action[len("wifi_menu_"):]))
        elif action in ("wifi_confirm_yes", "wifi_confirm_no"):
            self._run_wifi_task(self._wifi_answer(action == "wifi_confirm_yes"))
        elif action == "wifi_message_ok":
            self._run_wifi_task(self._wifi_leave_message())

    def handle_wifi_password(self, password):
        ssid = self.wifi_selected_ssid
        self.wifi_selected_ssid = None
        if ssid is None:
            self._loop.create_task(self._go_back())
            return
        password = clean_wifi_password(password)
        if password is None:
            logger.info(f"WiFi password for {ssid!r} has characters a WiFi password can't contain")
            self._run_wifi_task(self._wifi_show_message(
                ssid, ["Password has a character", "WiFi passwords can't have"], error=True
            ))
            return
        self._run_wifi_task(self._wifi_connect(ssid, password))

    async def _wifi_replace_page(self, page):
        """Go to page in place of the current one, so back skips the current one."""
        async with self._history_lock:
            if len(self.history) > 1:
                self.history.pop()
        await self._navigate_to_page(page)

    async def _wifi_show_message(self, title, lines, error=False):
        self.display.stage_wifi_message(title, lines, error)
        await self._wifi_replace_page(PAGE_SETTINGS_WIFI_ERROR if error else PAGE_SETTINGS_WIFI_MESSAGE)

    async def _wifi_leave_message(self):
        if await self._wifi_on_page(PAGE_SETTINGS_WIFI_MESSAGE) or await self._wifi_on_page(
            PAGE_SETTINGS_WIFI_ERROR
        ):
            await self._go_back()

    async def _wifi_open_menu(self, network):
        self.wifi_menu_network = network
        self.display.stage_wifi_menu(network["ssid"], network["in_use"], network.get("autoconnect", True))
        await self._navigate_to_page(PAGE_SETTINGS_WIFI_MENU)

    async def _wifi_menu_action(self, action):
        network = self.wifi_menu_network
        if network is None or not await self._wifi_on_page(PAGE_SETTINGS_WIFI_MENU):
            return
        ssid = network["ssid"]
        if action == "connect":
            if not network["in_use"]:
                await self._wifi_connect(ssid, None)
        elif action == "autoconnect":
            enabled = not network.get("autoconnect", True)
            if await asyncio.to_thread(set_wifi_autoconnect, ssid, enabled):
                network["autoconnect"] = enabled
                await self.display.draw_wifi_menu(
                    ssid, network["in_use"], enabled, lambda: self._wifi_on_page(PAGE_SETTINGS_WIFI_MENU)
                )
        elif action == "forget":
            self._wifi_question = ("forget", ssid)
            self.display.stage_wifi_confirm("Forget?", f"Forget {ssid}")
            await self._wifi_replace_page(PAGE_SETTINGS_WIFI_CONFIRM)

    async def _wifi_ask_join_open(self, ssid):
        self._wifi_question = ("join", ssid)
        self.display.stage_wifi_confirm("Open network", f"Join {ssid}")
        await self._navigate_to_page(PAGE_SETTINGS_WIFI_CONFIRM)

    async def _wifi_answer(self, yes):
        question, self._wifi_question = self._wifi_question, None
        if question is None or not await self._wifi_on_page(PAGE_SETTINGS_WIFI_CONFIRM):
            return
        if not yes:
            await self._go_back()
            return
        kind, ssid = question
        if kind == "radio_off":
            await self._go_back()  # to the list, which then shows WiFi off
            await self._wifi_set_radio(False)
        elif kind == "join":
            await self._wifi_connect(ssid, None)
        elif kind == "forget":
            if await asyncio.to_thread(forget_wifi, ssid):
                self.display.invalidate_wifi_status()
                self.wifi_networks = await asyncio.to_thread(_load_networks, False)
                await self._wifi_show_message(ssid, ["Network forgotten"])
            else:
                await self._wifi_show_message(
                    ssid, await self._wifi_failure_lines("Could not forget it"), error=True
                )

    async def handle_wifi_keyboard_touch(self, x, y, pressed):
        """After a tap on the keyboard's mode key, relabel the symbol page if it is up.

        Only the mode key is followed, and the panel is only asked which page is up
        after it: the typed text has no terminator, so a query reply that crossed
        it on the serial line would end up in the password. Nobody presses OK
        within a tenth of a second of switching pages.
        """
        key = self.wifi_keyboard_mode_key
        if key is None or not await self._wifi_on_page(PAGE_SETTINGS_WIFI_PASSWORD):
            return
        if pressed:
            # A tap that starts on the key and slides off still switches pages
            self._wifi_mode_key_pressed = _inside(key, x, y)
            return
        if not (self._wifi_mode_key_pressed or _inside(key, x, y)):
            return
        self._wifi_mode_key_pressed = False
        # The panel puts its stock labels back as it switches; replace them after
        await asyncio.sleep(KEYBOARD_LABEL_SETTLE)
        try:
            if await self.display.wifi_keyboard_on_symbols():
                await self.display.show_wifi_keyboard_symbols()
        except Exception as e:
            logger.debug(f"Could not relabel the WiFi keyboard symbols: {e}")

    async def _open_wifi_keyboard(self, ssid):
        self.display.stage_wifi_password(ssid)
        await self._navigate_to_page(PAGE_SETTINGS_WIFI_PASSWORD)
        self._wifi_mode_key_pressed = False
        self.wifi_keyboard_mode_key = None
        mode_key = getattr(self.display, "wifi_keyboard_mode_key", None)
        if mode_key is None:
            return
        try:
            self.wifi_keyboard_mode_key = await mode_key()
        except Exception as e:
            logger.debug(f"WiFi keyboard keeps its stock symbols: {e}")

    async def show_wifi_settings(self):
        """Page entry (also when coming back from the keyboard or loading overlay)."""
        await self._draw_wifi_list()

    async def _wifi_on_page(self, page):
        async with self._history_lock:
            return bool(self.history) and self.history[-1] == page

    async def _draw_wifi_list(self):
        if not await self._wifi_on_page(PAGE_SETTINGS_WIFI):
            return
        radio_on = await asyncio.to_thread(wifi_radio_enabled)
        ip = await asyncio.to_thread(get_wlan0_ip) if radio_on else None
        status = self.wifi_status
        if status is None:
            connected = next((n for n in self.wifi_networks if n["in_use"]), None)
            if not radio_on:
                status = "WiFi off"
            elif connected:
                status = connected["ssid"]
            else:
                status = "Not connected"
        await self.display.draw_wifi_list(
            self.wifi_networks, self.wifi_page, status, ip,
            lambda: self._wifi_on_page(PAGE_SETTINGS_WIFI), radio_on=radio_on,
        )

    async def _wifi_failure_status(self, default):
        """Tell the user to reboot when the polkit rule isn't in place yet.

        display.service installs it as it starts, so a reboot (or a display
        service restart) fixes it.
        """
        if not await asyncio.to_thread(wifi_permitted):
            return "Need reboot"
        return default

    async def _wifi_failure_lines(self, default):
        if not await asyncio.to_thread(wifi_permitted):
            return ["Restart the printer", "to use WiFi settings"]
        return [default]

    async def _wifi_scan(self):
        if not await asyncio.to_thread(wifi_radio_enabled):
            # Nothing to scan with; the list says "WiFi off"
            self.wifi_networks = []
            self.wifi_page = 0
            self.wifi_status = None
            await self._draw_wifi_list()
            return
        # Show what NetworkManager already knows straight away, then rescan
        self.wifi_networks = await asyncio.to_thread(_load_networks, False)
        if not await asyncio.to_thread(wifi_permitted):
            # "dev wifi list --rescan yes" quietly skips a scan it isn't allowed
            # to do and lists only what NetworkManager already knows
            self.wifi_status = "Need reboot"
            await self._draw_wifi_list()
            return
        self.wifi_status = "Scanning..."
        await self._draw_wifi_list()
        networks = await asyncio.to_thread(_load_networks, True)
        if networks:
            self.wifi_networks = networks
            last_page = max(0, (len(networks) - 1) // WIFI_ROWS_PER_PAGE)
            self.wifi_page = min(self.wifi_page, last_page)
        self.wifi_status = None if networks else await self._wifi_failure_status("Scan failed")
        await self._draw_wifi_list()

    async def _wifi_select(self, network):
        ssid = network["ssid"]
        profiles = await asyncio.to_thread(saved_wifi_profiles)
        _annotate([network], profiles)
        if network["in_use"] or network["saved"]:
            await self._wifi_open_menu(network)
        elif network["secured"]:
            self.wifi_selected_ssid = ssid
            await self._open_wifi_keyboard(ssid)
        else:
            await self._wifi_ask_join_open(ssid)

    async def _wifi_connect(self, ssid, password):
        """Connect with the loading overlay up, then show how it went.

        Called from the keyboard, the menu or the open network question, which
        the overlay replaces, so OK on the result goes back to the list.
        """
        logger.info(f"Connecting to WiFi network {ssid!r}")
        await self._wifi_replace_page(PAGE_OVERLAY_LOADING)
        ok, output, fallback = await asyncio.to_thread(connect_wifi, ssid, password)
        self.display.invalidate_wifi_status()
        self.wifi_status = None
        self.wifi_networks = await asyncio.to_thread(_load_networks, False)
        if ok:
            lines = ["Connected"]
        elif "Secrets were required" in output or "psk" in output:
            lines = ["Wrong password"]
        else:
            lines = await self._wifi_failure_lines("Could not connect")
        if fallback:
            lines.append(f"Reconnected to {fallback}")
        if await self._wifi_on_page(PAGE_OVERLAY_LOADING):
            await self._wifi_show_message(ssid, lines, error=not ok)

    async def _wifi_toggle(self):
        if await asyncio.to_thread(wifi_radio_enabled):
            # Off takes the printer offline, and only the screen can undo it
            self._wifi_question = ("radio_off", None)
            self.display.stage_wifi_confirm("WiFi off?", "Turn WiFi off", "Keep it on")
            await self._navigate_to_page(PAGE_SETTINGS_WIFI_CONFIRM)
            return
        await self._wifi_set_radio(True)

    async def _wifi_set_radio(self, enable):
        if not await asyncio.to_thread(set_wifi_radio, enable):
            self.wifi_status = await self._wifi_failure_status("Not allowed")
            await self._draw_wifi_list()
            return
        self.display.invalidate_wifi_status()
        self.wifi_status = None
        if enable:
            # Give the adapter a moment to come up before scanning
            await asyncio.sleep(3)
            await self._wifi_scan()
        else:
            self.wifi_networks = []
            self.wifi_page = 0
            await self._draw_wifi_list()
