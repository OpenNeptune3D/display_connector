import subprocess  # nosec


def get_wlan0_status():
    """
    Get WiFi status without triggering a scan by using cached data.
    This is much lighter on the hardware.
    """
    try:
        # Get connection name and state from device info (no scan)
        connection_output = subprocess.check_output(
            ["nmcli", "-t", "-f", "GENERAL.CONNECTION,GENERAL.STATE", "dev", "show", "wlan0"]
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
             "connection", "show", connection_name]
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
             "dev", "wifi", "list", "--rescan", "no"]
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

    except subprocess.CalledProcessError:
        return False, None, None
    except FileNotFoundError:
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
