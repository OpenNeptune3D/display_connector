from logging import Logger

from src.elegoo_display import ElegooDisplayCommunicator, ElegooDisplayMapper
from src.openneptune_display import OpenNeptuneDisplayCommunicator, OpenNeptuneDisplayMapper

MODEL_N3_REGULAR = "N3"
MODEL_N3_PRO = "N3Pro"
MODEL_N3_PLUS = "N3Plus"
MODEL_N3_MAX = "N3Max"

MODELS_N3 = [MODEL_N3_REGULAR, MODEL_N3_PRO, MODEL_N3_PLUS, MODEL_N3_MAX]


class ElegooNeptune3DisplayMapper(ElegooDisplayMapper):
    pass


class ElegooNeptune3DisplayCommunicator(ElegooDisplayCommunicator):
    def __init__(
        self,
        logger: Logger,
        model: str,
        event_handler,
        port: str,
        baudrate: int = 115200,
        timeout: int = 5,
    ) -> None:
        super().__init__(logger, model, port, event_handler, baudrate, timeout)
        self.mapper = ElegooNeptune3DisplayMapper()



class OpenNeptune3DisplayMapper(OpenNeptuneDisplayMapper):
    pass


class OpenNeptune3DisplayCommunicator(OpenNeptuneDisplayCommunicator):
    def __init__(
        self,
        logger: Logger,
        model: str,
        event_handler,
        port: str,
        baudrate: int = 115200,
        timeout: int = 5,
    ) -> None:
        super().__init__(logger, model, port, event_handler, baudrate, timeout)
        self.mapper = ElegooNeptune3DisplayMapper()
