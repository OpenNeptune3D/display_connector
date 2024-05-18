from logging import Logger

from src.elegoo_display import ElegooDisplayCommunicator, ElegooDisplayMapper

MODEL_CUSTOM = "Custom"


class CustomDisplayCommunicator(ElegooDisplayCommunicator):
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
        self.mapper = ElegooDisplayMapper()
