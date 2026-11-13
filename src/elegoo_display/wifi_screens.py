"""WiFi settings screens (stock wifi_list and keybdA pages) for ElegooDisplayCommunicator."""

import asyncio

from src.mapping import (
    PAGE_SETTINGS,
    PAGE_SETTINGS_WIFI,
    PAGE_SETTINGS_WIFI_PASSWORD,
    PAGE_SETTINGS_WIFI_MENU,
    PAGE_SETTINGS_WIFI_CONFIRM,
    PAGE_SETTINGS_WIFI_MESSAGE,
)
from src.colors import (
    TEXT_HIGHLIGHT,
    TEXT_NORMAL,
    TEXT_SUCCESS,
)
from src.wifi import categorize_signal_strength

WIFI_ROWS_PER_PAGE = 8

# wifi_list component ids, read from the panel. Row n has a button, an SSID text
# and a signal icon at 3+3n, 4+3n and 5+3n, and a lock icon at 32+n.
_ROW_BUTTON, _ROW_TEXT, _ROW_SIGNAL, _ROW_LOCK = 3, 4, 5, 32
_STATUS_TEXT = 27  # left of the header line, "Label" in the stock HMI
_IP_TEXT = 28
_SSID_MAX_CHARS = 18
# The icons are crops of full-page pictures: 340 has none, 341 has the lock (in
# the lock column) and one signal bar, 342-344 two to four bars
_ICON_NONE = 340
_ICON_LOCK = 341
_ICON_SIGNAL_BASE = 340  # + 1-4 bars

# Saved network menu (stock "Print mode" list): title and three row texts
_MENU_TITLE = 2
_MENU_ROWS = (4, 7, 9)
# Yes/no question (stock "Leveling mode" list): title and two row texts
_CONFIRM_TITLE = 2
_CONFIRM_ROWS = (4, 7)
# Message (stock PID "Detection completed" page): title, text and the button
_MESSAGE_TITLE = 1
_MESSAGE_TEXT = 3
_MESSAGE_BUTTON = 4

# keybdA component ids: the input shows the typed text, which is kept in the
# _KEYBOARD_TEXT variable; OK sends that variable
_KEYBOARD_TITLE = 49
_KEYBOARD_INPUT = 35
_KEYBOARD_TEXT = 34

_KEYBOARD_BURST_SETTLE = 0.05

# "!?#" on the letters page, "ABC" on the symbol page
_KEYBOARD_MODE_KEY = 30
_KEYBOARD_MODE_ON_SYMBOLS = "ABC"

# keybdA symbol page keys whose characters can't be in a WiFi password (WPA
# passphrases are printable ASCII), with the ASCII symbols the page is missing
# put in their place; the rest are blanked. A key types its current label, but
# the panel puts its own labels back every time it switches to the symbol page.
# Read from a Neptune 4 Pro screen; other firmware keeps the stock symbols.
_KEYBOARD_SYMBOL_FIRMWARE = {"1.2.16"}
_KEYBOARD_SYMBOL_KEYS = {
    # id: (stock label, wifi label)
    8: ("、", ""),     # ideographic comma
    20: ("《", "["),   # double angle brackets
    21: ("》", "]"),
    26: ("￥", "`"),   # fullwidth yen
    27: ("“", '"'),   # curly double quotes
    28: ("”", "'"),
    41: ("×", ""),    # multiplication sign
    45: ("£", "{"),   # pound
    46: ("€", "}"),   # euro
    47: ("…", ""),    # ellipsis
    48: ("¢", ""),    # cent
}

# set_4_max: text of the "Factory Settings" row, reused for Temperature Settings
_SETTINGS_FACTORY_ROW_TEXT = 19


def _quote(text):
    """Make text safe to put inside a TJC "..." string."""
    return text.replace("\\", "\\\\").replace('"', "'")


