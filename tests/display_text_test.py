import pytest

from src.display_text import DisplayEncodingError, ascii_display_command


@pytest.mark.parametrize('before,after', [
    ('main.t.txt="265.0°C"', 'main.t.txt="265.0 C"'),
    ('main.t.txt="−5°C / 32°F"', 'main.t.txt="-5 C / 32 F"'),
    ('main.t.txt="pièce_été.gcode"', 'main.t.txt="piece_ete.gcode"'),
    ('main.t.txt="pie\u0300ce"', 'main.t.txt="piece"'),
    ('main.t.txt="cœur / Straße / æ / Ø / ł"', 'main.t.txt="coeur / Strasse / ae / O / l"'),
    ('main.t.txt="90° → prêt…"', 'main.t.txt="90 deg -> pret..."'),
    ('main.t.txt="中文🙂"', 'main.t.txt="???"'),
    ('main.t.txt="a\u00a0b\u2028c"', 'main.t.txt="a b c"'),
    ('main.t.txt="a\u200db"', 'main.t.txt="ab"'),
    ('main.t.txt="＂é＼"', 'main.t.txt="?e?"'),
    ('xstr 0,0,100,20,1,0,0,1,1,1,"Écran prêt"', 'xstr 0,0,100,20,1,0,0,1,1,1,"Ecran pret"'),
    ('main.t.txt="«test»"', 'main.t.txt="\'test\'"'),
    ('main.t.txt="N/A"', 'main.t.txt="N/A"'),
    ('page 1', 'page 1'),
    ('n0.val=265', 'n0.val=265'),
    ('cp0.write("ABcd09+/=~<>")', 'cp0.write("ABcd09+/=~<>")'),
    (r'main.t.txt="a\"b"', r'main.t.txt="a\"b"'),
    (r'main.t.txt="é\"b"', r'main.t.txt="e\"b"'),
])
def test_ascii_display_commands(before, after):
    assert ascii_display_command(before) == after
    assert after.isascii()
    assert ascii_display_command(after) == after


@pytest.mark.parametrize('command', [
    'pâge 1', 'main.été.txt="valid"', 'n0.val=−5',
    'main.t.txt="unterminated é',
])
def test_non_ascii_syntax_is_not_silently_changed(command):
    with pytest.raises(DisplayEncodingError):
        ascii_display_command(command)
