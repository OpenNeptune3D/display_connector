from src.mapping import format_temp, format_time, format_percent, build_format_filename, build_accessor

def test_format_temp():
    assert format_temp(25.5) == "25.5°C"

def test_format_temp_none():
    assert format_temp(None) == "N/A"

def test_format_time():
    assert format_time(3660) == "01h 01m"
    assert format_time(60) == "01m 00s"
    assert format_time(59) == "00m 59s"
    assert format_time(3600) == "01h 00m"
    assert format_time(None) == "N/A"

def test_format_percent():
    assert format_percent(0.5) == "50%"
    assert format_percent(0.123) == "12%"
    assert format_percent(1) == "100%"
    assert format_percent(None) == "N/A"

def test_format_default_filename():
    format_filename = build_format_filename()
    assert format_filename("test.gcode") == "test"
    assert format_filename("test_pla_0.2mm_printer_1h.gcode") == "test_pla_0.2mm"

def test_format_printing_filename():
    format_filename = build_format_filename("printing")
    assert format_filename("test.gcode") == "test"
    assert format_filename("test_pla_0.2mm_printer_1h.gcode") == "test"
    assert format_filename("test_pla_0.2mm_printer_1m.gcode") == "test"
    assert format_filename("test_pla_0.2mm_printer_1s.gcode") == "test"
    assert format_filename("test_pla_0.2mm_printer_1h1m1s.gcode") == "test"

def test_build_accessor():
    assert build_accessor(5, 0) == "p[5].b[0]"
    assert build_accessor(10, "test") == "p[10].test"
    assert build_accessor("test", 0) == "test.b[0]"
    assert build_accessor("testp", "testm") == "testp.testm"