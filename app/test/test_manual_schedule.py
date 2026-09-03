"""
Tests for 手动日程/待办（日程表第5数据源，issue #973 延伸）。

覆盖：
- _occurrence_dates 重复展开与越界校验；
- addScheduleItem：创建单条 / 重复实体化 / 待办 / 非法表单不写库；
- toggleTodo：切换完成态；
- deleteScheduleItem：删单条 / 删整系列；
- 越权：他人不能删除自己的条目（404/403 拒绝）；
- mySchedule：第5源聚合为日历事件、当日待办面板按 ?date 过滤；
- manageSchedule：列出本人的全部条目。
"""
from datetime import date, timedelta

from django.test import TestCase

from app.models import NaturalPerson, User, UserSchedule
from app.schedule_views import (
    _occurrence_dates,
    addScheduleItem,
    deleteScheduleItem,
    editScheduleItem,
    manageSchedule,
    mySchedule,
    toggleTodo,
)


def _make_person(username):
    user = User.objects.create_user(
        username, username, usertype=User.Type.PERSON, password="x")
    user.is_newuser = False
    user.save()
    # NaturalPerson.name 仅 10 字符；MySQL 严格模式下超长会直接报 1406，
    # 故此处截断（SQLite 不校验长度，容易掩盖该问题）。
    return NaturalPerson.objects.create(user, name=username[:10])


class OccurrenceDateTest(TestCase):
    def test_none_returns_single(self):
        d = date(2026, 2, 23)
        self.assertEqual(_occurrence_dates(d, 0, None), [d])

    def test_daily_expands(self):
        base = date(2026, 2, 23)
        end = date(2026, 2, 25)
        dates = _occurrence_dates(base, 1, end)
        self.assertEqual(len(dates), 3)
        self.assertEqual(dates[0], base)
        self.assertEqual(dates[-1], end)

    def test_weekly_expands_by_7(self):
        base = date(2026, 2, 23)  # 周一
        end = date(2026, 3, 9)
        dates = _occurrence_dates(base, 2, end)
        self.assertEqual(dates, [
            date(2026, 2, 23), date(2026, 3, 2), date(2026, 3, 9)])

    def test_repeat_end_before_base_raises(self):
        base = date(2026, 2, 23)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            _occurrence_dates(base, 2, date(2026, 2, 20))


