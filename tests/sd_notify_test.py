import os
import socket

from src import sd_notify


def test_notify_without_systemd(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert sd_notify.notify("READY=1") is False


def test_notify_sends_state(monkeypatch, tmp_path):
    path = str(tmp_path / "notify.sock")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind(path)
        monkeypatch.setenv("NOTIFY_SOCKET", path)
        assert sd_notify.notify("WATCHDOG=1") is True
        assert server.recv(64) == b"WATCHDOG=1"


def test_notify_abstract_socket(monkeypatch):
    name = f"display-connector-test-{os.getpid()}"
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as server:
        server.bind("\0" + name)
        monkeypatch.setenv("NOTIFY_SOCKET", "@" + name)
        assert sd_notify.notify("READY=1") is True
        assert server.recv(64) == b"READY=1"


def test_notify_unreachable_socket(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "missing.sock"))
    assert sd_notify.notify("STOPPING=1") is False
