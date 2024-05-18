from logging import Logger

from src.elegoo_display import ElegooDisplayCommunicator, ElegooDisplayMapper


MODEL_N3_REGULAR = "N3"
MODEL_N3_PRO = "N3Pro"
MODEL_N3_PLUS = "N3Plus"
MODEL_N3_MAX = "N3Max"

MODELS_N3 = [MODEL_N3_REGULAR, MODEL_N3_PRO, MODEL_N3_PLUS, MODEL_N3_MAX]


class Neptune3DisplayMapper(ElegooDisplayMapper):
    pass


class Neptune3DisplayCommunicator(ElegooDisplayCommunicator):
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
        self.mapper = Neptune3DisplayMapper()