class AddScheduleItemViewTest(TestCase):
    def setUp(self):
        self.me = _make_person("stu_add")
        self.client.force_login(self.me.person_id)

    def _post(self, **data):
        base = {
            'title': '测试日程', 'category': '1', 'date': '2026-02-23',
            'start_time': '08:00', 'end_time': '09:00', 'location': '理教101',
            'note': '', 'color': '#16a085', 'repeat': '0', 'repeat_end': '',
        }
        base.update({k: str(v) for k, v in data.items()})
        return self.client.post('/schedule/addItem/', data=base)

    def test_add_single_schedule(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(UserSchedule.objects.count(), 1)
        item = UserSchedule.objects.first()
        self.assertEqual(item.category, UserSchedule.Category.SCHEDULE.value)
        self.assertEqual(item.start_time.strftime('%H:%M'), '08:00')

    def test_add_recurring_weekly_materializes(self):
        resp = self._post(repeat='2', repeat_end='2026-03-09')
        self.assertEqual(resp.status_code, 302)
        items = list(UserSchedule.objects.filter(person=self.me))
        self.assertEqual(len(items), 3)
        self.assertTrue(all(i.series_id for i in items))
        self.assertEqual(len({i.series_id for i in items}), 1)

    def test_add_todo_ignores_time(self):
        resp = self._post(category='2', start_time='', end_time='')
        self.assertEqual(resp.status_code, 302)
        item = UserSchedule.objects.first()
        self.assertEqual(item.category, UserSchedule.Category.TODO.value)
        self.assertIsNone(item.start_time)
        self.assertIsNone(item.end_time)

    def test_add_invalid_no_title(self):
        resp = self._post(title='')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(UserSchedule.objects.count(), 0)

    def test_add_invalid_end_before_start(self):
        resp = self._post(start_time='09:00', end_time='08:00')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(UserSchedule.objects.count(), 0)

    def test_add_recurring_requires_end(self):
        resp = self._post(repeat='2', repeat_end='')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(UserSchedule.objects.count(), 0)


class ToggleTodoViewTest(TestCase):
    def setUp(self):
        self.me = _make_person("stu_toggle")
        self.client.force_login(self.me.person_id)
        self.todo = UserSchedule.objects.create(
            person=self.me, title='写报告',
            category=UserSchedule.Category.TODO.value, date=date(2026, 2, 23))

    def test_toggle_flips_done(self):
        self.client.post(f'/schedule/toggleTodo/{self.todo.id}/')
        self.assertTrue(UserSchedule.objects.get(id=self.todo.id).done)
        self.client.post(f'/schedule/toggleTodo/{self.todo.id}/')
        self.assertFalse(UserSchedule.objects.get(id=self.todo.id).done)


class DeleteScheduleItemViewTest(TestCase):
    def setUp(self):
        self.me = _make_person("stu_del")
        self.client.force_login(self.me.person_id)

    def _make_series(self):
        base = date(2026, 2, 23)
        sid = 'abc123'
        for i in range(3):
            UserSchedule.objects.create(
                person=self.me, title='周例',
                category=UserSchedule.Category.SCHEDULE.value,
                date=base + timedelta(days=7 * i),
                start_time='08:00', end_time='09:00',
                repeat=UserSchedule.Repeat.WEEKLY.value,
                repeat_end=base + timedelta(days=14), series_id=sid)
        return sid

    def test_delete_single_keeps_series(self):
        sid = self._make_series()
        first = UserSchedule.objects.filter(series_id=sid).first()
        self.client.post(f'/schedule/deleteItem/{first.id}/')
        self.assertEqual(UserSchedule.objects.filter(series_id=sid).count(), 2)

    def test_delete_series_removes_all(self):
        sid = self._make_series()
        first = UserSchedule.objects.filter(series_id=sid).first()
        self.client.post(
            f'/schedule/deleteItem/{first.id}/', data={'delete_series': '1'})
        self.assertEqual(UserSchedule.objects.filter(series_id=sid).count(), 0)


class PermissionTest(TestCase):
    def setUp(self):
        self.a = _make_person("stu_a")
        self.b = _make_person("stu_b")
        self.item = UserSchedule.objects.create(
            person=self.a, title='私有',
            category=UserSchedule.Category.SCHEDULE.value,
            date=date(2026, 2, 23))
        self.client_b = self.client_class()
        self.client_b.force_login(self.b.person_id)

    def test_other_user_cannot_delete(self):
        resp = self.client_b.post(f'/schedule/deleteItem/{self.item.id}/')
        # 归属校验失败：框架返回 403（或 404），但不应成功删除
        self.assertIn(resp.status_code, (403, 404))
        self.assertTrue(UserSchedule.objects.filter(id=self.item.id).exists())


class SchedulePageTest(TestCase):
    def setUp(self):
        self.me = _make_person("stu_page")
        self.client.force_login(self.me.person_id)

    def test_manual_schedule_in_events(self):
        UserSchedule.objects.create(
            person=self.me, title='手动课',
            category=UserSchedule.Category.SCHEDULE.value,
            date=date(2026, 2, 23),
            start_time='10:00', end_time='11:00')
        resp = self.client.get('/schedule/')
        self.assertEqual(resp.status_code, 200)
        events = resp.context['schedule_events']
        manual = [e for e in events if e['category'] == '手动日程']
        self.assertEqual(len(manual), 1)
        self.assertEqual(manual[0]['title'], '手动课')

    def test_todo_panel_filtered_by_date(self):
        d1 = date(2026, 2, 23)
        d2 = date(2026, 2, 24)
        UserSchedule.objects.create(
            person=self.me, title='今天待办',
            category=UserSchedule.Category.TODO.value, date=d1)
        UserSchedule.objects.create(
            person=self.me, title='明天待办',
            category=UserSchedule.Category.TODO.value, date=d2)
        resp = self.client.get(f'/schedule/?date={d1.isoformat()}')
        self.assertEqual(resp.status_code, 200)
        titles = [t.title for t in resp.context['todos']]
        self.assertIn('今天待办', titles)
        self.assertNotIn('明天待办', titles)
        # 日历定位到所选日期
        self.assertEqual(resp.context['selected_date_str'], d1.isoformat())


class ManageScheduleViewTest(TestCase):
    def setUp(self):
        self.me = _make_person("stu_mgr")
        self.client.force_login(self.me.person_id)
        UserSchedule.objects.create(
            person=self.me, title='条目1',
            category=UserSchedule.Category.SCHEDULE.value,
            date=date(2026, 2, 23))
        other = _make_person("stu_other_mgr")
        UserSchedule.objects.create(
            person=other, title='别人的',
            category=UserSchedule.Category.TODO.value,
            date=date(2026, 2, 23))

    def test_manage_lists_only_mine(self):
        resp = self.client.get('/schedule/manage/')
        self.assertEqual(resp.status_code, 200)
        titles = [i.title for i in resp.context['items']]
        self.assertIn('条目1', titles)
        self.assertNotIn('别人的', titles)
