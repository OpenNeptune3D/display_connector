import logging
import subprocess  # nosec


logger = logging.getLogger(__name__)

_NMCLI_TIMEOUT = 5  # seconds per subprocess call

def get_wlan0_status():
    """
    Get WiFi status without triggering a scan by using cached data.
    This is much lighter on the hardware.
    """
    try:
        # Get connection name and state from device info (no scan)
        connection_output = subprocess.check_output(
            ["nmcli", "-t", "-f", "GENERAL.CONNECTION,GENERAL.STATE", "dev", "show", "wlan0"],
            timeout=_NMCLI_TIMEOUT,
        ).decode("utf-8")  # nosec B603, B607

        # Check if we're connected and get the connection name
        is_connected = False
        connection_name = None
        for line in connection_output.strip().split("\n"):
            if line.startswith("GENERAL.STATE:") and "connected" in line:
                is_connected = True
            elif line.startswith("GENERAL.CONNECTION:"):
                connection_name = line.split(":", 1)[1]

        if not is_connected or not connection_name:
            return False, None, None

        # Get SSID from the connection details (no scan)
        ssid_output = subprocess.check_output(
            ["nmcli", "-t", "-f", "connection.id,802-11-wireless.ssid",
             "connection", "show", connection_name],
            timeout=_NMCLI_TIMEOUT,
        ).decode("utf-8")  # nosec B603, B607

        ssid = connection_name  # Default to connection name
        for line in ssid_output.strip().split("\n"):
            if line.startswith("802-11-wireless.ssid:"):
                found_ssid = line.split(":", 1)[1]
                if found_ssid:
                    ssid = found_ssid
                break

        # Get signal strength using cached data (--rescan no prevents scanning)
        signal_output = subprocess.check_output(
            ["nmcli", "-t", "-m", "tabular", "-f", "IN-USE,SIGNAL",
             "dev", "wifi", "list", "--rescan", "no"],
            timeout=_NMCLI_TIMEOUT,
        ).decode("utf-8")  # nosec B603, B607

        rssi = None
        for line in signal_output.strip().split("\n"):
            if line.startswith("*:"):
                try:
                    rssi = int(line.split(":")[1])
                except (ValueError, IndexError):
                    pass
                break

        # Categorise the signal strength
        rssi_category = categorize_signal_strength(rssi)

        return True, ssid, rssi_category

    except subprocess.TimeoutExpired:
        return False, None, None
    except subprocess.CalledProcessError:
        return False, None, None
    except FileNotFoundError:
        return False, None, None
    except Exception:
        logger.debug("Unexpected WiFi status failure", exc_info=True)
        return False, None, None


def categorize_signal_strength(signal_percentage):
    if signal_percentage is None:
        return 0
    elif signal_percentage < 25:
        return 1
    elif 25 <= signal_percentage < 50:
        return 2
    elif 50 <= signal_percentage < 75:
        return 3
    else:
        return 4


_NMCLI_CONNECT_TIMEOUT = 45  # seconds; association + DHCP can be slow


def _split_terse(line):
    """Split one line of `nmcli -t` output, honouring its \\: and \\\\ escapes."""
    fields, current, escaped = [], [], False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def _nmcli(args, timeout=_NMCLI_TIMEOUT):
    """Run nmcli, returning (ok, output). Output is stderr when it fails."""
    try:
        result = subprocess.run(  # nosec B603, B607
            ["nmcli", *args],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, str(exc)
    output = result.stdout if result.returncode == 0 else result.stderr
    return result.returncode == 0, output.decode("utf-8", "replace").strip()


def scan_networks(rescan=True):
    """List visible WiFi networks, strongest first, one entry per SSID.

    Each entry is a dict with ssid, signal (0-100), secured and in_use.
    Returns an empty list if nmcli fails (no adapter, scan not permitted, ...).
    """
    ok, output = _nmcli(
        ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list",
         "--rescan", "yes" if rescan else "no"],
        timeout=20 if rescan else _NMCLI_TIMEOUT,
    )
    if not ok:
        logger.info(f"WiFi scan failed: {output}")
        return []
    networks = {}
    for line in output.splitlines():
        fields = _split_terse(line)
        if len(fields) < 4 or not fields[1]:
            continue  # hidden networks have no SSID to show
        in_use, ssid, signal, security = fields[:4]
        try:
            signal = int(signal)
        except ValueError:
            signal = 0
        entry = {
            "ssid": ssid,
            "signal": signal,
            "secured": security not in ("", "--"),
            "in_use": in_use == "*",
        }
        previous = networks.get(ssid)
        if previous is None or entry["in_use"] or (
            not previous["in_use"] and signal > previous["signal"]
        ):
            networks[ssid] = entry
    return sorted(
        networks.values(), key=lambda n: (not n["in_use"], -n["signal"], n["ssid"])
    )


