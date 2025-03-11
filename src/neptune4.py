from logging import Logger
from src.mapping import (
    MappingLeaf,
    build_accessor,
    PAGE_MAIN,
    PAGE_PREPARE_TEMP,
    PAGE_PRINTING_FILAMENT,
    PAGE_SETTINGS_ABOUT,
    format_temp,
)
from src.elegoo_display import ElegooDisplayMapper, ElegooDisplayCommunicator
from src.openneptune_display import OpenNeptuneDisplayMapper, OpenNeptuneDisplayCommunicator

MODEL_N4_REGULAR = "N4"
MODEL_N4_PRO = "N4Pro"
MODEL_N4_PLUS = "N4Plus"
MODEL_N4_MAX = "N4Max"

MODELS_N4 = [MODEL_N4_REGULAR, MODEL_N4_PRO, MODEL_N4_PLUS, MODEL_N4_MAX]


class ElegooNeptune4Mapper(ElegooDisplayMapper):
    pass


class ElegooNeptune4ProMapper(ElegooNeptune4Mapper):
    def __init__(self) -> None:
        super().__init__()  # Call the parent class constructor first to initialize attributes
        self.page_mapping[PAGE_PREPARE_TEMP] = "pretemp"
        self.page_mapping[PAGE_PRINTING_FILAMENT] = "adjusttemp_pro"
        self.data_mapping["extruder"]["target"] = [
            MappingLeaf(
                [
                    build_accessor(self.map_page(PAGE_PREPARE_TEMP), "nozzletemp_t"),
                    build_accessor(
                        self.map_page(PAGE_PRINTING_FILAMENT), "nozzletemp_t"
                    ),
                ],
                formatter=format_temp,
            ),
            MappingLeaf(
                [build_accessor(self.map_page(PAGE_PREPARE_TEMP), 17)],
                formatter=lambda x: f"{x:.0f}",
            ),
        ]
        self.data_mapping["heater_bed"]["target"] = [
            MappingLeaf(
                [
                    build_accessor(self.map_page(PAGE_PREPARE_TEMP), "bedtemp_t"),
                    build_accessor(self.map_page(PAGE_PRINTING_FILAMENT), "bedtemp_t"),
                ],
                formatter=format_temp,
            ),
            MappingLeaf(
                [build_accessor(self.map_page(PAGE_PREPARE_TEMP), "18")],
                formatter=lambda x: f"{x:.0f}",
            ),
        ]
        self.data_mapping["heater_generic heater_bed_outer"] = {
            "temperature": [
                MappingLeaf(
                    [
                        build_accessor(self.map_page(PAGE_MAIN), "out_bedtemp"),
                        build_accessor(self.map_page(PAGE_PREPARE_TEMP), "out_bedtemp"),
                        build_accessor(
                            self.map_page(PAGE_PRINTING_FILAMENT), "out_bedtemp"
                        ),
                    ],
                    formatter=format_temp,
                )
            ],
            "target": [
                MappingLeaf(
                    [
                        build_accessor(
                            self.map_page(PAGE_PREPARE_TEMP), "out_bedtemp_t"
                        ),
                        build_accessor(
                            self.map_page(PAGE_PRINTING_FILAMENT), "out_bedtemp_t"
                        ),
                    ],
                    formatter=format_temp,
                ),
                MappingLeaf(
                    [build_accessor(self.map_page(PAGE_PREPARE_TEMP), "28")],
                    formatter=lambda x: f"{x:.0f}",
                ),
            ],
        }
        self.set_filament_sensor_name("filament_sensor")


class ElegooNeptune4PlusMapper(ElegooNeptune4Mapper):
    pass


class ElegooNeptune4MaxMapper(ElegooNeptune4Mapper):
    pass


