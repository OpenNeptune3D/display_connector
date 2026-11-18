from src.elegoo_display import ElegooDisplayCommunicator
from src.response_actions import openneptune_response_actions
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


def format_light_status(value):
    return "On" if value and float(value) > 0 else "Off"


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
                # Slate's pretemp has no nozzletemp_t target text
                "target": [MappingLeaf([])],
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
                # Slate's pretemp has no bedtemp_t target text
                "target": [MappingLeaf([])],
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
                        # Slate-only position readout on the move page
                        MappingLeaf(
                            [build_accessor(self.map_page(PAGE_PREPARE_MOVE), "x_pos")]
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
                        MappingLeaf(
                            [build_accessor(self.map_page(PAGE_PREPARE_MOVE), "y_pos")]
                        ),
                    ],
                    2: [
                        MappingLeaf(
                            [
                                build_accessor(self.map_page(PAGE_MAIN), "z_pos"),
                                build_accessor(self.map_page(PAGE_PREPARE_MOVE), "z_pos"),
                            ]
                        )
                    ],
                },
                # Slate's print page has no pressure_val (live speed) text
                "live_velocity": [MappingLeaf([])],
            },
            "print_stats": {
                "print_duration": [
                    MappingLeaf(
                        # Slate's print page has no printtime text; only the
                        # print-complete page shows the duration
                        [build_accessor(self.map_page(PAGE_PRINTING_COMPLETE), "t0")],
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
                    # Slate-only fan readout on the main page
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_MAIN), "Fan_Pwr")],
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
                # Slate's print page has no printvalue (percent) text, only
                # the printprocess progress bar
                "progress": [
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
                    ),
                    # Slate-only light status text on the main and print pages
                    MappingLeaf(
                        [
                            build_accessor(self.map_page(PAGE_MAIN), "Light_Stat"),
                            build_accessor(self.map_page(PAGE_PRINTING), "Light_Stat"),
                        ],
                        formatter=format_light_status,
                    ),
                ]
            },
            "output_pin Frame_Light": {
                "value": [
                    MappingLeaf(
                        [build_accessor(self.map_page(PAGE_LIGHTS), "led2")],
                        field_type="pic",
                        formatter=lambda x: "77" if int(x) == 1 else "76",
                    ),
                    MappingLeaf(
                        [
                            build_accessor(self.map_page(PAGE_MAIN), "Light_Stat"),
                            build_accessor(self.map_page(PAGE_PRINTING), "Light_Stat"),
                        ],
                        formatter=format_light_status,
                    ),
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
                        build_accessor(self.map_page(PAGE_PREPARE_MOVE), "z_pos"),
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
    extra_response_actions = openneptune_response_actions

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
            await self.write("fill 0,400,272,60," + str(BACKGROUND_GRAY))
            await self.write(
                "xstr 0,400,272,30,1,65535,"
                + str(BACKGROUND_GRAY)
                + ',1,1,1,"OpenNept4une"'
            )
            await self.write(
                "xstr 0,430,272,30,2,GRAY,"
                + str(BACKGROUND_GRAY)
                + ',1,1,1,"github.com/OpenNeptune3D"'
            )
        elif current_page == PAGE_PRINTING_COMPLETE:
            # By name: Slate moved t1 from id 4 to id 2 (id 4 is hotspot m1)
            await self.write('t1.txt="Print Completed!"')
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
            await self.write("fill 20,100,232,290," + str(BACKGROUND_DIALOG))
            await self.write('xstr 24,104,224,50,1,65535,10665,1,1,1,"Shut Down Host"')
            await self.write('xstr 24,158,224,50,1,65535,10665,1,1,1,"Reboot Host"')
            await self.write('xstr 24,212,224,50,1,65535,10665,1,1,1,"Reboot Klipper"')
            await self.write('xstr 24,266,224,50,1,65535,10665,1,1,1,"Firmware Restart"')
            await self.write('xstr 24,320,224,50,1,65535,10665,1,1,1,"Back"')

    # Slate renumbered or removed components the stock UI code writes by id;
    # these overrides target Slate's layout instead.

    async def update_time_remaining(self, time_remaining):
        # Stock writes b[37] (t7); in Slate t7 is id 22
        await self.write(
            f'{self.mapper.map_page(PAGE_PRINTING)}.t7.txt="{time_remaining}"'
        )

    async def update_printing_heater_settings_ui(
        self, printing_selected_heater, printing_target_temp
    ):
        if self.has_two_beds:
            # adjusttemp_pro's b0-b2 and targettemp line up with stock
            await super().update_printing_heater_settings_ui(
                printing_selected_heater, printing_target_temp
            )
            return
        # Stock writes a heater highlight to b[13] (picture p0) and the target to
        # b[35]; Slate has no p0 (id 13 is hotspot m10) and targettemp is id 26
        await self.write(
            f'{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}.targettemp.txt="'
            + f'{printing_target_temp:.0f}"'
        )

    async def update_printing_temperature_increment_ui(
        self, printing_selected_temp_increment
    ):
        # Slate's adjusttemp and adjusttemp_pro have no p1 step-highlight picture
        pass

    async def update_prepare_move_ui(self, move_distance):
        # Slate's premove has no p0 step-highlight picture
        pass

    async def update_printing_state_ui(self, state):
        # Slate's print page has no b[44] pause/resume picture
        pass
