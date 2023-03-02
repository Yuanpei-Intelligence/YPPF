from utils.log.logger import Logger

class ExternLogger(Logger):
    def add_default_handler(self, name: str, *paths: str, format: str = '') -> None:
        return super().add_default_handler(name, *paths, format=format)
