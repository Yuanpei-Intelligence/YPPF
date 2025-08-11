from boot.config import ROOT_CONFIG
from utils.config import Config, LazySetting

__all__ = ['dormitory_config']

class DormitoryConfig(Config):
    routine_qa_survey_id = LazySetting('routine_qa_survey_id', type=int)

dormitory_config = DormitoryConfig(ROOT_CONFIG, 'dormitory')
