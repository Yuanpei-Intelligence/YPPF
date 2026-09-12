'''
Configuration of the rollout app.

Who may use a feature is decided at runtime in the admin site; this module only
holds deployment settings. See ``rollout/README.md``.
'''
from boot.config import ROOT_CONFIG
from utils.config import Config, LazySetting

__all__ = ['CONFIG']


class RolloutConfig(Config):
    # Paths are rooted and every setting has a default, so a config.json that
    # predates the `rollout` section keeps starting with the documented values.
    preview_open = LazySetting(
        'rollout/preview_channel/open', default=True, type=bool)
    feedback_type_name = LazySetting(
        'rollout/feedback/type_name', default='体验反馈', type=str)
    feedback_org_name = LazySetting(
        'rollout/feedback/org_name', default='智慧书院项目组', type=str)


CONFIG = RolloutConfig(ROOT_CONFIG, '')
