"""Override resolution and expansion tests (``timetable/README.md`` §8.2, §8.3)."""
from datetime import date, time

from django.test import SimpleTestCase, TestCase

from timetable import services
from timetable.models import (
    AcademicTerm,
    TimetableEntry,
    TimetableEntryOverride,
    TimetableSettings,
)
from timetable.overrides import (
    applicable_overrides,
    ignore_calendar_false_needed,
    overrides_by_entry,
    resolve_week,
)
from timetable.sources.stored import StoredEntriesSource, expand_entries
from timetable.tests.helpers import WEEK1_MONDAY, make_entry, make_person, make_term


def _term() -> AcademicTerm:
    return AcademicTerm(code='26-27-1', name='t', week1_monday=WEEK1_MONDAY, total_weeks=16)


def _entry(**overrides) -> TimetableEntry:
    fields = {
        'pk': 1, 'source': 'portal', 'external_key': 'k', 'name': '高数',
        'teacher': '张三', 'room': '理教406', 'weekday': 1, 'start_section': 1,
        'end_section': 2, 'start_time': time(8, 0), 'end_time': time(9, 50),
        'week_start': 2, 'week_end': 12, 'parity': 0, 'tag': '必修', 'color': '',
    }
    fields.update(overrides)
    return TimetableEntry(**fields)


def _override(pk, week_start=None, week_end=None, canceled=False, **fields):
    return TimetableEntryOverride(pk=pk, week_start=week_start, week_end=week_end,
                                  canceled=canceled, fields=fields)


