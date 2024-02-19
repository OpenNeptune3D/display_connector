import subprocess  # nosec

def get_wlan0_status():
    try:
        # Get the SSID
        ssid_output = subprocess.check_output(['nmcli', '-t', '-f', 'active,ssid', 'dev', 'wifi']).decode('utf-8')  # nosec B603, B607
        if len(ssid_output) == 0:
            return False, None, None
        ssid = None
        for line in ssid_output.strip().split('\n'):
            if line.startswith('yes:'):
                ssid = line.split(':')[1]
                break

        # Get the signal strength
        rssi_output = subprocess.check_output(['nmcli', '-f', 'in-use,signal', '-t', 'dev', 'wifi']).decode('utf-8')  # nosec B603, B607
        rssi = None
        for line in rssi_output.strip().split('\n'):
            if line.startswith('*:'):
                rssi = int(line.split(':')[1])  # Convert the string to an integer
                break

        # Categorize the signal strength
        rssi_category = categorize_signal_strength(rssi)

        return True, ssid, rssi_category

    except subprocess.CalledProcessError:
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
