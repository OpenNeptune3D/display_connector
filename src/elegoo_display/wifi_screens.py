"""WiFi settings screens (stock wifi_list and keybdA pages) for ElegooDisplayCommunicator."""

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

# set_4_max: text of the "Factory Settings" row, reused for Temperature Settings
_SETTINGS_FACTORY_ROW_TEXT = 19


def _quote(text):
    """Make text safe to put inside a TJC "..." string."""
    return text.replace("\\", "\\\\").replace('"', "'")


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

        await self.write(f'{prefix}.b[{_STATUS_TEXT}].txt="{_quote(_shorten(status, 12))}"')
        await self.write(f'{prefix}.b[{_IP_TEXT}].txt="{"IP:" + ip if ip else ""}"')

    async def draw_wifi_password(self, ssid):
        prefix = self.mapper.map_page(PAGE_SETTINGS_WIFI_PASSWORD)
        await self.write(f'{prefix}.b[{_KEYBOARD_TITLE}].txt="{_quote(_shorten(ssid, 20))}"')
        await self.write(f'{prefix}.b[{_KEYBOARD_INPUT}].txt=""')