class ResolutionTests(SimpleTestCase):
    """Pure resolution over unsaved instances."""

    def setUp(self):
        self.term = _term()
        self.entry = _entry()

    def test_order_wide_to_narrow_then_by_id(self):
        whole = _override(1, name='整学期')
        following = _override(2, 3, None, name='第三周起')
        single = _override(3, 5, 5, name='仅第五周')
        newer_whole = _override(4, name='更新的整学期')
        overrides = [single, newer_whole, following, whole]
        self.assertEqual([o.pk for o in applicable_overrides(self.entry, overrides, 2)], [1, 4])
        self.assertEqual([o.pk for o in applicable_overrides(self.entry, overrides, 4)],
                         [1, 4, 2])
        self.assertEqual([o.pk for o in applicable_overrides(self.entry, overrides, 5)],
                         [1, 4, 2, 3])
        self.assertEqual(applicable_overrides(self.entry, overrides, 13), [])
        self.assertEqual(resolve_week(self.entry, overrides, 2, self.term).values['name'],
                         '更新的整学期')
        self.assertEqual(resolve_week(self.entry, overrides, 4, self.term).values['name'],
                         '第三周起')
        resolved = resolve_week(self.entry, overrides, 5, self.term)
        self.assertEqual(resolved.values['name'], '仅第五周')
        self.assertEqual([o.pk for o in resolved.applied], [1, 4, 2, 3])
        self.assertTrue(resolved.modified)
        untouched = resolve_week(self.entry, [single], 4, self.term)
        self.assertFalse(untouched.modified)
        self.assertEqual(untouched.values['name'], '高数')
        # Open bounds follow the entry's own span: after a re-import narrowed
        # the entry to weeks 4-6 the whole-range override spans 4-6 and the
        # "following" one 3-6 (now the wider of the two).
        self.entry.week_start, self.entry.week_end = 4, 6
        self.assertEqual([o.pk for o in applicable_overrides(self.entry, [whole, following], 3)],
                         [2])
        self.assertEqual([o.pk for o in applicable_overrides(self.entry, [whole, following], 4)],
                         [2, 1])
        self.assertEqual([o.pk for o in applicable_overrides(self.entry, [whole, following], 7)],
                         [])

    def test_canceled_takes_the_last_applied_value(self):
        following = _override(1, 5, None, canceled=True)
        restore = _override(2, 7, 7, canceled=False, room='补课教室')
        fields_only = _override(3, 8, 8, room='另一教室')
        overrides = [following, restore, fields_only]
        self.assertFalse(resolve_week(self.entry, overrides, 4, self.term).canceled)
        self.assertTrue(resolve_week(self.entry, overrides, 5, self.term).canceled)
        self.assertTrue(resolve_week(self.entry, overrides, 6, self.term).canceled)
        week7 = resolve_week(self.entry, overrides, 7, self.term)
        self.assertEqual((week7.canceled, week7.values['room']), (False, '补课教室'))
        week8 = resolve_week(self.entry, overrides, 8, self.term)
        self.assertEqual((week8.canceled, week8.values['room']), (False, '另一教室'))
        self.assertTrue(resolve_week(self.entry, overrides, 9, self.term).canceled)

    def test_values_are_coerced(self):
        moved = _override(1, 3, 3, weekday=3, start_section=5, end_section=6, tag='调课')
        resolved = resolve_week(self.entry, [moved], 3, self.term)
        self.assertEqual((resolved.values['weekday'], resolved.values['start_section'],
                          resolved.values['end_section']), (3, 5, 6))
        # Sections without times derive the times from the term table.
        self.assertEqual((resolved.values['start_time'], resolved.values['end_time']),
                         (time(13, 0), time(14, 50)))
        self.assertEqual(resolved.values['tag'], '调课')
        timed = _override(2, 3, 3, start_time='19:00', end_time='20:30:00', weekday='4')
        resolved = resolve_week(self.entry, [timed], 3, self.term)
        self.assertEqual((resolved.values['start_time'], resolved.values['end_time'],
                          resolved.values['weekday']), (time(19, 0), time(20, 30), 4))
        # Malformed values are ignored; an inverted pair falls back to the entry.
        broken = _override(3, 3, 3, weekday=9, start_section='x', start_time='25:99',
                           end_time='07:00', name=None)
        resolved = resolve_week(self.entry, [broken], 3, self.term)
        self.assertEqual((resolved.values['weekday'], resolved.values['start_section'],
                          resolved.values['start_time'], resolved.values['end_time'],
                          resolved.values['name']), (1, 1, time(8, 0), time(9, 50), ''))
        self.assertTrue(resolved.modified)
        # A non-dict fields value is treated as empty.
        empty = _override(4, 3, 3)
        empty.fields = 'oops'
        self.assertEqual(resolve_week(self.entry, [empty], 3, self.term).values['name'], '高数')

    def test_ignore_calendar_resolves_like_any_key(self):
        """README §11: the last applied boolean wins; it is not one of the values."""
        whole = _override(1, ignore_calendar=True)
        single = _override(2, 5, 5, ignore_calendar=False)
        malformed = _override(3, 7, 7, ignore_calendar='yes')
        overrides = [malformed, single, whole]
        self.assertTrue(resolve_week(self.entry, overrides, 4, self.term).ignore_calendar)
        self.assertFalse(resolve_week(self.entry, overrides, 5, self.term).ignore_calendar)
        self.assertTrue(resolve_week(self.entry, overrides, 7, self.term).ignore_calendar)
        self.assertFalse(resolve_week(self.entry, [single], 4, self.term).ignore_calendar)
        self.assertFalse(resolve_week(self.entry, [], 4, self.term).ignore_calendar)
        resolved = resolve_week(self.entry, overrides, 4, self.term)
        self.assertNotIn('ignore_calendar', resolved.values)
        self.assertEqual((resolved.values['name'], resolved.modified), ('高数', True))

    def test_ignore_calendar_false_needed(self):
        """README §11.4: a false is needed only to beat a true applied before it."""
        whole = _override(1, ignore_calendar=True)
        single = _override(2, 5, 5, ignore_calendar=False)
        self.assertTrue(ignore_calendar_false_needed(self.entry, [whole, single], single))
        # Nothing true before it, or a malformed true: not needed.
        self.assertFalse(ignore_calendar_false_needed(self.entry, [single], single))
        self.assertFalse(ignore_calendar_false_needed(
            self.entry, [_override(3, ignore_calendar='yes')], single))
        # A narrower true inside the range wins its week either way.
        following = _override(4, 4, None, ignore_calendar=False)
        inner = _override(5, 6, 6, ignore_calendar=True)
        self.assertFalse(ignore_calendar_false_needed(self.entry, [inner], following))
        self.assertTrue(ignore_calendar_false_needed(self.entry, [whole, inner], following))
        # Same width (weeks 2-12): the smaller id is applied first, an unsaved row last.
        same_width = _override(6, 2, None, ignore_calendar=False)
        self.assertTrue(ignore_calendar_false_needed(self.entry, [whole], same_width))
        self.assertFalse(ignore_calendar_false_needed(
            self.entry, [_override(7, ignore_calendar=True)], same_width))
        unsaved = _override(None, 2, None, ignore_calendar=False)
        self.assertEqual([o.pk for o in applicable_overrides(self.entry, [unsaved, whole], 3)],
                         [1, None])
        self.assertTrue(ignore_calendar_false_needed(
            self.entry, [_override(7, ignore_calendar=True)], unsaved))
        # A stale copy of the row (same id) is ignored in favour of the row itself.
        stale = _override(2, 5, 5, ignore_calendar=True)
        self.assertFalse(ignore_calendar_false_needed(self.entry, [stale], single))
        # Other keys of the row do not matter.
        roomy = _override(2, 5, 5, room='理教101', ignore_calendar=False)
        self.assertTrue(ignore_calendar_false_needed(self.entry, [whole], roomy))


