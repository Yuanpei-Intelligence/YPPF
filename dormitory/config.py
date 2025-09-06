from boot.config import ROOT_CONFIG
from utils.config import Config, LazySetting

__all__ = ['dormitory_config']

class DormitoryConfig(Config):
    routine_qa_survey_title = LazySetting('routine_qa_survey_title', type=str)

dormitory_config = DormitoryConfig(ROOT_CONFIG, 'dormitory')
