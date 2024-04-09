from src.tjc import TJCProtocol

def test_is_ecent():
    protocol = TJCProtocol(None)
    assert protocol.is_event(b"\x65") == True
    assert protocol.is_event(b"\x71") == False
    assert protocol.is_event(b"\x72") == True