import importlib
from logging import Logger

MODEL_CUSTOM = "Custom"

class CustomDisplayCommunicator:
    def __init__(
        self,
        logger: Logger,
        model: str,
        event_handler,
        port: str,
        baudrate: int = 115200,
        timeout: int = 5,
    ) -> None:
        # Dynamically import ElegooDisplayCommunicator and ElegooDisplayMapper to avoid circular import
        ElegooDisplayCommunicator = importlib.import_module('src.elegoo_display').ElegooDisplayCommunicator
        ElegooDisplayMapper = importlib.import_module('src.elegoo_display').ElegooDisplayMapper
        
        super().__init__(logger, model, port, event_handler, baudrate, timeout)
        self.mapper = ElegooDisplayMapper()