class ExpansionTests(TestCase):
    """Overrides applied by ``expand_entries`` and the stored source."""

    def setUp(self):
        self.term = make_term()                        # week 1 = 2026-09-14
        _, self.person = make_person()
        self.entry = make_entry(self.person, self.term, name='高数', weekday=1,
                                week_start=1, week_end=8, tag='必修')

    def test_canceled_weekday_move_and_modified(self):
        TimetableEntryOverride.objects.create(entry=self.entry, week_start=2, week_end=2,
                                              fields={'weekday': 3, 'room': '理教101'})
        TimetableEntryOverride.objects.create(entry=self.entry, week_start=4, week_end=None,
                                              canceled=True)
        TimetableEntryOverride.objects.create(entry=self.entry, week_start=6, week_end=6,
                                              canceled=False, fields={'name': '补课'})
        occurrences = expand_entries([self.entry], self.term, 1, 8)
        self.assertEqual([(o.week, o.date.isoformat(), o.weekday, o.title, o.location,
                           o.modified) for o in occurrences], [
            (1, '2026-09-14', 1, '高数', '', False),
            (2, '2026-09-23', 3, '高数', '理教101', True),     # Wednesday of week 2
            (3, '2026-09-28', 1, '高数', '', False),
            (6, '2026-10-19', 1, '补课', '', True),
        ])
        self.assertEqual(occurrences[1].id, f'portal:{self.entry.pk}:2026-09-23')
        self.assertEqual((occurrences[0].role, occurrences[0].tag), ('enrolled', '必修'))
        self.assertEqual(occurrences[1].as_dict()['modified'], True)

    def test_overrides_by_entry_and_prefetch(self):
        other = make_entry(self.person, self.term, name='英语', weekday=2)
        TimetableEntryOverride.objects.create(entry=self.entry, week_start=2, week_end=2,
                                              fields={'room': 'a'})
        with self.assertNumQueries(1):
            by_entry = overrides_by_entry([self.entry, other])
        self.assertEqual({pk: len(items) for pk, items in by_entry.items()},
                         {self.entry.pk: 1, other.pk: 0})
        entries = list(TimetableEntry.objects.filter(person=self.person)
                       .prefetch_related('overrides'))
        with self.assertNumQueries(0):
            by_entry = overrides_by_entry(entries)
        self.assertEqual(sorted(by_entry), sorted([self.entry.pk, other.pk]))
        self.assertEqual(overrides_by_entry([]), {})

    def test_stored_source_skips_hidden_tags(self):
        make_entry(self.person, self.term, name='选修', weekday=2, tag='选修')
        TimetableEntryOverride.objects.create(entry=self.entry, week_start=2, week_end=2,
                                              fields={'tag': '调课'})
        source = StoredEntriesSource()
        settings = TimetableSettings(person=self.person, hidden_tags=['必修'])
        occurrences = source.occurrences(self.person, self.term, 1, 2, settings)
        # Week 1 高数 (tag 必修) is hidden; week 2 carries the overridden tag 调课.
        self.assertEqual([(o.title, o.week, o.tag) for o in occurrences],
                         [('选修', 1, '选修'), ('高数', 2, '调课'), ('选修', 2, '选修')])
        settings.hidden_tags = ['选修', '调课']
        occurrences = source.occurrences(self.person, self.term, 1, 2, settings)
        self.assertEqual([(o.title, o.week) for o in occurrences], [('高数', 1)])
        settings.hidden_tags = 'not-a-list'
        self.assertEqual(len(source.occurrences(self.person, self.term, 1, 2, settings)), 4)
        self.assertEqual(len(source.occurrences(self.person, self.term, 1, 2, None)), 4)