class ElegooNeptune4DisplayCommunicator(ElegooDisplayCommunicator):
    def __init__(
        self,
        logger: Logger,
        model: str,
        event_handler,
        port: str = None,
        baudrate: int = 115200,
        timeout: int = 5,
    ) -> None:
        super().__init__(logger, model, port if port else "/dev/ttyS1", event_handler, baudrate, timeout)
        self.mapper = self.get_mapper(model)
        self.has_two_beds = model.lower() == MODEL_N4_PRO.lower()

    def get_mapper(self, model: str) -> ElegooNeptune4Mapper:
        if model.lower() == MODEL_N4_REGULAR.lower():
            self.model = MODEL_N4_REGULAR
            return ElegooNeptune4Mapper()
        elif model.lower() == MODEL_N4_PRO.lower():
            self.model = MODEL_N4_PRO
            return ElegooNeptune4ProMapper()
        elif model.lower() == MODEL_N4_PLUS.lower():
            self.model = MODEL_N4_PLUS
            return ElegooNeptune4PlusMapper()
        elif model.lower() == MODEL_N4_MAX.lower():
            self.model = MODEL_N4_MAX
            return ElegooNeptune4MaxMapper()
        else:
            self.logger.error(
                f"Unknown printer model {model}, falling back to Neptune 4"
            )
            self.model = MODEL_N4_REGULAR
            return ElegooNeptune4Mapper()

    def get_device_name(self):
        model_map = {
            MODEL_N4_REGULAR: "Neptune 4",
            MODEL_N4_PRO: "Neptune 4 Pro",
            MODEL_N4_PLUS: "Neptune 4 Plus",
            MODEL_N4_MAX: "Neptune 4 Max",
        }
        return model_map[self.model]

    async def initialize_display(self):
        await self.write("sendxy=1")
        model_image_key = None
        if self.model == MODEL_N4_REGULAR:
            model_image_key = "213"
        elif self.model == MODEL_N4_PRO:
            model_image_key = "214"
            await self.write(
                f"{self.mapper.map_page(PAGE_MAIN)}.disp_q5.val=1"
            )  # N4Pro Outer Bed Symbol (Bottom Rig>
        elif self.model == MODEL_N4_PLUS:
            model_image_key = "313"
        elif self.model == MODEL_N4_MAX:
            model_image_key = "314"

        if self.display_name_override is None:
            await self.write(
                f"{self.mapper.map_page(PAGE_MAIN)}.q4.picc={model_image_key}"
            )
        else:
            await self.write(f"{self.mapper.map_page(PAGE_MAIN)}.q4.picc=137")

        await self.write(
            f'{self.mapper.map_page(PAGE_SETTINGS_ABOUT)}.machine.txt="{self.get_device_name()}"'
        )

    def get_model(self) -> str:
        return self.model


# OpenNeptune Display Code

class OpenNeptune4Mapper(OpenNeptuneDisplayMapper):
    pass


class OpenNeptune4ProMapper(OpenNeptune4Mapper):
    def __init__(self) -> None:
        self.page_mapping[PAGE_PREPARE_TEMP] = "pretemp"
        self.page_mapping[PAGE_PRINTING_FILAMENT] = "adjusttemp_pro"
        super().__init__()
        self.data_mapping["extruder"]["target"] = [
            MappingLeaf(
                [
                    build_accessor(self.map_page(PAGE_PREPARE_TEMP), "nozzletemp_t"),
                    build_accessor(
                        self.map_page(PAGE_PRINTING_FILAMENT), "nozzletemp_t"
                    ),
                ],
                formatter=format_temp,
            ),
            MappingLeaf(
                [build_accessor(self.map_page(PAGE_PREPARE_TEMP), 17)],
                formatter=lambda x: f"{x:.0f}",
            ),
        ]
        self.data_mapping["heater_bed"]["target"] = [
            MappingLeaf(
                [
                    build_accessor(self.map_page(PAGE_PREPARE_TEMP), "bedtemp_t"),
                    build_accessor(self.map_page(PAGE_PRINTING_FILAMENT), "bedtemp_t"),
                ],
                formatter=format_temp,
            ),
            MappingLeaf(
                [build_accessor(self.map_page(PAGE_PREPARE_TEMP), "18")],
                formatter=lambda x: f"{x:.0f}",
            ),
        ]
        self.data_mapping["heater_generic heater_bed_outer"] = {
            "temperature": [
                MappingLeaf(
                    [
                        build_accessor(self.map_page(PAGE_MAIN), "out_bedtemp"),
                        build_accessor(self.map_page(PAGE_PREPARE_TEMP), "out_bedtemp"),
                        build_accessor(
                            self.map_page(PAGE_PRINTING_FILAMENT), "out_bedtemp"
                        ),
                    ],
                    formatter=format_temp,
                )
            ],
            "target": [
                MappingLeaf(
                    [
                        build_accessor(
                            self.map_page(PAGE_PREPARE_TEMP), "out_bedtemp_t"
                        ),
                        build_accessor(
                            self.map_page(PAGE_PRINTING_FILAMENT), "out_bedtemp_t"
                        ),
                    ],
                    formatter=format_temp,
                ),
                MappingLeaf(
                    [build_accessor(self.map_page(PAGE_PREPARE_TEMP), "28")],
                    formatter=lambda x: f"{x:.0f}",
                ),
            ],
        }
        self.set_filament_sensor_name("filament_sensor")


