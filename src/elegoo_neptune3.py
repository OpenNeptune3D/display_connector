import importlib
from logging import Logger

MODEL_N3_REGULAR = "N3"
MODEL_N3_PRO = "N3Pro"
MODEL_N3_PLUS = "N3Plus"
MODEL_N3_MAX = "N3Max"

MODELS_N3 = [MODEL_N3_REGULAR, MODEL_N3_PRO, MODEL_N3_PLUS, MODEL_N3_MAX]


class ElegooNeptune3DisplayMapper:
    def __init__(self):
        # Dynamically import ElegooDisplayMapper to avoid circular import
        importlib.import_module("src.elegoo_display").ElegooDisplayMapper
        super().__init__()


class ElegooNeptune3DisplayCommunicator:
    def __init__(
        self,
        logger: Logger,
        model: str,
        event_handler,
        port: str,
        baudrate: int = 115200,
        timeout: int = 5,
    ) -> None:
        # Dynamically import ElegooDisplayCommunicator to avoid circular import
        importlib.import_module("src.elegoo_display").ElegooDisplayCommunicator
        super().__init__(logger, model, port, event_handler, baudrate, timeout)
        self.mapper = ElegooNeptune3DisplayMapper()


class OpenNeptune3DisplayMapper:
    def __init__(self):
        # Dynamically import OpenNeptuneDisplayMapper to avoid circular import
        importlib.import_module("src.openneptune_display").OpenNeptuneDisplayMapper
        super().__init__()


class OpenNeptune3DisplayCommunicator:
    def __init__(
        self,
        logger: Logger,
        model: str,
        event_handler,
        port: str,
        baudrate: int = 115200,
        timeout: int = 5,
    ) -> None:
        # Dynamically import OpenNeptuneDisplayCommunicator to avoid circular import
        importlib.import_module("src.openneptune_display").OpenNeptuneDisplayCommunicator
        super().__init__(logger, model, port, event_handler, baudrate, timeout)
        self.mapper = ElegooNeptune3DisplayMapper()
