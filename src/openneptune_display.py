from src.elegoo_display import ElegooDisplayCommunicator
from src.mapping import (
    Mapper,
    MappingLeaf,
    build_accessor,
    build_format_filename,
    PAGE_MAIN,
    PAGE_FILES,
    PAGE_PREPARE_MOVE,
    PAGE_PREPARE_TEMP,
    PAGE_PREPARE_EXTRUDER,
    PAGE_SETTINGS,
    PAGE_SETTINGS_LANGUAGE,
    PAGE_SETTINGS_TEMPERATURE,
    PAGE_SETTINGS_TEMPERATURE_SET,
    PAGE_SETTINGS_ABOUT,
    PAGE_SETTINGS_ADVANCED,
    PAGE_LEVELING,
    PAGE_LEVELING_SCREW_ADJUST,
    PAGE_LEVELING_Z_OFFSET_ADJUST,
    PAGE_CONFIRM_PRINT,
    PAGE_PRINTING,
    PAGE_PRINTING_KAMP,
    PAGE_PRINTING_PAUSE,
    PAGE_PRINTING_STOP,
    PAGE_PRINTING_EMERGENCY_STOP,
    PAGE_PRINTING_COMPLETE,
    PAGE_PRINTING_FILAMENT,
    PAGE_PRINTING_SPEED,
    PAGE_PRINTING_ADJUST,
    PAGE_PRINTING_FILAMENT_RUNOUT,
    PAGE_PRINTING_DIALOG_SPEED,
    PAGE_PRINTING_DIALOG_FAN,
    PAGE_PRINTING_DIALOG_FLOW,
    PAGE_OVERLAY_LOADING,
    PAGE_LIGHTS,
    PAGE_SHUTDOWN_DIALOG,
    format_temp,
    format_time,
    format_percent,
)
from src.colors import (
    BACKGROUND_DIALOG,
    BACKGROUND_GRAY,
)


class OpenNeptuneDisplayMapper(Mapper):
    page_mapping = {
        PAGE_MAIN: "main",
        PAGE_FILES: "file1",
        PAGE_SHUTDOWN_DIALOG: "none_9",
        PAGE_PREPARE_MOVE: "premove",
        PAGE_PREPARE_TEMP: "pretemp",
        PAGE_PREPARE_EXTRUDER: "prefilament",
        PAGE_SETTINGS: "set",
        PAGE_SETTINGS_LANGUAGE: "language",
        PAGE_SETTINGS_TEMPERATURE: "tempset",
        PAGE_SETTINGS_TEMPERATURE_SET: "tempsetvalue",
        PAGE_SETTINGS_ABOUT: "information",
        PAGE_SETTINGS_ADVANCED: "multiset",
        PAGE_LEVELING: "file2",
        PAGE_LEVELING_SCREW_ADJUST: "assist_level",
        PAGE_LEVELING_Z_OFFSET_ADJUST: "leveldata_36",
        PAGE_CONFIRM_PRINT: "askprint",
        PAGE_PRINTING: "printpause",
        PAGE_PRINTING_KAMP: "leveling_121",
        PAGE_PRINTING_PAUSE: "pauseconfirm",
        PAGE_PRINTING_STOP: "resumeconfirm",
        PAGE_PRINTING_EMERGENCY_STOP: "if_emergency",
        PAGE_PRINTING_COMPLETE: "printfinish",
        PAGE_PRINTING_FILAMENT: "adjusttemp",
        PAGE_PRINTING_SPEED: "adjustspeed_3",
        PAGE_PRINTING_ADJUST: "adjustzoffset3",
        PAGE_PRINTING_FILAMENT_RUNOUT: "nofilament",
        PAGE_PRINTING_DIALOG_SPEED: "print_speed",
        PAGE_PRINTING_DIALOG_FAN: "fan_speed",
        PAGE_PRINTING_DIALOG_FLOW: "flow_speed",
        PAGE_OVERLAY_LOADING: "wifi_scaning",
        PAGE_LIGHTS: "led",
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
                            build_accessor(self.map_page(PAGE_PRINTING_KAMP), "nozzletemp"),
                            build_accessor(
                                self.map_page(PAGE_PRINTING_FILAMENT), "nozzletemp"
                            ),
                        ],
                        formatter=format_temp,
                    )
                ],
                "target": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PREPARE_TEMP), "nozzletemp_t")],
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
                            build_accessor(self.map_page(PAGE_PRINTING_KAMP), "bedtemp"),
                            build_accessor(
                                self.map_page(PAGE_PRINTING_FILAMENT), "bedtemp"
                            ),
                        ],
                        formatter=format_temp,
                    )
                ],
                "target": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PREPARE_TEMP), "bedtemp_t")],
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
                        [
                            build_accessor(self.map_page(PAGE_PRINTING), "printtime"),
                            build_accessor(self.map_page(PAGE_PRINTING_COMPLETE), "t0"),
                        ],
                        formatter=format_time,
                    )
                ],
                "filename": [
                    MappingLeaf(
                        [
                            build_accessor(self.map_page(PAGE_PRINTING), "t0"),
                            build_accessor(self.map_page(PAGE_PRINTING_COMPLETE), "t1"),
                        ],
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
                                self.map_page(PAGE_PRINTING_DIALOG_FLOW), "h0"
                            ),
                            build_accessor(
                                self.map_page(PAGE_PRINTING_DIALOG_FLOW), "n0"
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
                                self.map_page(PAGE_PRINTING_DIALOG_SPEED), "h0"
                            ),
                            build_accessor(
                                self.map_page(PAGE_PRINTING_DIALOG_SPEED), "n0"
                            ),
                        ],
                        field_type="val",
                        formatter=lambda x: f"{x * 100:.0f}",
                    ),
                ],
                "homing_origin": {
                    2: [
                        MappingLeaf(
                            [build_accessor(self.map_page(PAGE_PRINTING_ADJUST), "z_offset")],
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
                        [build_accessor(self.map_page(PAGE_SETTINGS), "fanstatue")],
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
        }
        self.set_z_display("mm")

    def set_z_display(self, value):
        if value == "layer":
            self.data_mapping["print_stats"]["info"] = {
                "current_layer": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_PRINTING), "zvalue")],
                        required_fields=[["print_stats", "info", "total_layer"]],
                        formatter=lambda current, total: f"{current:.0f}/{total:.0f}"
                        if current is not None and total is not None
                        else "0/0",
                    )
                ],
                "total_layer": [MappingLeaf([])],
            }
        else:
            self.data_mapping["motion_report"]["live_position"][2] = [
                MappingLeaf(
                    [
                        build_accessor(self.map_page(PAGE_MAIN), "z_pos"),
                        build_accessor(self.map_page(PAGE_PRINTING), "zvalue"),
                    ]
                )
            ]

    def set_filament_sensor_name(self, value):
        self.data_mapping[f"filament_switch_sensor {value}"] = {
            "enabled": [
                MappingLeaf(
                    [
                        build_accessor(self.map_page(PAGE_SETTINGS), "filamentdec"),
                        build_accessor(self.map_page(PAGE_PRINTING_ADJUST), "filamentdec"),
                    ],
                    field_type="pic",
                    formatter=lambda x: "77" if int(x) == 1 else "76",
                )
            ]
        }


