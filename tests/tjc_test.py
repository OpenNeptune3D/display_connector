from src.tjc import TJCProtocol


def test_is_event():
    protocol = TJCProtocol(None)
    assert protocol.is_event(b"\x65") is True
    assert protocol.is_event(b"\x71") is False
    assert protocol.is_event(b"\x72") is True
