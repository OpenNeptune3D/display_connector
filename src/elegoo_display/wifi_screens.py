"""WiFi settings screens (stock wifi_list and keybdA pages) for ElegooDisplayCommunicator."""

import asyncio

from src.mapping import (
    PAGE_SETTINGS,
    PAGE_SETTINGS_WIFI,
    PAGE_SETTINGS_WIFI_PASSWORD,
)
from src.colors import (
    TEXT_NORMAL,
    TEXT_SUCCESS,
)

WIFI_ROWS_PER_PAGE = 8

# wifi_list component ids, read from the panel. Row n has a button, an SSID text
# and a signal icon at 3+3n, 4+3n and 5+3n, and a lock icon at 32+n.
_ROW_BUTTON, _ROW_TEXT, _ROW_SIGNAL, _ROW_LOCK = 3, 4, 5, 32
_STATUS_TEXT = 27  # left of the header line, "Label" in the stock HMI
_IP_TEXT = 28
_SSID_MAX_CHARS = 18

# keybdA component ids
_KEYBOARD_TITLE = 49
_KEYBOARD_INPUT = 35

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


class ElegooWifiScreensMixin:
    """WiFi network list and password keyboard."""

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
            await self.write(
                f"{prefix}.b[{text_id}].pco={TEXT_SUCCESS if network['in_use'] else TEXT_NORMAL}"
            )
            # The stock signal and lock icon pictures aren't mapped yet
            await self.write(f"vis b[{ids[2]}],0")
            await self.write(f"vis b[{ids[3]}],0")

    async def draw_wifi_header(self, status, ip):
        """The status and IP texts above the wifi_list rows."""
        prefix = self.mapper.map_page(PAGE_SETTINGS_WIFI)
        await self.write(f'{prefix}.b[{_STATUS_TEXT}].txt="{_quote(_shorten(status, 12))}"')
        await self.write(f'{prefix}.b[{_IP_TEXT}].txt="{"IP:" + ip if ip else ""}"')

    async def draw_wifi_password(self, ssid):
        prefix = self.mapper.map_page(PAGE_SETTINGS_WIFI_PASSWORD)
        await self.write(f'{prefix}.b[{_KEYBOARD_TITLE}].txt="{_quote(_shorten(ssid, 20))}"')
        await self.write(f'{prefix}.b[{_KEYBOARD_INPUT}].txt=""')

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
