"""Minimal sd_notify(3): report service state to systemd without libsystemd.

Replaces systemd-python, which has to be compiled against libsystemd-dev and
broke Moonraker updates on printers missing the build dependencies.
"""

import os
import socket


def notify(state):
    """Send a state string such as "READY=1" or "WATCHDOG=1" to systemd.

    Returns False when not running under systemd or the message can't be sent.
    """
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return False
    if address[0] == "@":  # abstract namespace socket
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(state.encode())
    except OSError:
        return False
    return True
