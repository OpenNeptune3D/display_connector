"""Touch screen WiFi settings (#17): scan, join and switch WiFi with nmcli for DisplayController."""

import asyncio

from src.mapping import (
    PAGE_OVERLAY_LOADING,
    PAGE_SETTINGS_WIFI,
    PAGE_SETTINGS_WIFI_PASSWORD,
)
from src.wifi import (
    clean_wifi_password,
    connect_wifi,
    get_wlan0_ip,
    saved_wifi_connections,
    scan_networks,
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


class WifiSettingsMixin:
    """WiFi network list, password entry and the WiFi on/off toggle."""

    def _init_wifi_settings(self):
        self.wifi_networks = []
        self.wifi_page = 0
        self.wifi_status = None  # message replacing the connection status, if any
        self.wifi_selected_ssid = None
        self._wifi_task = None
        self._wifi_header = ("", None)  # status and IP last drawn on the list
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

    def handle_wifi_password(self, password):
        ssid = self.wifi_selected_ssid
        self.wifi_selected_ssid = None
        if ssid is None:
            self._loop.create_task(self._go_back())
            return
        password = clean_wifi_password(password)
        if password is None:
            # Back to the list, which shows the status instead of the network name
            logger.info(f"WiFi password for {ssid!r} has characters a WiFi password can't contain")
            self.wifi_status = "Invalid char"
            self._loop.create_task(self._go_back())
            return
        self._run_wifi_task(self._wifi_connect(ssid, password, from_keyboard=True))

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
        await self._navigate_to_page(PAGE_SETTINGS_WIFI_PASSWORD)
        await self.display.draw_wifi_password(ssid)
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
        # The page comes back with its stock "Label" placeholder in the status
        # line; cover it before the nmcli calls below, which take a moment
        last_status, last_ip = self._wifi_header
        await self.display.draw_wifi_header(self.wifi_status or last_status, last_ip)
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
        self._wifi_header = (status, ip)
        await self.display.draw_wifi_list(self.wifi_networks, self.wifi_page, status, ip)

    async def _wifi_failure_status(self, default):
        """Tell the user to reboot when the polkit rule isn't in place yet.

        display.service installs it as it starts, so a reboot (or a display
        service restart) fixes it.
        """
        if not await asyncio.to_thread(wifi_permitted):
            return "Need reboot"
        return default

    async def _wifi_scan(self):
        # Show what NetworkManager already knows straight away, then rescan
        self.wifi_networks = await asyncio.to_thread(scan_networks, False)
        if not await asyncio.to_thread(wifi_permitted):
            # "dev wifi list --rescan yes" quietly skips a scan it isn't allowed
            # to do and lists only what NetworkManager already knows
            self.wifi_status = "Need reboot"
            await self._draw_wifi_list()
            return
        self.wifi_status = "Scanning..."
        await self._draw_wifi_list()
        networks = await asyncio.to_thread(scan_networks, True)
        if networks:
            self.wifi_networks = networks
            last_page = max(0, (len(networks) - 1) // WIFI_ROWS_PER_PAGE)
            self.wifi_page = min(self.wifi_page, last_page)
        self.wifi_status = None if networks else await self._wifi_failure_status("Scan failed")
        await self._draw_wifi_list()

    async def _wifi_select(self, network):
        ssid = network["ssid"]
        if network["in_use"]:
            return
        if network["secured"] and ssid not in await asyncio.to_thread(saved_wifi_connections):
            self.wifi_selected_ssid = ssid
            await self._open_wifi_keyboard(ssid)
            return
        await self._wifi_connect(ssid, None)

    async def _wifi_connect(self, ssid, password, from_keyboard=False):
        logger.info(f"Connecting to WiFi network {ssid!r}")
        if from_keyboard:
            # Straight from the keyboard to the loading overlay, so going back
            # lands on the list. Showing the list in between only flashed its
            # stock "Label" placeholder before the overlay replaced it.
            async with self._history_lock:
                if self.history and self.history[-1] == PAGE_SETTINGS_WIFI_PASSWORD:
                    self.history.pop()
        await self._navigate_to_page(PAGE_OVERLAY_LOADING)
        ok, output = await asyncio.to_thread(connect_wifi, ssid, password)
        self.display.invalidate_wifi_status()
        if ok:
            self.wifi_status = "Connected"
        elif "Secrets were required" in output or "psk" in output:
            self.wifi_status = "Wrong password"
        else:
            self.wifi_status = await self._wifi_failure_status("Failed")
        self.wifi_networks = await asyncio.to_thread(scan_networks, False)
        if await self._wifi_on_page(PAGE_OVERLAY_LOADING):
            await self._go_back()  # back to the list, which redraws it

    async def _wifi_toggle(self):
        enable = not await asyncio.to_thread(wifi_radio_enabled)
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
