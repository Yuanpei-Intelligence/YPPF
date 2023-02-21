from utils.config import Config, LazySetting
from boot.config import ROOT_CONFIG

class LibraryConfig(Config):
    organization_name = LazySetting('organization_name', type=str)
    start_time = LazySetting('open_time_start', type=str)
    end_time = LazySetting('open_time_end', type=str)

    
library_conf = LibraryConfig(ROOT_CONFIG, 'library')