def saved_wifi_profiles():
    """Saved WiFi connection profiles, as {name: autoconnect}."""
    ok, output = _nmcli(["-t", "-f", "NAME,TYPE,AUTOCONNECT", "connection", "show"])
    if not ok:
        return {}
    profiles = {}
    for line in output.splitlines():
        fields = _split_terse(line)
        if len(fields) >= 3 and fields[1] == "802-11-wireless":
            profiles[fields[0]] = fields[2] == "yes"
    return profiles


def saved_wifi_connections():
    """Names of saved WiFi connection profiles."""
    return set(saved_wifi_profiles())


def active_wifi_connection():
    """Name of the connection profile wlan0 is using, or None."""
    ok, output = _nmcli(["-t", "-f", "GENERAL.CONNECTION", "device", "show", "wlan0"])
    if not ok:
        return None
    for line in output.splitlines():
        if line.startswith("GENERAL.CONNECTION:"):
            return line.split(":", 1)[1] or None
    return None


def set_wifi_autoconnect(name, enabled):
    """Turn joining a saved network on its own on or off. Returns ok."""
    ok, output = _nmcli(
        ["connection", "modify", "id", name, "connection.autoconnect", "yes" if enabled else "no"]
    )
    if not ok:
        logger.info(f"Setting autoconnect of {name!r} failed: {output}")
    return ok


def forget_wifi(name):
    """Delete a saved network, password included. Returns ok."""
    ok, output = _nmcli(["connection", "delete", "id", name])
    if not ok:
        logger.info(f"Forgetting WiFi network {name!r} failed: {output}")
    return ok


# The stock keyboard's symbol page (keybdA) has curly double quotes but no
# straight one, so typing " on the touch screen sends U+201C / U+201D
_KEYBOARD_LOOKALIKES = str.maketrans({"“": '"', "”": '"'})


def clean_wifi_password(password):
    """Turn touch screen keyboard text into a WiFi password, or None if it can't be one.

    WPA passphrases are printable ASCII (IEEE 802.11i), so a curly quote can only
    mean a straight one. Anything else outside ASCII 32-126 (the keyboard also
    offers characters like the euro sign or an ellipsis) can never match, and
    nmcli would only report it as a wrong password.
    """
    password = password.translate(_KEYBOARD_LOOKALIKES)
    if all(" " <= char <= "~" for char in password):
        return password
    return None


def connect_wifi(ssid, password=None):
    """Connect wlan0 to ssid, returning (ok, message, fallback).

    Without a password nmcli uses the saved profile for that SSID, or joins an
    open network. If a new profile was created and the connection failed (wrong
    password, out of range), it is deleted so it doesn't linger with a bad key.

    nmcli drops the current network to try the new one, so after a failure the
    previous connection is brought back up; fallback is its name when that
    worked, else None.
    """
    previous = active_wifi_connection()
    existed = ssid in saved_wifi_connections()
    args = ["dev", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    args += ["ifname", "wlan0"]
    ok, output = _nmcli(args, timeout=_NMCLI_CONNECT_TIMEOUT)
    if ok:
        return ok, output, None
    logger.info(f"WiFi connect to {ssid!r} failed: {output}")
    if not existed and ssid in saved_wifi_connections():
        _nmcli(["connection", "delete", "id", ssid])
    fallback = None
    if previous and previous != ssid:
        back, back_output = _nmcli(["connection", "up", "id", previous], timeout=_NMCLI_CONNECT_TIMEOUT)
        if back:
            fallback = previous
        else:
            logger.info(f"Reconnecting to {previous!r} failed: {back_output}")
    return ok, output, fallback


def wifi_radio_enabled():
    ok, output = _nmcli(["radio", "wifi"])
    return ok and output == "enabled"


def set_wifi_radio(enabled):
    ok, output = _nmcli(["radio", "wifi", "on" if enabled else "off"])
    if not ok:
        logger.info(f"Switching WiFi {'on' if enabled else 'off'} failed: {output}")
    return ok


def get_wlan0_ip():
    ok, output = _nmcli(["-t", "-f", "IP4.ADDRESS", "dev", "show", "wlan0"])
    if not ok:
        return None
    for line in output.splitlines():
        if line.startswith("IP4.ADDRESS") and ":" in line:
            return line.split(":", 1)[1].split("/")[0] or None
    return None


_WIFI_PERMISSIONS = (
    "org.freedesktop.NetworkManager.wifi.scan",
    "org.freedesktop.NetworkManager.network-control",
    "org.freedesktop.NetworkManager.settings.modify.system",
)


def wifi_permitted():
    """True when NetworkManager lets this user scan for and join networks.

    Needs the polkit rule display.service installs at start; without it nmcli
    answers "auth" (a password prompt nobody can answer) for these actions.
    """
    ok, output = _nmcli(["-t", "-f", "PERMISSION,VALUE", "general", "permissions"])
    if not ok:
        return False
    values = dict(line.rsplit(":", 1) for line in output.splitlines() if ":" in line)
    return all(values.get(permission) == "yes" for permission in _WIFI_PERMISSIONS)