def _escape(text):
    """Escape text for a TJC "..." string, keeping double quotes."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _shorten(text, limit):
    return text if len(text) <= limit else text[: limit - 2] + ".."


def _text(component, text, limit=None):
    """Set a text on the current page."""
    if limit is not None:
        text = _shorten(text, limit)
    return f'b[{component}].txt="{_quote(text)}"'


class ElegooWifiScreensMixin:
    """WiFi network list, password keyboard and the dialogs around them.

    The dialogs are stock pages with their texts swapped. Their texts are sent
    as page entry commands, right after the page switch, so the stock ones
    never show.
    """

    def page_entry_commands(self, page_id):
        return list(getattr(self, "_wifi_page_entry", {}).get(page_id, ()))

    def _set_page_entry(self, page, commands):
        if not hasattr(self, "_wifi_page_entry"):
            self._wifi_page_entry = {}
        self._wifi_page_entry[self.mapper.map_page(page)] = commands

    def stage_wifi_menu(self, ssid, connected, autoconnect):
        """Texts for the saved network menu, for the next time it is shown."""
        self._set_page_entry(PAGE_SETTINGS_WIFI_MENU, [
            _text(_MENU_TITLE, ssid, 20),
            _text(_MENU_ROWS[0], "Connected" if connected else "Connect"),
            _text(_MENU_ROWS[1], f"Auto-connect: {'On' if autoconnect else 'Off'}"),
            _text(_MENU_ROWS[2], "Forget network"),
        ])

    async def draw_wifi_menu(self, ssid, connected, autoconnect):
        """Redraw the saved network menu while it is shown."""
        self.stage_wifi_menu(ssid, connected, autoconnect)
        for command in self.page_entry_commands(self.mapper.map_page(PAGE_SETTINGS_WIFI_MENU)):
            await self.write(command)

    def stage_wifi_confirm(self, title, yes, no="Cancel"):
        self._set_page_entry(PAGE_SETTINGS_WIFI_CONFIRM, [
            _text(_CONFIRM_TITLE, title, 12),
            _text(_CONFIRM_ROWS[0], yes, 16),
            _text(_CONFIRM_ROWS[1], no, 16),
        ])

    def stage_wifi_message(self, text, title="WLAN", button="OK"):
        self._set_page_entry(PAGE_SETTINGS_WIFI_MESSAGE, [
            _text(_MESSAGE_TITLE, title),
            _text(_MESSAGE_TEXT, text, 60),
            _text(_MESSAGE_BUTTON, button),
        ])

    async def update_settings_page(self):
        # Only set_4_max needs this; the "set" page has its own Temperature row
        if self.mapper.map_page(PAGE_SETTINGS) == "set_4_max":
            await self.write(f'b[{_SETTINGS_FACTORY_ROW_TEXT}].txt="Temperature Settings"')

    async def draw_wifi_list(self, networks, page, status, ip):
        """Fill the 8 rows of wifi_list with one page of networks.

        Must only be called while wifi_list is the current page: the row buttons
        are local components, so `vis` and their attributes only work there.
        """
        prefix = self.mapper.map_page(PAGE_SETTINGS_WIFI)
        # Status line first: until it is written the page shows its stock "Label"
        await self.draw_wifi_header(status, ip)
        shown = networks[page * WIFI_ROWS_PER_PAGE:(page + 1) * WIFI_ROWS_PER_PAGE]
        for row in range(WIFI_ROWS_PER_PAGE):
            ids = (
                _ROW_BUTTON + 3 * row,
                _ROW_TEXT + 3 * row,
                _ROW_SIGNAL + 3 * row,
                _ROW_LOCK + row,
            )
            if row >= len(shown):
                for component in ids:
                    await self.write(f"vis b[{component}],0")
                continue
            network = shown[row]
            text_id = ids[1]
            await self.write(f"vis b[{ids[0]}],1")
            await self.write(f"vis b[{text_id}],1")
            await self.write(
                f'{prefix}.b[{text_id}].txt="{_quote(_shorten(network["ssid"], _SSID_MAX_CHARS))}"'
            )
            if network["in_use"]:
                color = TEXT_SUCCESS
            elif network.get("saved"):
                color = TEXT_HIGHLIGHT
            else:
                color = TEXT_NORMAL
            await self.write(f"{prefix}.b[{text_id}].pco={color}")
            bars = categorize_signal_strength(network["signal"])
            await self.write(f"b[{ids[2]}].picc={_ICON_SIGNAL_BASE + bars if bars else _ICON_NONE}")
            await self.write(f"vis b[{ids[2]}],1")
            await self.write(f"b[{ids[3]}].picc={_ICON_LOCK if network['secured'] else _ICON_NONE}")
            await self.write(f"vis b[{ids[3]}],1")

    async def draw_wifi_header(self, status, ip):
        """The status and IP texts above the wifi_list rows.

        Also kept as page entry commands, so coming back to the list shows the
        last status straight away instead of the stock "Label".
        """
        commands = [
            _text(_STATUS_TEXT, status, 12),
            f'b[{_IP_TEXT}].txt="{"IP:" + ip if ip else ""}"',
        ]
        self._set_page_entry(PAGE_SETTINGS_WIFI, commands)
        for command in commands:
            await self.write(command)

    def stage_wifi_password(self, ssid):
        """Keyboard title, and nothing typed yet, for the next time it is shown."""
        self._set_page_entry(PAGE_SETTINGS_WIFI_PASSWORD, [
            _text(_KEYBOARD_TITLE, ssid, 20),
            f'b[{_KEYBOARD_INPUT}].txt=""',
            f'b[{_KEYBOARD_TEXT}].txt=""',
        ])

    async def wifi_keyboard_mode_key(self):
        """Where keybdA's letters/symbols key is, as (x0, y0, x1, y1).

        None on screen firmware whose symbol layout isn't known. Call right after
        opening the keyboard, before anything is typed: the typed text has no
        terminator, so a query reply must not cross it on the serial line.
        """
        if await self.get_firmware_version() not in _KEYBOARD_SYMBOL_FIRMWARE:
            return None
        prefix = self.mapper.map_page(PAGE_SETTINGS_WIFI_PASSWORD)
        x, y, w, h = [
            int(await self.display.get(f"{prefix}.b[{_KEYBOARD_MODE_KEY}].{attribute}", self.timeout))
            for attribute in ("x", "y", "w", "h")
        ]
        return x, y, x + w, y + h

    async def wifi_keyboard_on_symbols(self):
        """Is keybdA showing its symbol page? The mode key then offers the letters."""
        prefix = self.mapper.map_page(PAGE_SETTINGS_WIFI_PASSWORD)
        mode = await self.display.get(f"{prefix}.b[{_KEYBOARD_MODE_KEY}].txt", self.timeout)
        return mode == _KEYBOARD_MODE_ON_SYMBOLS

    async def show_wifi_keyboard_symbols(self):
        """Swap the symbol page's non-ASCII keys for the ASCII symbols it lacks."""
        prefix = self.mapper.map_page(PAGE_SETTINGS_WIFI_PASSWORD)
        labels = [f'{prefix}.b[{key}].txt="{_escape(label)}"' for key, (_, label) in _KEYBOARD_SYMBOL_KEYS.items()]
        # One burst instead of a write per key: status updates keep the serial line
        # busy, and waiting for every label's ack behind them took 1-2 s. bkcmd=0
        # stops the acks, and the acknowledged bkcmd=3 at the end means the panel
        # has done the rest. (Holding the redraw with ref_stop/ref_star made the
        # whole keyboard blink, and the burst is quick enough without it.)
        async with self._serial_lock:
            for command in ("bkcmd=0", *labels):
                self._write_without_response(command)
            # Let a reply to bkcmd=0 itself arrive, so the next command flushes it
            await asyncio.sleep(_KEYBOARD_BURST_SETTLE)
            await self._execute_command("bkcmd=3")
