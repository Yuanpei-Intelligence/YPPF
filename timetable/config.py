"""
Configuration of the timetable app (``config.json`` section ``timetable``).

See ``timetable/README.md`` §2. ``CONFIG.sources`` is the event source
registry: every entry is the dotted path of an ``EventSource`` class and
packaging a product means editing that list. Unknown or unimportable entries
are logged and skipped by ``timetable.sources.base.load_sources``.
"""
from boot.config import ROOT_CONFIG
from utils.config import Config, LazySetting
from utils.config.cast import mapping

__all__ = ['TimetableConfig', 'CONFIG']


DEFAULT_SOURCES = [
    'timetable.sources.stored.StoredEntriesSource',
    'timetable.sources.college.CollegeCourseSource',
    'timetable.sources.activity.ActivitySource',
    'timetable.sources.appoint.AppointSource',
]


class TimetableConfig(Config):
    """Settings of the timetable feature."""

    # Dotted paths of the enabled event sources, in legend order.
    sources = LazySetting(
        'sources', mapping(list, str), default=list(DEFAULT_SOURCES), type=list)
    # Default minutes-before-class of a newly created TimetableSettings row.
    reminder_default_minutes = LazySetting(
        'reminder_default_minutes', int, default=20)


CONFIG = TimetableConfig(ROOT_CONFIG, 'timetable')