class OpenNeptune4PlusMapper(OpenNeptune4Mapper):
    pass


class OpenNeptune4MaxMapper(OpenNeptune4Mapper):
    pass


class OpenNeptune4DisplayCommunicator(OpenNeptuneDisplayCommunicator):
    def __init__(
        self,
        logger: Logger,
        model: str,
        event_handler,
        port: str = None,
        baudrate: int = 115200,
        timeout: int = 5,
    ) -> None:
        super().__init__(
            logger,
            model,
            port if port else "/dev/ttyS1",
            event_handler,
            baudrate,
            timeout,
        )
        self.mapper = self.get_mapper(model)
        self.has_two_beds = model.lower() == MODEL_N4_PRO.lower()

    def get_mapper(self, model: str) -> OpenNeptune4Mapper:
        if model.lower() == MODEL_N4_REGULAR.lower():
            self.model = MODEL_N4_REGULAR
            return OpenNeptune4Mapper()
        elif model.lower() == MODEL_N4_PRO.lower():
            self.model = MODEL_N4_PRO
            return OpenNeptune4ProMapper()
        elif model.lower() == MODEL_N4_PLUS.lower():
            self.model = MODEL_N4_PLUS
            return OpenNeptune4PlusMapper()
        elif model.lower() == MODEL_N4_MAX.lower():
            self.model = MODEL_N4_MAX
            return OpenNeptune4MaxMapper()
        else:
            self.logger.error(
                f"Unknown printer model {model}, falling back to Neptune 4"
            )
            self.model = MODEL_N4_REGULAR
            return OpenNeptune4Mapper()

    def get_device_name(self):
        model_map = {
            MODEL_N4_REGULAR: "Neptune 4",
            MODEL_N4_PRO: "Neptune 4 Pro",
            MODEL_N4_PLUS: "Neptune 4 Plus",
            MODEL_N4_MAX: "Neptune 4 Max",
        }
        return model_map[self.model]

    async def initialize_display(self):
        await self.write("sendxy=1")
        model_image_key = None
        if self.model == MODEL_N4_REGULAR:
            model_image_key = "213"
        elif self.model == MODEL_N4_PRO:
            model_image_key = "214"
            await self.write(
                f"{self.mapper.map_page(PAGE_MAIN)}.disp_q5.val=1"
            )  # N4Pro Outer Bed Symbol (Bottom Rig>
        elif self.model == MODEL_N4_PLUS:
            model_image_key = "313"
        elif self.model == MODEL_N4_MAX:
            model_image_key = "314"

        if self.display_name_override is None:
            await self.write(
                f"{self.mapper.map_page(PAGE_MAIN)}.q4.picc={model_image_key}"
            )
        else:
            await self.write(f"{self.mapper.map_page(PAGE_MAIN)}.q4.picc=137")

        await self.write(
            f'{self.mapper.map_page(PAGE_SETTINGS_ABOUT)}.machine.txt="{self.get_device_name()}"'
        )

    def get_model(self) -> str:
        return self.model
