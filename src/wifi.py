import subprocess

def get_wlan0_status():
    try:
        # Get the SSID
        ssid_output = subprocess.check_output(
            ['nmcli', '-t', '-f', 'active,ssid', 'dev', 'wifi']).decode('utf-8')
        if len(ssid_output) == 0:
            return False, None, None
        ssid = None
        for line in ssid_output.strip().split('\n'):
            if line.startswith('yes:'):
                ssid = line.split(':')[1]
                break

        # Get the signal strength
        rssi_output = subprocess.check_output(
            ['nmcli', '-f', 'in-use,signal', '-t', 'dev', 'wifi']).decode('utf-8')
        rssi = None
        for line in rssi_output.strip().split('\n'):
            if line.startswith('*:'):
                rssi = line.split(':')[1]
                break

        return True, ssid, rssi

    except subprocess.CalledProcessError:
        return False, None, None

def categorize_signal_strength(signal_dbm):
    if signal_dbm is None:
        return 0
    elif signal_dbm < -70:
        return 1
    elif -70 <= signal_dbm < -60:
        return 2
    elif -60 <= signal_dbm < -50:
        return 3
    else:
        return 4