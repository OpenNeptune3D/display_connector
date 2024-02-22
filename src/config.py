import os
from configparser import ConfigParser

TEMP_DEFAULTS = {
    "pla": [210, 60],
    "abs": [240, 110],
    "petg": [240, 80],
    "tpu": [240, 60],
}


class ConfigHandler(ConfigParser):
    def __init__(self, file_path, logger):
        self.file_path = file_path
        self.logger = logger
        super().__init__(allow_no_value=True)
        self.initialize_config_file()
        self.reload_config()

    @property
    def file(self):
        return self.file_path

    def reload_config(self):
        self.read(self.file_path)

    def write_changes(self):
        with open(self.file_path, "w") as configfile:
            self.write(configfile)

    def safe_get(self, section, key, default=None):
        try:
            return self.get(section, key)
        except:
            return default

    def initialize_config_file(self):
        if not os.path.exists(self.file_path):
            self.logger.info("Creating config file")
            self.add_section("general")
            self.set(
                "general",
                "clean_filename_regex",
                ".*_(.*?_(?:[0-9]+h|[0-9]+m|[0-9]+s)+\.gcode)",
            )
            self.add_section("LOGGING")
            self.set("LOGGING", "file_log_level", "ERROR")

            self.add_section("files")
            self.set("files", "sort_by", "modified")
            self.set("files", "sort_order", "desc")
            self.set("files", "sort_folders_first", "true")

            self.add_section("main_screen")
            self.set(
                "main_screen",
                "; set to MODEL_NAME for built in model name. Remove to use Elegoo model images.",
            )
            self.set("main_screen", "display_name", "MODEL_NAME")
            self.set(
                "main_screen",
                "; color for the line below the model name. As RGB565 value.",
            )
            self.set("main_screen", "display_name_line_color", "1725")

            self.add_section("print_screen")
            self.set("print_screen", "z_display", "mm")

            self.add_section("thumbnails")
            self.set(
                "main_screen",
                "; Background color for thumbnails. As RGB Hex value. Remove for default background color.",
            )
            self.set("thumbnails", "background_color", "29354a")

            self.add_section("temperatures.pla")
            self.set("temperatures.pla", "extruder", str(TEMP_DEFAULTS["pla"][0]))
            self.set("temperatures.pla", "heater_bed", str(TEMP_DEFAULTS["pla"][1]))
            self.add_section("temperatures.petg")
            self.set("temperatures.petg", "extruder", str(TEMP_DEFAULTS["petg"][0]))
            self.set("temperatures.petg", "heater_bed", str(TEMP_DEFAULTS["petg"][1]))
            self.add_section("temperatures.abs")
            self.set("temperatures.abs", "extruder", str(TEMP_DEFAULTS["abs"][0]))
            self.set("temperatures.abs", "heater_bed", str(TEMP_DEFAULTS["abs"][1]))
            self.add_section("temperatures.tpu")
            self.set("temperatures.tpu", "extruder", str(TEMP_DEFAULTS["tpu"][0]))
            self.set("temperatures.tpu", "heater_bed", str(TEMP_DEFAULTS["tpu"][1]))

            self.add_section("prepare")
            self.set("prepare", "move_distance", "1")
            self.set("prepare", "xy_move_speed", "130")
            self.set("prepare", "z_move_speed", "10")
            self.set("prepare", "extrude_amount", "10")
            self.set("prepare", "extrude_speed", "5")

            with open(self.file_path, "w") as configfile:
                self.write(configfile)
