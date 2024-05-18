from src.mapping import (
    PAGE_PREPARE_MOVE,
    PAGE_PREPARE_TEMP,
    PAGE_PREPARE_EXTRUDER,
    PAGE_SETTINGS,
    PAGE_SETTINGS_LANGUAGE,
    PAGE_SETTINGS_TEMPERATURE,
    PAGE_SETTINGS_ABOUT,
    PAGE_SETTINGS_ADVANCED,
    PAGE_LEVELING,
    PAGE_LEVELING_SCREW_ADJUST,
    PAGE_LEVELING_Z_OFFSET_ADJUST,
    PAGE_PRINTING_STOP,
    PAGE_PRINTING_EMERGENCY_STOP,
    PAGE_PRINTING_FILAMENT,
    PAGE_PRINTING_SPEED,
    PAGE_PRINTING_ADJUST,
    PAGE_PRINTING_DIALOG_SPEED,
    PAGE_PRINTING_DIALOG_FLOW,
    PAGE_LIGHTS,
    PAGE_SHUTDOWN_DIALOG,
)

response_actions = {
    # Main
    1: {
        1: "files_picker",
        2: "page " + PAGE_PREPARE_MOVE,
        3: "page " + PAGE_SETTINGS,
        4: "page " + PAGE_LEVELING,
    },
    # File Picker
    2: {
        2: "files_page_next",
        1: "files_page_prev",
        7: "open_file_0",
        8: "open_file_1",
        9: "open_file_2",
        10: "open_file_3",
        11: "open_file_4",
    },
    # Level Picker
    3: {
        7: "page " + PAGE_LEVELING_SCREW_ADJUST,
        8: "page " + PAGE_LEVELING_Z_OFFSET_ADJUST,
        9: "begin_full_bed_level",
    },
    # Prepare Temperature (Pro Only)
    6: {
        1: "printer.send_gcode('SET_HEATER_TEMPERATURE HEATER=extruder')",
        2: "printer.send_gcode('SET_HEATER_TEMPERATURE HEATER=heater_bed')",
        3: "set_preset_temp_PLA",
        4: "set_preset_temp_ABS",
        5: "set_preset_temp_PETG",
        6: "set_preset_temp_TPU",
        7: "page " + PAGE_PREPARE_MOVE,
        8: "page " + PAGE_PREPARE_EXTRUDER,
        9: "printer.send_gcode('SET_HEATER_TEMPERATURE HEATER=heater_bed_outer')",
    },
    # Prepare Move
    8: {
        1: "set_distance_0.1",
        2: "set_distance_1",
        3: "set_distance_10",
        4: "printer.send_gcode('G28 X')",
        5: "printer.send_gcode('G28 Y')",
        6: "move_z_+",
        7: "move_y_-",
        8: "move_x_+",
        9: "move_x_-",
        10: "move_y_+",
        11: "move_z_-",
        12: "printer.send_gcode('G28')",
        13: "printer.send_gcode('G28 Z')",
        14: "printer.send_gcode('M84')",
        15: "page " + PAGE_PREPARE_TEMP,
        16: "page " + PAGE_PREPARE_EXTRUDER,
    },
    # Prepare Extruder
    9: {
        1: "extrude_+",
        2: "extrude_-",
        3: "page " + PAGE_PREPARE_MOVE,
        4: "page " + PAGE_PREPARE_TEMP,
    },
    # Settings
    11: {
        1: "page " + PAGE_SETTINGS_LANGUAGE,
        2: "page " + PAGE_SETTINGS_TEMPERATURE,
        3: "page " + PAGE_LIGHTS,
        4: "toggle_fan",
        5: "printer.send_gcode('M84')",
        6: "toggle_filament_sensor",
        8: "page " + PAGE_SETTINGS_ABOUT,
        9: "page " + PAGE_SETTINGS_ADVANCED,
    },
    # Confirm Print
    18: {0: "print_opened_file", 1: "go_back"},
    # Printing
    19: {
        0: "page " + PAGE_PRINTING_FILAMENT,
        1: "pause_print_button",
        2: "page " + PAGE_PRINTING_STOP,
        3: "page " + PAGE_LIGHTS,
        4: "page " + PAGE_PRINTING_EMERGENCY_STOP,
        5: "page " + PAGE_PRINTING_DIALOG_FLOW,
        6: "page " + PAGE_PRINTING_DIALOG_SPEED,
    },
    # Print Completed
    24: {
        0: "confirm_complete",
        1: "print_opened_file",
    },
    # Confirm Pause
    25: {0: "pause_print_confirm", 1: "go_back"},
    # Confirm Stop
    26: {0: "stop_print", 1: "go_back"},
    # Printing Temp (4 Pro only)
    27: {
        1: "temp_heater_extruder",
        2: "temp_heater_heater_bed",
        3: "temp_increment_1",
        4: "temp_increment_5",
        5: "temp_increment_10",
        6: "temp_adjust_-",
        7: "temp_adjust_+",
        8: "temp_reset",
        9: "temp_heater_heater_bed_outer",
        12: "page " + PAGE_PRINTING_SPEED,
        13: "page " + PAGE_PRINTING_ADJUST,
    },
    # Printing Temp
    28: {
        1: "temp_heater_extruder",
        2: "temp_heater_heater_bed",
        3: "temp_increment_1",
        4: "temp_increment_5",
        5: "temp_increment_10",
        6: "temp_adjust_-",
        7: "temp_adjust_+",
        8: "temp_reset",
        12: "page " + PAGE_PRINTING_SPEED,
        13: "page " + PAGE_PRINTING_ADJUST,
    },
    # Settings Temperature
    32: {
        1: "start_temp_preset_pla",
        2: "start_temp_preset_abs",
        3: "start_temp_preset_petg",
        4: "start_temp_preset_tpu",
    },
    # Settings Temperature Set
    33: {
        0: "save_temp_preset",
        1: "preset_temp_step_1",
        2: "preset_temp_step_5",
        3: "preset_temp_step_10",
        4: "preset_temp_extruder_down",
        5: "preset_temp_extruder_up",
        6: "preset_temp_bed_down",
        7: "preset_temp_bed_up",
    },
    # Lights Page
    84: {
        1: "toggle_part_light",
        2: "toggle_frame_light",
    },
    # Printing Speed dialog
    86: {
        1: "",
    },
    # Leveling Screws
    94: {5: "retry_screw_leveling"},
    # Prepare Temperature
    95: {
        1: "printer.send_gcode('SET_HEATER_TEMPERATURE HEATER=extruder')",
        2: "printer.send_gcode('SET_HEATER_TEMPERATURE HEATER=heater_bed')",
        3: "set_preset_temp_PLA",
        4: "set_preset_temp_ABS",
        5: "set_preset_temp_PETG",
        6: "set_preset_temp_TPU",
        7: "page " + PAGE_PREPARE_MOVE,
        8: "page " + PAGE_PREPARE_EXTRUDER,
    },
    # Confirm Emergency Stop
    106: {0: "emergency_stop", 1: "go_back"},
    # Printing Adjust
    127: {
        1: "zoffsetchange_0.01",
        2: "zoffsetchange_0.1",
        3: "zoffsetchange_1",
        4: "zoffset_+",
        5: "zoffset_-",
        7: "page " + PAGE_LIGHTS,
        8: "toggle_filament_sensor",
        9: "page " + PAGE_PRINTING_FILAMENT,
        10: "page " + PAGE_PRINTING_SPEED,
    },
    # Printing Speed
    135: {
        1: "speed_type_print",
        2: "speed_type_flow",
        3: "speed_type_fan",
        4: "speed_increment_1",
        5: "speed_increment_5",
        6: "speed_increment_10",
        7: "speed_adjust_-",
        8: "speed_adjust_+",
        9: "speed_reset",
        12: "page " + PAGE_PRINTING_FILAMENT,
        13: "page " + PAGE_PRINTING_ADJUST,
    },
    # Leveling Z Offset
    137: {
        0: "abort_zprobe",
        1: "zprobe_step_0.01",
        2: "zprobe_step_0.1",
        3: "zprobe_step_1",
        5: "zprobe_+",
        6: "zprobe_-",
        7: "save_zprobe",
    },
}

input_actions = {
    # Prepare Temp (4 Pro only)
    6: {
        0: "set_temp_extruder_$",
        1: "set_temp_heater_bed_$",
        10: "set_temp_heater_bed_outer_$",
    },
    # Prepare Extruder
    9: {
        2: "set_extrude_amount_$",
        3: "set_extrude_speed_$",
    },
    # Printing Temperature
    85: {
        1: "set_flow_$",
    },
    # Printing Speed
    86: {
        1: "set_speed_$",
    },
    # Prepare Temp
    95: {
        0: "set_temp_extruder_$",
        1: "set_temp_heater_bed_$",
    },
}

custom_touch_actions = {
    "main": {
        (200, 0, 260, 50): "page " + PAGE_SHUTDOWN_DIALOG,
    },
    "shutdown_dialog": {
        (24, 104, 248, 154): "shutdown_host",
        (24, 158, 248, 208): "reboot_host",
        (24, 212, 248, 262): "reboot_klipper",
        (0, 0, 272, 480): "go_back",
    },
    "printing_kamp": {(40, 400, 230, 450): "save_config"},
}