class UpdateEntryTests(TestCase):
    """``services.update_entry`` (the domain side of scoped edits)."""

    def setUp(self):
        self.term = make_term()
        _, self.person = make_person()
        self.imported = make_entry(self.person, self.term, name='高数', weekday=1)
        self.manual = make_entry(self.person, self.term, name='自习', weekday=2,
                                 source=TimetableEntry.Source.MANUAL)

    def test_scope_all(self):
        services.update_entry(self.manual, {'name': '晚自习', 'tag': 't', 'weekday': 5,
                                            'start_time': time(19, 0), 'end_time': time(21, 0)})
        self.manual.refresh_from_db()
        self.assertEqual((self.manual.name, self.manual.tag, self.manual.weekday,
                          self.manual.start_time), ('晚自习', 't', 5, time(19, 0)))
        self.assertEqual(self.manual.overrides.count(), 0)
        services.update_entry(self.imported, {'name': '高等数学', 'tag': 't', 'hidden': True,
                                              'start_time': time(19, 0), 'end_time': time(21, 0)})
        self.imported.refresh_from_db()
        self.assertEqual((self.imported.name, self.imported.tag, self.imported.hidden),
                         ('高数', 't', True))
        override = self.imported.overrides.get()
        self.assertEqual((override.week_start, override.week_end, override.fields),
                         (None, None, {'name': '高等数学', 'start_time': '19:00',
                                       'end_time': '21:00'}))
        services.update_entry(self.imported, {'room': 'r'})
        self.assertEqual(self.imported.overrides.get().fields['room'], 'r')
        self.assertEqual(self.imported.overrides.count(), 1)
        with self.assertRaises(ValueError):
            services.update_entry(self.imported, {'week_start': 3})
        with self.assertRaises(ValueError):
            services.update_entry(self.imported, {}, canceled=True)

    def test_single_and_following(self):
        services.update_entry(self.imported, {'room': 'a'}, scope='single', week=3)
        services.update_entry(self.imported, {'tag': 'x'}, scope='following', week=4,
                              canceled=True)
        services.update_entry(self.imported, {}, scope='single', week=3, canceled=True)
        rows = [(o.week_start, o.week_end, o.canceled, o.fields)
                for o in self.imported.overrides.order_by('id')]
        self.assertEqual(rows, [(3, 3, True, {'room': 'a'}), (4, None, True, {'tag': 'x'})])
        for kwargs in ({'scope': 'single'}, {'scope': 'single', 'week': 17},
                       {'scope': 'weekly', 'week': 2}):
            with self.assertRaises(ValueError):
                services.update_entry(self.imported, {'room': 'b'}, **kwargs)
        with self.assertRaises(ValueError):
            services.update_entry(self.imported, {'hidden': True}, scope='single', week=2)
        self.assertEqual(self.imported.overrides.count(), 2)

    def test_ignore_calendar_always_lands_in_an_override(self):
        """README §11: even a manual entry keeps 照常上课 off the row, in any scope."""
        services.update_entry(self.manual, {'ignore_calendar': True, 'room': '图书馆'})
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.room, '图书馆')
        override = self.manual.overrides.get()
        self.assertEqual((override.week_start, override.week_end, override.canceled,
                          override.fields), (None, None, False, {'ignore_calendar': True}))
        services.update_entry(self.imported, {'ignore_calendar': 1}, scope='single', week=3)
        services.update_entry(self.imported, {'ignore_calendar': True},
                              scope='following', week=5)
        # A false that beats a wider true is stored in its own override.
        services.update_entry(self.imported, {'ignore_calendar': False},
                              scope='single', week=6)
        self.assertEqual([(o.week_start, o.week_end, o.fields)
                          for o in self.imported.overrides.order_by('id')],
                         [(3, 3, {'ignore_calendar': True}),
                          (5, None, {'ignore_calendar': True}),
                          (6, 6, {'ignore_calendar': False})])

    def test_ignore_calendar_false_leaves_no_trace(self):
        """README §11.4: undoing 照常上课 removes the key where nothing wider is true."""
        def rows(entry):
            return [(o.week_start, o.week_end, o.canceled, o.fields)
                    for o in entry.overrides.order_by('id')]

        def modified(entry, week):
            return [o.modified for o in expand_entries([entry], self.term, week, week)]

        for scope, week in (('single', 3), ('following', 3), ('all', None)):
            with self.subTest(scope=scope):
                services.update_entry(self.imported, {'ignore_calendar': True},
                                      scope=scope, week=week)
                self.assertEqual(modified(self.imported, 3), [True])
                services.update_entry(self.imported, {'ignore_calendar': False},
                                      scope=scope, week=week)
                self.assertEqual(rows(self.imported), [])
                self.assertEqual(modified(self.imported, 3), [False])
        services.update_entry(self.manual, {'ignore_calendar': True})
        services.update_entry(self.manual, {'ignore_calendar': False})
        self.assertEqual(rows(self.manual), [])
        # A false with nothing to undo creates no override.
        services.update_entry(self.imported, {'ignore_calendar': False}, scope='single', week=4)
        services.update_entry(self.imported, {'ignore_calendar': False}, scope='following', week=4)
        self.assertEqual(rows(self.imported), [])
        # Other keys and canceled stay, and so does modified.
        services.update_entry(self.imported, {'room': '理教101', 'ignore_calendar': True},
                              scope='single', week=3)
        services.update_entry(self.imported, {'ignore_calendar': False}, scope='single', week=3)
        services.update_entry(self.imported, {'ignore_calendar': True}, scope='following', week=6)
        services.update_entry(self.imported, {'ignore_calendar': False}, scope='following',
                              week=6, canceled=True)
        self.assertEqual(rows(self.imported),
                         [(3, 3, False, {'room': '理教101'}), (6, None, True, {})])
        self.assertEqual(modified(self.imported, 3), [True])
        self.assertEqual(modified(self.imported, 6), [])
