import re
import time

PAGE_MAIN = "main"
PAGE_FILES = "files"
PAGE_SHUTDOWN_DIALOG = "shutdown_dialog"

PAGE_PREPARE_MOVE = "prepare_move"
PAGE_PREPARE_TEMP = "prepare_temp"
PAGE_PREPARE_EXTRUDER = "prepare_extruder"

PAGE_SETTINGS = "settings"
PAGE_SETTINGS_LANGUAGE = "settings_language"
PAGE_SETTINGS_TEMPERATURE = "settings_temperature"
PAGE_SETTINGS_TEMPERATURE_SET = "settings_temperature_set"
PAGE_SETTINGS_ABOUT = "settings_about"
PAGE_SETTINGS_ADVANCED = "settings_advanced"


PAGE_CONFIRM_PRINT = "confirm_print"
PAGE_PRINTING = "printing"
PAGE_PRINTING_KAMP = "printing_kamp"
PAGE_PRINTING_PAUSE = "printing_pause"
PAGE_PRINTING_STOP = "printing_stop"
PAGE_PRINTING_EMERGENCY_STOP = "printing_emergency_stop"
PAGE_PRINTING_COMPLETE = "printing_complete"
PAGE_PRINTING_FILAMENT = "printing_filament"
PAGE_PRINTING_SPEED = "printing_speed"
PAGE_PRINTING_ADJUST = "printing_adjust"
PAGE_PRINTING_FILAMENT_RUNOUT = "printing_filament_runout"
PAGE_PRINTING_DIALOG_SPEED = "printing_dialog_speed"
PAGE_PRINTING_DIALOG_FAN = "printing_dialog_fan"
PAGE_PRINTING_DIALOG_FLOW = "printing_dialog_flow"

PAGE_LEVELING = "leveling"
PAGE_LEVELING_SCREW_ADJUST = "leveling_screw_adjust"
PAGE_LEVELING_Z_OFFSET_ADJUST = "leveling_z_offset_adjust"

PAGE_OVERLAY_LOADING = "overlay_loading"

PAGE_LIGHTS = "lights"


def format_temp(value):
    if value is None:
        return "N/A"
    return f"{value:3.1f}°C"


def format_time(seconds):
    if seconds is None:
        return "N/A"
    if seconds < 3600:
        return time.strftime("%Mm %Ss", time.gmtime(seconds))
    return time.strftime("%Hh %Mm", time.gmtime(seconds))


def format_percent(value):
    if value is None:
        return "N/A"
    return f"{value * 100:2.0f}%"


# This attempts to strip the printer definition, the time estimate and the file extension from the filename
filename_regex_wrapper = {
    "default": re.compile(r"(.*)_.*?_(?:[0-9]+h|[0-9]+m|[0-9]+s)+\.gcode"),
    "printing": re.compile(r"(.*)_.*?_.*?_.*?_(?:[0-9]+h|[0-9]+m|[0-9]+s)+\.gcode"),
}


def build_format_filename(context=None):
    def format_filename(filename):
        filename = filename.split("/")[-1]
        match = filename_regex_wrapper[context if context else "default"].match(
            filename
        )
        if match is not None:
            return match.group(1)
        return filename.replace(".gcode", "")

    return format_filename


class MappingLeaf:
    def __init__(self, fields, field_type="txt", required_fields=None, formatter=None):
        self.fields = fields
        self.field_type = field_type
        self.required_fields = required_fields
        self.formatter = formatter

    def format(self, value):
        if self.formatter is not None:
            return self.formatter(value)
        if isinstance(value, float):
            return f"{value:3.2f}"
        return str(value)

    def format_with_required(self, value, *required_values):
        if self.formatter is not None:
            return self.formatter(value, *required_values)
        if isinstance(value, float):
            return f"{value:3.2f}"
        return str(value)


def build_accessor(page, field):
    accessor = ""
    try:
        page_number = int(page)
        accessor += f"p[{page_number}]"
    except ValueError:
        accessor += page
    accessor += "."
    try:
        field_number = int(field)
        accessor += f"b[{field_number}]"
    except ValueError:
        accessor += field
    return accessor


class Mapper:
    data_mapping = {}
    page_mapping = {}

    def map_page(self, page):
        if page in self.page_mapping:
            return self.page_mapping[page]
        return None