class OpenNeptuneDisplayCommunicator(ElegooDisplayCommunicator):
    supported_firmware_versions = ["0.1.5"]

    bed_leveling_box_size = 20

    async def special_page_handling(self, current_page):
        if current_page == PAGE_MAIN:
            has_wifi = await self.update_wifi_ui()
            if self.has_two_beds:
                await self.write("vis out_bedtemp,1")
            if self.display_name_override:
                display_name = self.display_name_override
                if display_name == "MODEL_NAME":
                    display_name = self.get_device_name()
                await self.write(
                    "xstr 12,20,180,20,1,65535,"
                    + str(BACKGROUND_GRAY)
                    + ',0,1,1,"'
                    + display_name
                    + '"'
                )
            if self.display_name_line_color:
                await self.write("fill 13,47,24,4," + str(self.display_name_line_color))

            await self.write(f"xpic {200 if has_wifi else 230},16,30,30,220,200,51")
        elif current_page == PAGE_SETTINGS_ABOUT:
            await self.write(
                self.mapper.map_page(PAGE_SETTINGS_ABOUT)
                + '.t9.txt="'
                + self.ips
                + '"'
            )
            await self.write("fill 0,400,320,60," + str(BACKGROUND_GRAY))
            await self.write(
                "xstr 0,400,320,30,1,65535,"
                + str(BACKGROUND_GRAY)
                + ',1,1,1,"OpenNept4une"'
            )
            await self.write(
                "xstr 0,430,320,30,2,GRAY,"
                + str(BACKGROUND_GRAY)
                + ',1,1,1,"github.com/OpenNeptune3D"'
            )
        elif current_page == PAGE_PRINTING:
            await self.write("printvalue.xcen=0")
            await self.write("move printvalue,13,267,13,267,0,10")
            await self.write("vis b[16],0")
        elif current_page == PAGE_PRINTING_COMPLETE:
            await self.write('b[4].txt="Print Completed!"')
        elif current_page == PAGE_PRINTING_ADJUST:
            await self.write('t9.txt="' + self.ips + '"')
        elif current_page == PAGE_LEVELING:
            await self.write('b[12].txt="Leveling"')
            await self.write('b[18].txt="Screws Tilt Adjust"')
            await self.write('b[19].txt="Z-Probe Offset"')
            await self.write('b[20].txt="Full Bed Level"')
            self.leveling_mode = None
        elif current_page == PAGE_PRINTING_DIALOG_SPEED:
            await self.write("b[3].maxval=200")
        elif current_page == PAGE_PRINTING_DIALOG_FLOW:
            await self.write("b[3].maxval=200")
        elif current_page == PAGE_SHUTDOWN_DIALOG:
            await self.write("fill 20,100,232,240," + str(BACKGROUND_DIALOG))
            await self.write('xstr 24,104,224,50,1,65535,10665,1,1,1,"Shut Down Host"')
            await self.write('xstr 24,158,224,50,1,65535,10665,1,1,1,"Reboot Host"')
            await self.write('xstr 24,212,224,50,1,65535,10665,1,1,1,"Reboot Klipper"')
            await self.write('xstr 24,286,224,50,1,65535,10665,1,1,1,"Back"')
