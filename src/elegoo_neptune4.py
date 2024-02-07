from logging import Logger
from src.mapping import *
from src.elegoo_display import ElegooDisplayMapper, ElegooDisplayCommunicator

MODEL_N4_REGULAR = 'N4'
MODEL_N4_PRO = 'N4Pro'
MODEL_N4_PLUS = 'N4Plus'
MODEL_N4_MAX = 'N4Max'

class Neptune4Mapper(ElegooDisplayMapper):
    pass

class Neptune4ProMapper(Neptune4Mapper):

    def __init__(self) -> None:
        self.page_mapping[PAGE_PREPARE_TEMP] = "6"
        self.page_mapping[PAGE_PRINTING_FILAMENT] = "27"
        super().__init__()
        self.data_mapping["extruder"]["target"] = [MappingLeaf([build_accessor(self.map_page(PAGE_PREPARE_TEMP), "nozzletemp_t"),
                                        build_accessor(self.map_page(PAGE_PRINTING_FILAMENT), "nozzletemp_t")], formatter=format_temp),
                                        MappingLeaf([build_accessor(self.map_page(PAGE_PREPARE_TEMP), 17)], formatter=lambda x: f"{x:.0f}")]
        self.data_mapping["heater_bed"]["target"] = [MappingLeaf([build_accessor(self.map_page(PAGE_PREPARE_TEMP), "bedtemp_t"),
                                        build_accessor(self.map_page(PAGE_PRINTING_FILAMENT), "bedtemp_t")], formatter=format_temp),
                                        MappingLeaf([build_accessor(self.map_page(PAGE_PREPARE_TEMP), 18)], formatter=lambda x: f"{x:.0f}")]
        self.data_mapping["heater_generic heater_bed_outer"] = {
                "temperature": [MappingLeaf([build_accessor(self.map_page(PAGE_MAIN), "out_bedtemp"),
                                             build_accessor(self.map_page(PAGE_PREPARE_TEMP), "out_bedtemp"),
                                             build_accessor(self.map_page(PAGE_PRINTING_FILAMENT), "out_bedtemp")], formatter=format_temp)],
                "target": [MappingLeaf([build_accessor(self.map_page(PAGE_PREPARE_TEMP), "out_bedtemp_t"),
                                        build_accessor(self.map_page(PAGE_PRINTING_FILAMENT), "out_bedtemp_t")], formatter=format_temp),
                                        MappingLeaf([build_accessor(self.map_page(PAGE_PREPARE_TEMP), 28)], formatter=lambda x: f"{x:.0f}")]
            }

class Neptune4PlusMapper(Neptune4Mapper):
    pass

class Neptune4MaxMapper(Neptune4Mapper):
    pass


class Neptune4DisplayCommunicator(ElegooDisplayCommunicator):
    def __init__(self, logger: Logger, model: str, event_handler, port: str = "/dev/ttyS1", baudrate: int = 115200, timeout: int = 5) -> None:
        super().__init__(logger, port, event_handler, baudrate, timeout)
        self.model = model
        self.mapper = self.get_mapper(model)

    def get_mapper(self, model: str) -> Neptune4Mapper:
        if model == MODEL_N4_REGULAR:
            return Neptune4Mapper()
        elif model == MODEL_N4_PRO:
            return Neptune4ProMapper()
        elif model == MODEL_N4_PLUS:
            return Neptune4PlusMapper()
        elif model == MODEL_N4_MAX:
            return Neptune4MaxMapper()
        else:
            self.logger.error(f"Unknown printer model {model}, falling back to Neptune 4")
            self.model = MODEL_N4_REGULAR
            return Neptune4Mapper()

    def get_model(self) -> str:
        return self.model