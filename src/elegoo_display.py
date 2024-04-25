from src.communicator import DisplayCommunicator
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
    TEXT_ERROR,
    TEXT_SUCCESS,
    TEXT_WARNING,
)
from src.wifi import get_wlan0_status


class ElegooDisplayMapper(Mapper):
    page_mapping = {
        PAGE_MAIN: "1",
        PAGE_FILES: "2",
        PAGE_SHUTDOWN_DIALOG: "50",
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
                        [
                            build_accessor(self.map_page(PAGE_PRINTING), "6"),
                            build_accessor(self.map_page(PAGE_PRINTING_COMPLETE), "4"),
                        ],
                        formatter=format_time,
                    )
                ],
                "filename": [
                    MappingLeaf(
                        [
                            build_accessor(self.map_page(PAGE_PRINTING), "t0"),
                            build_accessor(self.map_page(PAGE_PRINTING_COMPLETE), "3"),
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
                        build_accessor(self.map_page(PAGE_SETTINGS), "11"),
                        build_accessor(self.map_page(PAGE_PRINTING_ADJUST), "16"),
                    ],
                    field_type="pic",
                    formatter=lambda x: "77" if int(x) == 1 else "76",
                )
            ]
        }


class ElegooDisplayCommunicator(DisplayCommunicator):
    supported_firmware_versions = ["1.2.11", "1.2.12"]

    bed_leveling_box_size = 20

    async def get_firmware_version(self) -> str:
        return await self.display.get("p[35].b[11].txt", self.timeout)

    async def check_valid_version(self):
        is_valid = await super().check_valid_version()
        if not is_valid:
            await self.write(
                f'xstr 0,464,320,16,2,{TEXT_WARNING},{BACKGROUND_GRAY},1,1,1,"WARNING: Unsupported Display Firmware Version"'
            )

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
                "p["
                + self.mapper.map_page(PAGE_SETTINGS_ABOUT)
                + '].b[16].txt="'
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
            await self.write('b[20].txt="' + self.ips + '"')
        elif current_page == PAGE_LEVELING:
            await self.write('b[12].txt="Leveling"')
            await self.write('b[18].txt="Screws Tilt Adjust"')
            await self.write('b[19].txt="Z-Probe Offset"')
            await self.write('b[19].txt="Full Bed Level"')
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

    async def update_printing_heater_settings_ui(
        self, printing_selected_heater, printing_target_temp
    ):
        if self.has_two_beds:
            await self.write(
                f"p[{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}].b0.picc="
                + str(90 if printing_selected_heater == "extruder" else 89)
            )
            await self.write(
                f"p[{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}].b1.picc="
                + str(90 if printing_selected_heater == "heater_bed" else 89)
            )
            await self.write(
                f"p[{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}].b2.picc="
                + str(90 if printing_selected_heater == "heater_bed_outer" else 89)
            )
            await self.write(
                f"p[{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}].targettemp.val="
                + str(printing_target_temp)
            )

        else:
            await self.write(
                f'p[{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}].b[13].pic={54 + ["extruder", "heater_bed"].index(printing_selected_heater)}'
            )
            await self.write(
                f'p[{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}].b[35].txt="'
                + str(printing_target_temp)
                + '"'
            )

    async def update_printing_temperature_increment_ui(
        self, printing_selected_temp_increment
    ):
        await self.write(
            f'p[{self.mapper.map_page(PAGE_PRINTING_FILAMENT)}].p1.pic={56 + ["1", "5", "10"].index(printing_selected_temp_increment)}'
        )

    async def update_printing_speed_settings_ui(
        self, printing_selected_speed_type, printing_target_speed
    ):
        await self.write(
            f"p[{self.mapper.map_page(PAGE_PRINTING_SPEED)}].b0.picc="
            + str(59 if printing_selected_speed_type == "print" else 58)
        )
        await self.write(
            f"p[{self.mapper.map_page(PAGE_PRINTING_SPEED)}].b1.picc="
            + str(59 if printing_selected_speed_type == "flow" else 58)
        )
        await self.write(
            f"p[{self.mapper.map_page(PAGE_PRINTING_SPEED)}].b2.picc="
            + str(59 if printing_selected_speed_type == "fan" else 58)
        )
        await self.write(
            f"p[{self.mapper.map_page(PAGE_PRINTING_SPEED)}].targetspeed.val={printing_target_speed*100:.0f}"
        )

    async def update_printing_speed_increment_ui(
        self, printing_selected_speed_increment
    ):
        await self.write(
            f"p[{self.mapper.map_page(PAGE_PRINTING_SPEED)}].b[14].picc="
            + str(59 if printing_selected_speed_increment == "1" else 58)
        )
        await self.write(
            f"p[{self.mapper.map_page(PAGE_PRINTING_SPEED)}].b[15].picc="
            + str(59 if printing_selected_speed_increment == "5" else 58)
        )
        await self.write(
            f"p[{self.mapper.map_page(PAGE_PRINTING_SPEED)}].b[16].picc="
            + str(59 if printing_selected_speed_increment == "10" else 58)
        )

    async def update_printing_zoffset_increment_ui(self, z_offset_distance):
        await self.write(
            f"p[{self.mapper.map_page(PAGE_PRINTING_ADJUST)}].b[23].picc="
            + str(36 if z_offset_distance == "0.01" else 65)
        )
        await self.write(
            f"p[{self.mapper.map_page(PAGE_PRINTING_ADJUST)}].b[24].picc="
            + str(36 if z_offset_distance == "0.1" else 65)
        )
        await self.write(
            f"p[{self.mapper.map_page(PAGE_PRINTING_ADJUST)}].b[25].picc="
            + str(36 if z_offset_distance == "1" else 65)
        )

    async def update_preset_temp_ui(
        self,
        temperature_preset_step,
        temperature_preset_extruder,
        temperature_preset_bed,
    ):
        await self.write(
            f"p[{self.mapper.map_page(PAGE_SETTINGS_TEMPERATURE_SET)}].b[7].pic={56 + [1, 5, 10].index(temperature_preset_step)}"
        )
        await self.write(
            f'p[{self.mapper.map_page(PAGE_SETTINGS_TEMPERATURE_SET)}].b[18].txt="{temperature_preset_extruder}"'
        )
        await self.write(
            f'p[{self.mapper.map_page(PAGE_SETTINGS_TEMPERATURE_SET)}].b[19].txt="{temperature_preset_bed}"'
        )

    async def update_prepare_move_ui(self, move_distance):
        await self.write(
            f'p[{self.mapper.map_page(PAGE_PREPARE_MOVE)}].p0.pic={10 + ["0.1", "1", "10"].index(move_distance)}'
        )

    async def update_prepare_extrude_ui(self, extrude_amount, extrude_speed):
        await self.write(
            f'p[{self.mapper.map_page(PAGE_PREPARE_EXTRUDER)}].b[8].txt="{extrude_amount}"'
        )
        await self.write(
            f'p[{self.mapper.map_page(PAGE_PREPARE_EXTRUDER)}].b[9].txt="{extrude_speed}"'
        )

    async def update_wifi_ui(self):
        has_wifi, ssid, rssi_category = get_wlan0_status()
        if not has_wifi:
            await self.write("picq 230,0,42,42,214")
            return False
        if ssid is None:
            await self.write("picq 230,0,42,42,313")
        else:
            await self.write(f"picq 230,0,42,42,{313 + rssi_category}")
        return True

    async def show_files_page(self, current_dir, dir_contents, files_page):
        page_size = 5
        title = current_dir.split("/")[-1]
        if title == "":
            title = "Files"
        file_count = len(dir_contents)
        if file_count == 0:
            await self.write(
                f'p[{self.mapper.map_page(PAGE_FILES)}].b[11].txt="{title} (Empty)"'
            )
        else:
            await self.write(
                f'p[{self.mapper.map_page(PAGE_FILES)}].b[11].txt="{title} ({(files_page * page_size) + 1}-{min((files_page * page_size) + page_size, file_count)}/{file_count})"'
            )
        component_index = 0
        for index in range(
            files_page * page_size, min(len(dir_contents), (files_page + 1) * page_size)
        ):
            file = dir_contents[index]
            await self.write(
                f'p[{self.mapper.map_page(PAGE_FILES)}].b[{component_index + 18}].txt="{file["name"]}"'
            )
            if file["type"] == "dir":
                await self.write(
                    f"p[{self.mapper.map_page(PAGE_FILES)}].b[{component_index + 13}].pic=194"
                )
            else:
                await self.write(
                    f"p[{self.mapper.map_page(PAGE_FILES)}].b[{component_index + 13}].pic=193"
                )
            component_index += 1
        for index in range(component_index, page_size):
            await self.write(
                f"p[{self.mapper.map_page(PAGE_FILES)}].b[{index + 13}].pic=195"
            )
            await self.write(
                f'p[{self.mapper.map_page(PAGE_FILES)}].b[{index + 18}].txt=""'
            )

    async def update_printing_state_ui(self, state):
        if state == "printing":
            await self.write(f"p[{self.mapper.map_page(PAGE_PRINTING)}].b[44].pic=68")
        elif state == "paused":
            await self.write(f"p[{self.mapper.map_page(PAGE_PRINTING)}].b[44].pic=69")

    async def set_data_prepare_screen(self, filename, metadata):
        await self.write(f"p[{self.mapper.map_page(PAGE_CONFIRM_PRINT)}].b[3].font=2")
        await self.write(
            f'p[{self.mapper.map_page(PAGE_CONFIRM_PRINT)}].b[2].txt="{build_format_filename()(filename)}"'
        )
        info = []
        if "layer_height" in metadata:
            info.append(f"Layer: {metadata['layer_height']}mm")
        if "estimated_time" in metadata:
            info.append(f"Time: {format_time(metadata['estimated_time'])}")
        await self.write(
            f'p[{self.mapper.map_page(PAGE_CONFIRM_PRINT)}].b[3].txt="{" ".join(info)}"'
        )

    async def draw_initial_screw_leveling(self):
        await self.write('b[1].txt="Screws Tilt Adjust"')
        await self.write('b[2].txt="Please Wait..."')
        await self.write('b[3].txt="Heating..."')
        await self.write("vis b[4],0")
        await self.write("vis b[5],0")
        await self.write("vis b[6],0")
        await self.write("vis b[7],0")
        await self.write("vis b[8],0")
        await self.write("fill 0,110,320,290,10665")

    async def draw_completed_screw_leveling(self, screw_levels):
        await self.write('b[1].txt="Screws Tilt Adjust"')
        await self.write('b[2].txt="Adjust the screws as indicated"')
        await self.write(
            'b[3].txt="01:20 means 1  turn and 20 mins\\rCW=clockwise\\rCCW=counter-clockwise"'
        )
        await self.write("vis b[4],0")
        await self.write("vis b[5],0")
        await self.write("vis b[6],0")
        await self.write("vis b[7],0")
        await self.write("vis b[8],1")
        await self.write("fill 0,110,320,290,10665")
        await self.write('xstr 12,320,100,20,1,65535,10665,1,1,1,"front left"')
        await self.draw_screw_level_info_at("12,340,100,20", screw_levels["front left"])

        await self.write('xstr 170,320,100,20,1,65535,10665,1,1,1,"front right"')
        await self.draw_screw_level_info_at(
            "170,340,100,20", screw_levels["front right"]
        )

        await self.write('xstr 170,120,100,20,1,65535,10665,1,1,1,"rear right"')
        await self.draw_screw_level_info_at(
            "170,140,100,20", screw_levels["rear right"]
        )

        await self.write('xstr 12,120,100,20,1,65535,10665,1,1,1,"rear left"')
        await self.draw_screw_level_info_at("12,140,100,20", screw_levels["rear left"])

        if "center right" in screw_levels:
            await self.write('xstr 12,220,100,30,1,65535,10665,1,1,1,"center\\rright"')
            await self.draw_screw_level_info_at(
                "170,240,100,20", screw_levels["center right"]
            )
        if "center left" in screw_levels:
            await self.write('xstr 12,120,100,20,1,65535,10665,1,1,1,"center\\rleft"')
            await self.draw_screw_level_info_at(
                "12,240,100,20", screw_levels["center left"]
            )

        await self.write('xstr 96,215,100,50,1,65535,15319,1,1,1,"Retry"')

    async def draw_screw_level_info_at(self, position, level):
        if level == "base":
            await self.write(f'xstr {position},0,65535,10665,1,1,1,"base"')
        else:
            color = TEXT_SUCCESS if int(level[-2:]) < 5 else TEXT_ERROR
            await self.write(f'xstr {position},0,{color},10665,1,1,1,"{level}"')

    async def update_screw_level_description(self, text):
        await self.write(f'b[3].txt="${text}"')

    async def draw_initial_zprobe_leveling(self, z_probe_step, z_probe_distance):
        await self.write('p[137].b[19].txt="Z-Probe"')
        await self.write("fill 0,250,320,320,10665")
        await self.write("fill 0,50,320,80,10665")
        await self.update_zprobe_leveling_ui(z_probe_step, z_probe_distance)

    async def update_zprobe_leveling_ui(self, z_probe_step, z_probe_distance):
        await self.write('p[137].b[19].txt="Z-Probe"')
        await self.write(
            f'p[137].b[11].pic={7 + ["0.01", "0.1", "1"].index(z_probe_step)}'
        )
        await self.write(f'p[137].b[20].txt="{z_probe_distance}"')

    async def draw_kamp_page(self, bed_leveling_counts):
        await self.write("fill 0,45,272,340,10665")
        await self.write('xstr 0,0,272,50,1,65535,10665,1,1,1,"Creating Bed Mesh"')
        max_size = 264  # display width - 4px padding
        x_probes = bed_leveling_counts[0]
        y_probes = bed_leveling_counts[1]
        spacing = 2
        self.bed_leveling_box_size = min(
            40, int(min(max_size / x_probes, max_size / y_probes) - spacing)
        )
        total_width = (x_probes * (self.bed_leveling_box_size + spacing)) - spacing
        total_height = (y_probes * (self.bed_leveling_box_size + spacing)) - spacing
        self.bed_leveling_x_offset = 4 + (max_size - total_width) / 2
        self.bed_leveling_y_offset = 45 + (max_size - total_height) / 2
        for x in range(0, x_probes):
            for y in range(0, y_probes):
                await self.draw_kamp_box(x, y, 17037)

    async def update_kamp_text(self, text):
        await self.write(f'xstr 0,310,320,30,1,65535,10665,1,1,1,"{text}"')

    async def draw_kamp_box_index(self, index, color, bed_leveling_counts):
        if bed_leveling_counts[0] == 0:
            return
        row = int(index / bed_leveling_counts[0])
        inverted_row = (bed_leveling_counts[1] - 1) - row
        col = index % bed_leveling_counts[0]
        if row % 2 == 1:
            col = bed_leveling_counts[0] - 1 - col
        await self.draw_kamp_box(col, inverted_row, color)

    async def draw_kamp_box(self, x, y, color):
        box_size = self.bed_leveling_box_size
        if box_size > 0:
            await self.write(
                f"fill {int(self.bed_leveling_x_offset+x*(box_size+2))},{47+y*(box_size+2)},{box_size},{box_size},{color}"
            )

    async def update_klipper_version_ui(self, software_version):
        await self.write(
            "p["
            + self.mapper.map_page(PAGE_SETTINGS_ABOUT)
            + '].b[10].txt="'
            + software_version
            + '"'
        )

    async def update_machine_size_ui(self, max_x, max_y, max_z):
        await self.write(
            f'p[{self.mapper.map_page(PAGE_SETTINGS_ABOUT)}].b[9].txt="{max_x}x{max_y}x{max_z}"'
        )

    async def display_thumbnail(self, page_number, thumbnail):
        await self.write("vis cp0,1")
        await self.write("p[" + str(page_number) + "].cp0.close()")

        parts = []
        start = 0
        end = 1024
        while start + 1024 < len(thumbnail):
            parts.append(thumbnail[start:end])
            start = start + 1024
            end = end + 1024

        parts.append(thumbnail[start : len(thumbnail)])
        for part in parts:
            await self.write(
                "p[" + str(page_number) + '].cp0.write("' + str(part) + '")'
            )

    async def hide_thumbnail(self):
        await self.write("vis cp0,0")

    async def update_time_remaining(self, time_remaining):
        await self.write(
            f'p[{self.mapper.map_page(PAGE_PRINTING)}].b[37].txt="{time_remaining}"'
        )

    async def show_bed_mesh_final(self):
        await self.update_kamp_text("Bed Mesh completed")
        await self.write(
            'xstr 0,350,272,30,1,65535,10665,1,1,1,"Tap SAVE to update printer config and restart"'
        )
        await self.write('xstr 40,400,200,50,1,65535,15319,1,1,1,"SAVE"')

    async def show_shutdown_screens(self):
        await self.write("cls 44637")
        await self.write(
            'xstr 8,220,256,20,1,54151,44637,1,1,1,"Please wait while your printer"'
        )
        await self.write('xstr 24,240,224,20,1,54151,44637,1,1,1,"shuts down."')
        await self.write("delay=10000")
        await self.write("cls BLACK")
        await self.write(
            'xstr 24,220,224,20,1,54150,0,1,1,1,"It\'s now safe to turn off"'
        )
        await self.write('xstr 24,240,224,20,1,54150,0,1,1,1,"your printer."')
