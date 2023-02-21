from utils.config import Config, LazySetting
from boot.config import ROOT_CONFIG


class SchedulerConfig(Config):
    rpc_port = LazySetting('rpc_port', type=int)
    use_scheduler = LazySetting('use_scheduler', default=False)


scheduler_config = SchedulerConfig(ROOT_CONFIG, 'scheduler')
