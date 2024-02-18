from src.communicator import DisplayCommunicator
from src.mapping import Mapper, MappingLeaf, build_accessor, build_format_filename, PAGE_MAIN, PAGE_FILES, PAGE_PREPARE_MOVE, PAGE_PREPARE_TEMP, PAGE_PREPARE_EXTRUDER, PAGE_SETTINGS, PAGE_SETTINGS_LANGUAGE, PAGE_SETTINGS_TEMPERATURE, PAGE_SETTINGS_TEMPERATURE_SET, PAGE_SETTINGS_ABOUT, PAGE_SETTINGS_ADVANCED, PAGE_LEVELING, PAGE_LEVELING_SCREW_ADJUST, PAGE_LEVELING_Z_OFFSET_ADJUST, PAGE_CONFIRM_PRINT, PAGE_PRINTING, PAGE_PRINTING_KAMP, PAGE_PRINTING_PAUSE, PAGE_PRINTING_STOP, PAGE_PRINTING_EMERGENCY_STOP, PAGE_PRINTING_COMPLETE, PAGE_PRINTING_FILAMENT, PAGE_PRINTING_SPEED, PAGE_PRINTING_ADJUST, PAGE_PRINTING_FILAMENT_RUNOUT, PAGE_PRINTING_DIALOG_SPEED, PAGE_PRINTING_DIALOG_FAN, PAGE_PRINTING_DIALOG_FLOW, PAGE_OVERLAY_LOADING, PAGE_LIGHTS, format_temp, format_time, format_percent
from src.colors import BACKGROUND_GRAY, TEXT_WARNING


