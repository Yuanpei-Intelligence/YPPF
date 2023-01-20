from boot.config import Config, LazySetting

class __Config(Config):

    def __init__(self, dict_prefix: str = 'library'):
        super().__init__(dict_prefix)
        self.organization_name = LazySetting('organization_name')
        self.start_time = LazySetting('open_time_start')
        self.end_time = LazySetting('open_time_end')

    
library_conf = __Config()