class ElegooDisplayMapper(Mapper):
    page_mapping = {
        PAGE_MAIN: "1",
        PAGE_FILES: "2",
        PAGE_PREPARE_MOVE: "8",
        PAGE_PREPARE_TEMP: "95",
        PAGE_PREPARE_EXTRUDER: "9",
        PAGE_SETTINGS: "11",
        PAGE_SETTINGS_LANGUAGE: "12",
        PAGE_SETTINGS_TEMPERATURE: "32",
        PAGE_SETTINGS_TEMPERATURE_SET: "33",
        PAGE_SETTINGS_ABOUT: "35",
        PAGE_SETTINGS_ADVANCED: "42",
        PAGE_LEVELING: "3",
        PAGE_LEVELING_SCREW_ADJUST: "94",
        PAGE_LEVELING_Z_OFFSET_ADJUST: "137",
        PAGE_CONFIRM_PRINT: "18",
        PAGE_PRINTING: "19",
        PAGE_PRINTING_KAMP: "104",
        PAGE_PRINTING_PAUSE: "25",
        PAGE_PRINTING_STOP: "26",
        PAGE_PRINTING_EMERGENCY_STOP: "106",
        PAGE_PRINTING_COMPLETE: "24",
        PAGE_PRINTING_FILAMENT: "28",
        PAGE_PRINTING_SPEED: "135",
        PAGE_PRINTING_ADJUST: "127",
        PAGE_PRINTING_FILAMENT_RUNOUT: "22",
        PAGE_PRINTING_DIALOG_SPEED: "86",
        PAGE_PRINTING_DIALOG_FAN: "87",
        PAGE_PRINTING_DIALOG_FLOW: "85",
        PAGE_OVERLAY_LOADING: "130",
        PAGE_LIGHTS: "84",
    }

    def __init__(self) -> None:
        super().__init__()
        self.data_mapping = {
            "extruder": {
                "temperature": [
                    MappingLeaf(
                        [
                            build_accessor(self.map_page(PAGE_MAIN), "nozzletemp"),
                            build_accessor(
                                self.map_page(PAGE_PREPARE_TEMP), "nozzletemp"
                            ),
                            build_accessor(
                                self.map_page(PAGE_PREPARE_EXTRUDER), "nozzletemp"
                            ),
                            build_accessor(self.map_page(PAGE_PRINTING), "nozzletemp"),
                            build_accessor(self.map_page(PAGE_PRINTING_KAMP), "b[3]"),
                            build_accessor(
                                self.map_page(PAGE_PRINTING_FILAMENT), "nozzletemp"
                            ),
                        ],
                        formatter=format_temp,
                    )
                ],
                "target": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PREPARE_TEMP), 17)],
                        formatter=lambda x: f"{x:.0f}",
                    )
                ],
            },
            "heater_bed": {
                "temperature": [
                    MappingLeaf(
                        [
                            build_accessor(self.map_page(PAGE_MAIN), "bedtemp"),
                            build_accessor(self.map_page(PAGE_PREPARE_TEMP), "bedtemp"),
                            build_accessor(
                                self.map_page(PAGE_PREPARE_EXTRUDER), "bedtemp"
                            ),
                            build_accessor(self.map_page(PAGE_PRINTING), "bedtemp"),
                            build_accessor(self.map_page(PAGE_PRINTING_KAMP), "b[2]"),
                            build_accessor(
                                self.map_page(PAGE_PRINTING_FILAMENT), "bedtemp"
                            ),
                        ],
                        formatter=format_temp,
                    )
                ],
                "target": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PREPARE_TEMP), 18)],
                        formatter=lambda x: f"{x:.0f}",
                    )
                ],
            },
            "motion_report": {
                "live_position": {
                    0: [
                        MappingLeaf(
                            [build_accessor(self.map_page(PAGE_MAIN), "x_pos")]
                        ),
                        MappingLeaf(
                            [build_accessor(self.map_page(PAGE_PRINTING), "x_pos")],
                            formatter=lambda x: f"X[{x:3.2f}]",
                        ),
                    ],
                    1: [
                        MappingLeaf(
                            [build_accessor(self.map_page(PAGE_MAIN), "y_pos")]
                        ),
                        MappingLeaf(
                            [build_accessor(self.map_page(PAGE_PRINTING), "y_pos")],
                            formatter=lambda y: f"Y[{y:3.2f}]",
                        ),
                    ],
                    2: [
                        MappingLeaf([build_accessor(self.map_page(PAGE_MAIN), "z_pos")])
                    ],
                },
                "live_velocity": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PRINTING), "pressure_val")],
                        formatter=lambda x: f"{x:3.2f}mm/s",
                    )
                ],
            },
            "print_stats": {
                "print_duration": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PRINTING), "6")],
                        formatter=format_time,
                    )
                ],
                "filename": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PRINTING), "t0")],
                        formatter=build_format_filename("printing"),
                    )
                ],
            },
            "gcode_move": {
                "extrude_factor": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PRINTING), "flow_speed")],
                        formatter=format_percent,
                    ),
                    MappingLeaf(
                        [
                            build_accessor(
                                self.map_page(PAGE_PRINTING_DIALOG_FLOW), "b[3]"
                            ),
                            build_accessor(
                                self.map_page(PAGE_PRINTING_DIALOG_FLOW), "b[6]"
                            ),
                        ],
                        field_type="val",
                        formatter=lambda x: f"{x * 100:.0f}",
                    ),
                ],
                "speed_factor": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PRINTING), "printspeed")],
                        formatter=format_percent,
                    ),
                    MappingLeaf(
                        [
                            build_accessor(
                                self.map_page(PAGE_PRINTING_DIALOG_SPEED), "b[3]"
                            ),
                            build_accessor(
                                self.map_page(PAGE_PRINTING_DIALOG_SPEED), "b[6]"
                            ),
                        ],
                        field_type="val",
                        formatter=lambda x: f"{x * 100:.0f}",
                    ),
                ],
                "homing_origin": {
                    2: [
                        MappingLeaf(
                            [build_accessor(self.map_page(PAGE_PRINTING_ADJUST), "15")],
                            formatter=lambda x: f"{x:.3f}",
                        )
                    ],
                },
            },
            "fan": {
                "speed": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PRINTING), "fanspeed")],
                        formatter=format_percent,
                    ),
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_SETTINGS), "12")],
                        field_type="pic",
                        formatter=lambda x: "77" if int(x) == 1 else "76",
                    ),
                ]
            },
            "display_status": {
                "progress": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PRINTING), "printvalue")],
                        formatter=lambda x: f"{x * 100:2.0f}%",
                    ),
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PRINTING), "printprocess")],
                        field_type="val",
                        formatter=lambda x: f"{x * 100:.0f}",
                    ),
                ]
            },
            "output_pin Part_Light": {
                "value": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_LIGHTS), "led1")],
                        field_type="pic",
                        formatter=lambda x: "77" if int(x) == 1 else "76",
                    )
                ]
            },
            "output_pin Frame_Light": {
                "value": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_LIGHTS), "led2")],
                        field_type="pic",
                        formatter=lambda x: "77" if int(x) == 1 else "76",
                    )
                ]
            },
            "filament_switch_sensor fila": {
                "enabled": [
                    MappingLeaf(
                        [
                            build_accessor(self.map_page(PAGE_SETTINGS), "11"),
                            build_accessor(self.map_page(PAGE_PRINTING_ADJUST), "16"),
                        ],
                        field_type="pic",
                        formatter=lambda x: "77" if int(x) == 1 else "76",
                    )
                ]
            },
        }

    def set_z_display(self, value):
        if value == "mm":
            self.data_mapping["motion_report"]["live_position"][2] = [
                MappingLeaf(
                    [
                        build_accessor(self.map_page(PAGE_MAIN), "z_pos"),
                        build_accessor(self.map_page(PAGE_PRINTING), "zvalue"),
                    ]
                )
            ]
        elif value == "layer":
            self.data_mapping["print_stats"]["info"] = {
                "current_layer": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PRINTING), "zvalue")],
                        required_fields=[["print_stats", "info", "total_layer"]],
                        formatter=lambda current, total: f"{current:.0f}/{total:.0f}" if current is not None and total is not None else '0/0',
                    )
                ],
                "total_layer": [MappingLeaf([])],
            }


class ElegooDisplayCommunicator(DisplayCommunicator):
    supported_firmware_versions = ["1.2.11", "1.2.12"]

    async def get_firmware_version(self) -> str:
        return await self.display.get("p[35].b[11].txt", self.timeout)

    async def check_valid_version(self):
        is_valid = await super().check_valid_version()
        if not is_valid:
            await self.write(
                f'xstr 0,464,320,16,2,{TEXT_WARNING},{BACKGROUND_GRAY},1,1,1,"WARNING: Unsupported Display Firmware Version"'
            )
