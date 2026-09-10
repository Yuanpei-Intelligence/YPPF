# Timetable (课表) — design and contract

This document is the single source of truth for the timetable feature set:
the `pku_account`, `timetable` and (later) `academic_record` Django apps, their
mini-program API under `api/`, and the YPPF-mini pages that consume it.
Three tracks are implemented in parallel against this contract; if you need
to change the contract, change this file first.

Product goals (from the 2026-09 requirement pool): a personal timetable in the
mini-program that merges 学校课程 (PKU 教务课表) with 书院课 and other YPPF
events; import that is automatic (portal fetch) with zero-credential
fallbacks; a shareable poster; ICS export; class reminders; grade lookup with
opt-in storage. Everything must stay **pluggable**: each data source and each
optional module can be switched off through `config.json` without leaving
dead code paths behind, so products can be packaged from subsets.

## 1. Module dependency graph

```
generic.User / app.NaturalPerson / semester          (existing YPPF core)
        ▲                       ▲
        │                       │
   pku_account ◄──────── timetable ◄──── api/timetable, timetable.reminders (S2)
   (IAAA + portal client,   (terms, stored entries, sources,
    binding, session vault)  week view, import, ICS)
        ▲                       ▲
        │                       │ (live adapters, optional)
   academic_record (S2)     app.Course / app.Activity / Appointment.Appoint
   (grades, consent-gated)
```

Rules:

- `pku_account` depends only on `generic.User` (+ `NaturalPerson` for the
  "person" check). It knows nothing about courses or grades.
- `timetable` core (`models.py`, `services.py`, `sources/stored.py`,
  `sources/pku_parsers.py`, `ics.py`) depends on `generic`, `app.NaturalPerson`
  and `pku_account`. Adapters under `timetable/sources/` that read other apps
  (`college.py`, `activity.py`, `appoint.py`) import those apps **lazily inside
  functions** and are only loaded when listed in `config.json → timetable.sources`.
- Nothing in `app/`, `Appointment/` etc. imports `timetable` or `pku_account`.
  Consumers such as 学术地图 / 综测 read through `timetable.services` later.
- `academic_record` (sprint 2) depends on `pku_account` only.

## 2. Configuration (`config.json`)

```json
"pku_portal": {
    "enabled": false,          // safe default; set true per deployment (login answers PORTAL_DISABLED while false)
    "session_key": "",           // Fernet key (urlsafe base64, 32 bytes). Empty → derived from SECRET_KEY
    "timeout": 15,               // seconds per HTTP call
    "max_login_failures": 5,     // per binding, then locked for lock_seconds
    "lock_seconds": 900
},
"timetable": {
    "sources": [
        "timetable.sources.stored.StoredEntriesSource",
        "timetable.sources.college.CollegeCourseSource",
        "timetable.sources.activity.ActivitySource",
        "timetable.sources.appoint.AppointSource",
        "timetable.sources.exam.ExamSource"          // §8.4
    ],
    "reminder_default_minutes": 20
}
```

Each app exposes `CONFIG` through `<app>/config.py` built on
`utils.config.Config` / `LazySetting` (same pattern as `api/config.py`).
`timetable.config.CONFIG.sources` is the source registry; packaging a product
means editing that list. Unknown/unimportable entries are logged and skipped,
never fatal.

## 3. `pku_account`

### 3.1 External client (`pku_account/extern/`)

Pure `requests` code, no Django models. Mirrors what public tools do
(pkuhelper-web-score, Packup-Android):

```
POST https://iaaa.pku.edu.cn/iaaa/oauthlogin.do
     form: appid=portal2017, userName, password,
           redirUrl=https://portal.pku.edu.cn/portal2017/ssoLogin.do
     headers: Referer=https://iaaa.pku.edu.cn/iaaa/oauth.jsp?appID=portal2017&...
     → JSON {"success": true, "token": "..."}  |  {"success": false, "errors": {"code": "...", "msg": "..."}}
GET  https://portal.pku.edu.cn/portal2017/ssoLogin.do?_rand=<random>&token=<token>
     → sets portal session cookies (follow redirects; keep every Set-Cookie)
GET  https://portal.pku.edu.cn/portal2017/bizcenter/course/getCourseInfo.do?xndxq=26-27-1
     → {"success": true, "remark": "...", "course": [ {"timeNum": "第一节",
          "mon": {"courseName": "...", "parity": "...", "sty": "..."}, "tue": {...}, ... "sun": {...}} , ... ]}
GET  https://portal.pku.edu.cn/portal2017/bizcenter/score/retrScores.do
     → {"cjxx": [ {"xnd": "25-26", "xq": "1", "list": [ {"kcmc", "kch", "xf", "xqcj", "jd", ...} ]} ], ...}
```

The portal returns an HTML login page (not JSON) once the session is gone:
treat "response is not JSON" as `PortalSessionExpired`. IAAA responses whose
`errors.msg` mention 验证码 / OTP / 二次验证 map to `CaptchaRequired` /
`OtpRequired` (both subclasses of `IaaaError`). Off-campus logins require OTP
since 2026-03-30; the production server is on campus, so this is only an
edge case to report cleanly, not to solve.

```python
# pku_account/extern/iaaa.py
class IaaaError(Exception):      code: str; msg: str
class OtpRequired(IaaaError): ...
class CaptchaRequired(IaaaError): ...
def iaaa_login(session, username, password, *, appid='portal2017', redir_url=PORTAL_SSO) -> str  # token

# pku_account/extern/portal.py
class PortalSessionExpired(Exception): ...
class PortalClient:
    @classmethod
    def login(cls, username, password) -> 'PortalClient'
    @classmethod
    def from_cookies(cls, cookies: dict[str, str]) -> 'PortalClient'
    def cookies(self) -> dict[str, str]
    def get_course_info(self, term_code: str) -> dict
    def get_scores(self) -> dict
    def ping(self) -> bool            # cheap liveness probe, never raises
```

Never log usernames+passwords, tokens or cookies. Timeouts from config.

### 3.2 Models

```python
class PkuAccount(models.Model):
    user = OneToOneField(User, related_name='pku_account')
    pku_username = CharField(max_length=32, unique=True, db_index=True)
    verified_at = DateTimeField()                 # first successful IAAA login
    last_login_at = DateTimeField(null=True)      # last successful IAAA login
    last_sync_at = DateTimeField(null=True)       # last successful data fetch by any consumer
    login_failures = PositiveSmallIntegerField(default=0)
    locked_until = DateTimeField(null=True, blank=True)
    consent_timetable = BooleanField(default=False); consent_timetable_at = DateTimeField(null=True)
    consent_grades = BooleanField(default=False);    consent_grades_at = DateTimeField(null=True)
    created_at = DateTimeField(auto_now_add=True)

class PkuPortalSession(models.Model):
    account = OneToOneField(PkuAccount, related_name='portal_session')
    cookies_encrypted = BinaryField()             # Fernet(json.dumps(cookies))
    created_at = DateTimeField(auto_now_add=True)
    last_ok_at = DateTimeField(null=True)
    last_checked_at = DateTimeField(null=True)
    invalid = BooleanField(default=False)
    invalid_reason = CharField(max_length=64, blank=True)
```

Passwords are **never persisted** server-side (not even encrypted). What is
kept is the portal session cookie jar, encrypted with Fernet
(`pku_account/crypto.py`; key = `pku_portal.session_key` or
`sha256(SECRET_KEY)` urlsafe-b64). The mini-program may keep the password on
the device if the student opts in; the server only ever sees it inside one
login request.

### 3.3 Services (`pku_account/services.py`)

```python
class SessionUnavailable(Exception): ...          # no binding, or session invalid

def login_and_bind(user, username, password, *, consent_timetable=None, consent_grades=None) -> PkuAccount
    # enforces locked_until / login_failures, calls PortalClient.login, upserts PkuAccount
    # (pku_username unique → 409-style ValueError if bound to another user), stores session, resets failures
def get_binding(user) -> PkuAccount | None
def get_client(user) -> PortalClient              # raises SessionUnavailable
def mark_session_ok(account) / invalidate_session(account, reason)
def update_consents(user, *, timetable=None, grades=None) -> PkuAccount
def unbind(user) -> None                          # deletes binding + session
def binding_payload(account_or_none) -> dict      # the JSON shape used by the API (see 3.4)
```

`get_client` decrypts cookies and returns a client; callers that hit
`PortalSessionExpired` must call `invalidate_session` and surface
`PKU_LOGIN_REQUIRED` (see API errors).

### 3.4 API — `/api/v2/pku/` (`api/pku_account/`)

Auth: `WxJWTAuthentication` + `IsAuthenticated`, persons only (403 for org
accounts). Tags: `['北大账号']`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `binding/` | – | `Binding` |
| POST | `login/` | `{username, password, consent_timetable?, consent_grades?}` | 200 `Binding` |
| POST | `unbind/` | – | 204 |
| PATCH | `consents/` | `{timetable?: bool, grades?: bool}` | 200 `Binding` |

```ts
interface Binding {
  bound: boolean
  pku_username: string | null
  verified_at: string | null
  last_login_at: string | null
  last_sync_at: string | null
  session: { alive: boolean | null; last_ok_at: string | null; invalid_reason: string }
  consents: { timetable: boolean; grades: boolean }
  locked_until: string | null
}
```

Errors are `{code, message}` with HTTP 400 unless noted:
`IAAA_ERROR` (wrong password etc., message = IAAA msg), `OTP_REQUIRED`,
`CAPTCHA_REQUIRED`, `LOCKED` (429), `ALREADY_BOUND_ELSEWHERE` (409),
`PORTAL_DISABLED` (503 when `pku_portal.enabled` is false). `message` is what
the mini-program shows (its `http.ts` reads `message`).

## 4. `timetable`

### 4.1 Models

```python
class AcademicTerm(models.Model):
    code = CharField(max_length=16, unique=True)        # portal xndxq: '26-27-1' (1 秋, 2 春, 3 夏)
    name = CharField(max_length=32)                     # '2026-2027学年秋季学期'
    week1_monday = DateField()                          # Monday of teaching week 1
    total_weeks = PositiveSmallIntegerField(default=16)
    section_times = JSONField(default=default_section_times)   # {"1": ["08:00", "08:50"], ...}
    is_active = BooleanField(default=True)

    @classmethod
    def current(cls, on: date | None = None) -> 'AcademicTerm | None'
        # latest active term with week1_monday <= on; None if none
    def week_of(self, on: date) -> int                 # 1-based; may be <1 or >total_weeks
    def date_of(self, week: int, weekday: int) -> date  # weekday 1=Mon..7=Sun
    def yppf_year_semester(self) -> tuple[int, Semester] | None   # ('26-27-1') -> (2026, Semester.FALL); -2 -> (2026, SPRING); -3 -> None

class TimetableEntry(models.Model):
    class Source(TextChoices): PORTAL='portal'; PASTE='paste'; MANUAL='manual'
    class Parity(IntegerChoices): ALL=0; ODD=1; EVEN=2
    person = FK(NaturalPerson, related_name='timetable_entries')
    term = FK(AcademicTerm, on_delete=PROTECT)
    source = CharField(choices=Source)
    external_key = CharField(max_length=64)   # sha1 of normalised fields (portal/paste), uuid4 hex (manual)
    name, course_code(blank), class_no(blank), teacher(blank), room(blank)   # CharFields
    weekday = SmallInt (1..7)
    start_section, end_section = SmallInt (1..12; 0 allowed for manual entries with explicit times)
    start_time, end_time = TimeField
    week_start, week_end = SmallInt; parity = SmallInt(choices=Parity, default=ALL)
    note = CharField(200, blank); raw_text = TextField(blank)
    hidden = BooleanField(default=False); color = CharField(7, blank)
    created_at / updated_at
    class Meta: unique_together = ('person', 'term', 'source', 'external_key'); ordering = ['weekday', 'start_section']

class ImportLog(models.Model):
    person, term, source, status ('ok'|'failed'), entries_count, message(blank), created_at

class TimetableSettings(models.Model):
    person = OneToOneField(NaturalPerson, related_name='timetable_settings')
    ics_token = UUIDField(default=uuid4, unique=True)
    reminder_enabled = BooleanField(default=False); reminder_minutes = PositiveSmallIntegerField(default=20)
    show_college = BooleanField(default=True); show_activities = BooleanField(default=True)
    show_appointments = BooleanField(default=True); share_show_name = BooleanField(default=True)
```

`default_section_times` is the PKU 校本部 50-minute table (verified against
xmcp/pku-syllabus): 1 08:00–08:50, 2 09:00–09:50, 3 10:10–11:00,
4 11:10–12:00, 5 13:00–13:50, 6 14:00–14:50, 7 15:10–16:00, 8 16:10–17:00,
9 17:10–18:00, 10 18:40–19:30, 11 19:40–20:30, 12 20:40–21:30.

Stored data is per (person, term). Re-import replaces the set for
(person, term, source) via upsert on `external_key` and deletes entries of
that source that disappeared; other sources are untouched; older terms are
never touched. This is the durable record other modules may read later.

Management command `timetable_seed_terms` creates `AcademicTerm` rows from
`semester.Semester` when present (`start_date` → `week1_monday` aligned to
Monday; `type.name` 秋/春 → suffix 1/2) and is idempotent; admins can also
create terms in Django admin.

### 4.2 Parsers (`timetable/sources/pku_parsers.py`) — pure functions, stdlib only

```python
@dataclass
class LessonBlock:
    name: str; teacher: str = ''; room: str = ''; course_code: str = ''; class_no: str = ''
    weekday: int = 0                     # 1..7
    start_section: int = 0; end_section: int = 0
    week_start: int = 1; week_end: int = 16; parity: int = 0   # 0 all, 1 odd, 2 even
    note: str = ''                       # portal 备注, stored in TimetableEntry.note
    raw: str = ''

def parse_course_cell_text(text) -> list[dict]      # '课名(主)\n上课信息：1-16周 每周 理教201 教师：张三 备注：…\n考试信息：…'
def parse_portal_course_json(raw: dict) -> list[LessonBlock]   # getCourseInfo.do; merge consecutive sections
def parse_portal_html(html: str) -> list[LessonBlock]          # portal 我的课表 page, cells id="mon1".."sun12"
def parse_elective_table(text: str) -> list[LessonBlock]       # elective.pku.edu.cn 选课结果 (HTML or plain text)
                                                                # time regex: (\d+)~(\d+)周 (.)周周(.)(\d+)~(\d+)节\s*(\S*)
def detect_format(text: str) -> str                             # 'portal_html' | 'portal_json' | 'elective' | 'unknown'
def external_key(block: LessonBlock) -> str                     # sha1 over name/weekday/sections/week range/parity
                                                                # (room and teacher excluded, so a room change is an
                                                                #  update of the same entry, not delete + create)
```

Merging rule (portal JSON/HTML): consecutive sections on the same weekday with
identical (name, week_start, week_end, parity, room, teacher) collapse into one
block. A cell may carry several 上课信息 lines (different week ranges) →
several blocks.

### 4.3 Sources (`timetable/sources/`)

```python
@dataclass
class Occurrence:
    id: str                 # stable: f'{source}:{key}:{date}'
    source: str             # 'portal' | 'paste' | 'manual' | 'college' | 'activity' | 'appoint'
    kind: str               # 'course' (school course), 'college' (书院课), 'activity', 'appoint', 'custom'
    title: str; subtitle: str = ''; location: str = ''
    start: datetime; end: datetime
    date: date; week: int; weekday: int
    start_section: int | None = None; end_section: int | None = None
    color_key: str = ''     # stable colouring key (course name or id)
    status: str = ''        # '' | 'canceled' | 'checked_in' | 'applied'
    ref: dict = field(default_factory=dict)   # {'entry_id'} | {'course_id','activity_id'} | {'activity_id'} | {'appoint_id'}
    hidden: bool = False

class EventSource(Protocol):
    key: str; label: str
    def occurrences(self, person, term, week_from, week_to, settings) -> list[Occurrence]: ...

def load_sources() -> list[EventSource]     # from CONFIG.sources, cached, import errors logged & skipped
```

- `stored.StoredEntriesSource` expands `TimetableEntry` rows (sections →
  times from `term.section_times`, parity, week range). `kind='course'` for
  portal/paste, `'custom'` for manual.
- `college.CollegeCourseSource` (needs `app`): 书院课 the person selected
  (`CourseParticipant.status == SUCCESS`) in the YPPF semester that matches
  `term.yppf_year_semester()`. For each `CourseTime` and each week: if a
  generated `Activity` (category `COURSE`, `course_time=ct`) starts in that
  week, use its real `start/end/location/status` (exclude canceled/aborted,
  `status='checked_in'` if the person's `Participation` is ATTENDED);
  otherwise expand `ct.start + 7*k days` for `k in range(ct.cur_week, ct.end_week)`.
  `ref = {'course_id', 'activity_id' (or None)}`, subtitle = course teacher or
  organization name. Honour `settings.show_college`.
- `activity.ActivitySource` (needs `app`): activities the person applied to
  (`Participation` in APPLYSUCCESS/ATTENDED/UNATTENDED, activity not COURSE
  category, not canceled/rejected) starting inside the week range.
  `ref={'activity_id'}`, `kind='activity'`. Honour `settings.show_activities`.
- `appoint.AppointSource` (needs `Appointment`): non-cancelled `Appoint`
  rows where the person's `User` is `major_student` or in `students`.
  Title `地下室 <room>`, `ref={'appoint_id'}`. Honour `settings.show_appointments`.

### 4.4 Services (`timetable/services.py`)

```python
def get_or_create_settings(person) -> TimetableSettings
def week_view(person, term, week) -> dict     # see API 4.6 for the shape
def import_portal(person, term, raw_json) -> ImportResult          # parse + upsert source=PORTAL
def import_text(person, term, text, *, dry_run=False) -> ImportResult | list[LessonBlock]
def upsert_entries(person, term, source, blocks) -> ImportResult   # shared by the two above
def expand_entries(entries, term, week_from, week_to) -> list[Occurrence]
def detect_conflicts(occurrences) -> list[list[str]]               # groups of overlapping occurrence ids (same date)
def build_ics(person) -> str                                       # timetable/ics.py; current + future active terms

@dataclass
class ImportResult: created: int; updated: int; removed: int; entries: list[TimetableEntry]; log: ImportLog
```

`import_portal` is called by the API after it obtained raw JSON through
`pku_account.services.get_client(user).get_course_info(term.code)`; the
timetable app never touches credentials.

### 4.5 ICS feed

`GET /timetable/ics/<token>.ics` (root-level route in `timetable/urls.py`,
no auth, token = `TimetableSettings.ics_token`). `text/calendar; charset=utf-8`,
`Cache-Control: private, max-age=3600`. One `VEVENT` per occurrence (no
RRULE; ~200 events per term is fine), `X-WR-CALNAME: 元培课表`,
`TZID=Asia/Shanghai`. Rotating the token (API) invalidates the old URL.

### 4.6 API — `/api/v2/timetable/` (`api/timetable/`)

Auth as in §3.4. Tags `['课表']`. All dates ISO 8601, times `HH:MM`, datetimes
naive local (`YYYY-MM-DDTHH:MM:SS`, Asia/Shanghai — YPPF runs with
`USE_TZ=False`).

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `terms/` | – | `{current: Term \| null, terms: Term[]}` |
| GET | `week/` | `?term=<code>&week=<n>` (both optional → current term / current week, clamped to 1..total_weeks) | `WeekView` |
| GET | `entries/` | `?term=<code>` | `Entry[]` |
| POST | `entries/` | `EntryIn` (manual) | 201 `Entry` |
| PATCH | `entries/{id}/` | partial `EntryIn` + `hidden` (`hidden` allowed for any source; other fields only for manual) | `Entry` |
| DELETE | `entries/{id}/` | manual only | 204 |
| POST | `import/portal/` | `{term?, username?, password?, consent_timetable?}` | `ImportOut` |
| POST | `import/text/` | `{term?, text, dry_run?}` | dry run: `{format, blocks: LessonBlock[]}`; else `ImportOut` |
| GET | `settings/` | – | `Settings` |
| PATCH | `settings/` | partial `Settings` (not `ics_token`) | `Settings` |
| GET | `ics/` | – | `{url, token}` (absolute URL via `utils.http.utils.build_full_url`) |
| POST | `ics/rotate/` | – | `{url, token}` |

Defaults and errors: the default term is `AcademicTerm.current()` or, before
the first term starts, the nearest upcoming active term; with no usable term
`terms/` returns `current: null` and the other endpoints answer 404
`NO_CURRENT_TERM`; an unknown `term` code answers 404 `TERM_NOT_FOUND`. A
portal payload with `success: false` or zero courses, and pasted text that
yields no blocks, answer 400 `PARSE_FAILED` and leave existing entries
untouched (a failed `ImportLog` is written); a dry run on unrecognised text
answers 200 `{format: 'unknown', blocks: []}`. Hidden entries are excluded
from `week/` and from the ICS feed but still listed by `entries/` so they can
be un-hidden. Every error body is `{code, message}`; validation errors add
`errors: {field: [{code, message}]}` — the same item shape as the
platform-wide envelope of `api/exceptions.py` (YPPF PR #1014) and of the
mini-program's unified `RequestError` (YPPF-mini PR #10). Once #1014 is
merged these modules should adopt `StandardizedExceptionHandlerMixin` /
`APIError` instead of their local mixins (mechanical change; codes stay).

```ts
interface Term { code: string; name: string; week1_monday: string; total_weeks: number;
                 current_week: number | null; section_times: Record<string, [string, string]> }
interface WeekView {
  term: Term; week: number; week_dates: string[]          // 7 ISO dates Mon..Sun
  today: { date: string; weekday: number; week: number | null }
  occurrences: Occurrence[]; conflicts: string[][]
  sources: { key: string; label: string }[]              // legend, only sources that are enabled
}
interface Occurrence { id: string; source: string; kind: 'course'|'college'|'activity'|'appoint'|'custom';
  title: string; subtitle: string; location: string; start: string; end: string; date: string;
  week: number; weekday: number; start_section: number | null; end_section: number | null;
  color_key: string; status: string; ref: Record<string, number | null>; hidden: boolean }
interface Entry { id: number; term: string; source: 'portal'|'paste'|'manual'; name: string; course_code: string;
  class_no: string; teacher: string; room: string; weekday: number; start_section: number; end_section: number;
  start_time: string; end_time: string; week_start: number; week_end: number; parity: 0|1|2;
  note: string; hidden: boolean; color: string }
type EntryIn = Omit<Entry, 'id'|'source'|'term'> & { term?: string }   // start/end_time optional when sections given
interface ImportOut { term: string; created: number; updated: number; removed: number; total: number }
interface Settings { reminder_enabled: boolean; reminder_minutes: number; show_college: boolean;
  show_activities: boolean; show_appointments: boolean; share_show_name: boolean }
```

`import/portal/` flow: if `username`+`password` given → `pku_account.services.login_and_bind`
(with `consent_timetable=True` implied) then fetch; else → `get_client(user)`;
`SessionUnavailable`/`PortalSessionExpired` → **409** `{code: 'PKU_LOGIN_REQUIRED', message}`.
IAAA errors propagate with the same codes as §3.4. Requires
`consent_timetable` on the binding; otherwise 403 `{code: 'CONSENT_REQUIRED'}`.
On success update `PkuAccount.last_sync_at`.

## 5. Mini-program (YPPF-mini) — pages and behaviour

Contract files: `src/api/types/pku.ts`, `src/api/pku.ts`,
`src/api/types/timetable.ts`, `src/api/timetable.ts` (same style as
`src/api/notification.ts`: `http.get/post/patch/delete` with `/api/v2/...`).

Pages (all behind login, `definePage` style like `pages/me/notifications.vue`):

- `pages/timetable/index.vue` — the timetable. Week grid: 7 columns
  (Mon..Sun, dates under headers, today highlighted) × 12 section rows with
  times from `term.section_times`; occurrences positioned by sections (or by
  time for custom entries). Header: term name, week picker (‹ › + “本周”).
  Colours: deterministic palette hashed from `color_key`; `kind` shown as a
  small badge/border (书院课 / 活动 / 预约). Tap → `uv-popup` detail
  (title, time, location, subtitle, status) with actions by kind:
  `college`/`activity` → “查看活动 / 签到” (`/pages/activity/detail?id=<activity_id>`,
  college without activity_id → toast “本周活动尚未发布”), `appoint` →
  `/pages/me/my-appointments`, `custom` → 编辑, any → 隐藏. Empty state
  (no occurrences at all in the term) → CTA to import. Cache the last
  `WeekView` in `uni.setStorageSync` for instant paint; refresh on show.
  `onShareAppMessage` → `{ title: '我的课表', path: '/pages/timetable/index' }`.
  Menu (navbar right or bottom bar): 导入 / 海报 / 设置.
- `pages/timetable/import.vue` — three sections. (1) 北大账号: binding status
  from `GET /api/v2/pku/binding/`; form 学号 + 密码 + consent checkbox
  (“我同意智慧书院使用我的门户课表数据，密码仅用于本次登录，不会被保存”) +
  optional “本机记住密码（仅存本手机）” toggle (`uni.setStorageSync('pku_cred')`);
  primary button 登录并导入 → `POST import/portal/` with credentials; when a
  live session exists show 立即刷新 instead (no credentials); on 409
  `PKU_LOGIN_REQUIRED` retry silently with stored credentials if any, else show
  the form. Also 解除绑定. (2) 粘贴导入: textarea + 解析预览 (`dry_run`)
  → list of parsed blocks → 确认导入. Include short instructions for
  selecting the 选课结果 table on elective.pku.edu.cn or saving the portal
  page. (3) 手动添加 → `entry-form`. Settings toggles (show_college/…)
  and ICS link copy (`uni.setClipboardData`) live at the bottom.
- `pages/timetable/entry-form.vue?id=` — create/edit a manual entry
  (name, weekday, start/end section pickers, week range, parity, room,
  teacher, note); delete for existing.
- `pages/timetable/poster.vue` — canvas (type="2d") poster of the current
  week/term grid with name (respecting `share_show_name`), term + week label
  and a footer “元培智慧书院 · 课表”; 保存到相册 via `uni.canvasToTempFilePath`
  + `uni.saveImageToPhotosAlbum` (handle denied auth with `uni.openSetting`).
- Entry points: home (`pages/index/index.vue`) quick entry “课表”, and a
  “我的课表” item in `pages/me/me.vue`.

Error display uses the message returned by the API (`http.ts` already
formats `{message}`); never echo passwords back.

## 6. Sprint 2 — reminders, grades, course catalog

Same rules as above: every piece is optional, switched by `config.json`, and
depends only downwards (`academic_record` → `pku_account`; reminders → the
notification system; nothing in `app/` learns about them).

### 6.1 Class reminders (`timetable/reminders.py`, `timetable/jobs.py`, `extern/wx_miniapp.py`)

Channel order: WeChat mini-program **subscribe message** when a template is
configured and the user has quota, otherwise 站内通知 + the existing WeChat
push (`app.notification_utils.notification_create(..., to_wechat=True)`).

```json
"wx_miniapp": {
    ...,
    "subscribe_templates": {
        "class_reminder": {
            "id": "",                                   // template id from mp.weixin.qq.com; empty → channel disabled
            "fields": {"course": "thing1", "time": "time2", "location": "thing3", "note": "thing4"},
            "page": "pages/timetable/index"
        }
    }
},
"timetable": { ..., "reminder_default_minutes": 20, "reminder_lookahead_minutes": 60, "subscribe_quota_cap": 50 }
```

Models (in `timetable/models.py`):

```python
class SubscribeQuota(models.Model):       # accepted-but-unused subscribe grants, per template key
    user = FK(User); template_key = CharField(32); count = PositiveIntegerField(default=0); updated_at
    unique_together = ('user', 'template_key')
class ReminderLog(models.Model):          # one row per (person, occurrence) ever reminded → no duplicates
    person = FK(NaturalPerson); occurrence_id = CharField(128); channel = CharField(16)  # 'subscribe' | 'notification' | 'skipped'
    scheduled_for = DateTimeField(); sent_at = DateTimeField(auto_now_add=True); detail = CharField(128, blank=True)
    unique_together = ('person', 'occurrence_id')
```

Job: `@periodical('interval', 'timetable_class_reminders', minutes=5)` →
for every `TimetableSettings` with `reminder_enabled`, take today's
`week_view` occurrences (not hidden, not canceled) whose `start -
reminder_minutes` falls in `(now - 5min, now]`; skip ones already in
`ReminderLog`; send. Sending = `reminders.send_class_reminder(person,
occurrence)`: if `subscribe_templates.class_reminder.id` is set, the user has
a `UserWechatProfile` (`user.wx_profile.openid`) and `SubscribeQuota.count >
0` → `extern.wx_miniapp.send_subscribe_message(openid, template_id, page,
data)` (uses `api.auth.wechat_api.get_wechat_access_token()`; `data` values
are truncated to WeChat's limits: `thing*` 20 chars, `time*` formatted
`YYYY年MM月DD日 HH:MM`); decrement the quota; WeChat errcode 43101 (user
refused / no quota) → set quota 0 and fall through. Fallback:
`notification_create(receiver=user, sender=None, typename=NEEDREAD,
title='上课提醒', content='...', URL=None, to_wechat=True)` — `'上课提醒'` is
used as a plain title string; do not extend `Notification.Title` (no `app`
migration). Every outcome is logged in `ReminderLog.channel/detail`.

API additions under `/api/v2/timetable/`:

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `subscribe-templates/` | – | `{class_reminder: {template_id: string \| null}}` (null when not configured → client never calls `wx.requestSubscribeMessage`) |
| POST | `subscribe-grant/` | `{template_key: 'class_reminder', count?: number}` | `{template_key, count}` (server caps at `subscribe_quota_cap`; count defaults to 1) |

The mini-program calls `wx.requestSubscribeMessage({tmplIds:[id]})` on a
user tap (the 提醒 switch) and on each timetable open once the switch is on
(silent when "总是保持以上选择" was chosen), posting `subscribe-grant/` for
every `accept`.

Implementation notes (as built): `send_class_reminder` first inserts the
`ReminderLog` row (channel `skipped`, detail `pending`) so the unique key
makes concurrent jobs send at most once, then updates it; a quota unit is
only consumed on a successful send (43101 zeroes the quota, other WeChat
failures give the unit back) before falling back to the notification; the
fallback content omits ` @location` when the location is empty; the due
window is `(now − 15min, now]` (three job intervals, so a short scheduler
outage does not drop reminders; `ReminderLog` keeps re-scans idempotent) and
a reminder is never sent once the class has started
(`reminder_lookahead_minutes` is reserved for a look-ahead mode). Each job
tick resolves the sources per enabled person (~10 queries each); fine for
YPPF's scale, batch it before rolling out to thousands of users. `subscribe-grant/` accepts only
configured template keys (plus `class_reminder`), 400 otherwise. Jobs are
discovered by `scheduler.management.commands.collect_jobs` importing
`<app>.jobs` for every installed app — no registration list to edit.

### 6.2 Grades (`academic_record` app, `/api/v2/grades/`)

Portal payload (`retrScores.do`): `{"cjxx": [{"xnd": "25-26", "xq": "1",
"list": [{"kcmc": 课程名, "kch": 课程号, "xf": 学分, "xqcj": 学期成绩, "jd": 绩点,
...}]}]}` — field names beyond these five are kept in `raw`; the parser must
tolerate missing/extra keys and non-numeric scores (`P`, `合格`, `W`).

```python
class GradeRecord(models.Model):
    person = FK(NaturalPerson, related_name='grade_records')
    term_code = CharField(16)        # f'{xnd}-{xq}' → '25-26-1'
    course_code = CharField(32, blank=True); class_no = CharField(8, blank=True)
    name = CharField(80); course_type = CharField(32, blank=True)
    credits = DecimalField(4, 1, null=True); score = CharField(16, blank=True)   # raw text
    score_numeric = FloatField(null=True); gpa = FloatField(null=True)
    raw = JSONField(default=dict); fetched_at = DateTimeField()
    unique_together = ('person', 'term_code', 'course_code', 'name')
```

Services: `fetch_scores(user) -> list[TermScores]` (via
`pku_account.services.get_client(user).get_scores()`; `PortalSessionExpired`
→ `invalidate_session` and re-raise), `store_scores(person, terms)` (upsert
per term; only called when `consent_grades`), `summary(terms)` →
`{credits, gpa}` with GPA = Σ(jd·xf)/Σxf over rows that have both, and the
same per term. Consent revocation: `pku_account.services.update_consents`
sends the Django signal `pku_account.signals.consent_changed(sender,
account, field, granted)`; `academic_record` connects a receiver that deletes
the person's `GradeRecord`s when `grades` is revoked (dependency stays
academic_record → pku_account).

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/v2/grades/` | – | `GradesOut` from stored rows; 403 `CONSENT_REQUIRED` if `consent_grades` is false |
| POST | `/api/v2/grades/sync/` | – | fetch live; when consented also store; `GradesOut` with `stored: bool`. Errors: 409 `PKU_LOGIN_REQUIRED`, 503 `PORTAL_UNREACHABLE`, 404 `NOT_BOUND` |
| DELETE | `/api/v2/grades/` | – | 204, wipes stored rows |

```ts
interface GradeRow { term_code: string; course_code: string; class_no: string; name: string; course_type: string;
  credits: number | null; score: string; score_numeric: number | null; gpa: number | null }
interface GradesOut { stored: boolean; fetched_at: string | null;
  summary: { credits: number; gpa: number | null };
  terms: { term_code: string; summary: { credits: number; gpa: number | null }; rows: GradeRow[] }[] }
```

Mini-program page `pages/timetable/grades.vue`: consent gate (explain,
toggle → `PATCH /api/v2/pku/consents/ {grades: true}`), 同步 button,
overall + per-term GPA, rows; entry from the timetable menu and 我的.

Implementation notes (as built): `GET` answers 404 `NOT_BOUND` when there is
no binding and 403 `CONSENT_REQUIRED` when bound without consent; its
`stored` means "rows exist" and `fetched_at` is the newest stored row's
timestamp (null when none). `POST sync/` adds 400 `PARSE_FAILED` (portal JSON
without a `cjxx` list or `success: false`; the session is not marked ok) and
503 `PORTAL_DISABLED`; `{"cjxx": []}` is a valid empty result. `terms` are
ordered newest first, rows keep the portal order, rows lacking both `kcmc`
and `kch` are dropped, duplicates within a term keep the first. `credits`
and `summary.credits` are JSON numbers; GPA is rounded to 3 decimals.
`consent_changed` fires for every explicitly passed flag (even unchanged),
only after commit. Deleting a `PkuAccount` (unbind / user deletion) also
deletes the person's stored grades (`academic_record.receivers`).

### 6.3 Course catalog (`timetable/catalog.py`, command `import_course_catalog`)

Source: the xlsx written by ICUlizhi/PKU-Course-Crawler (`课表信息汇总+.xlsx`),
columns in order: 学年学期, 院系, 表格类型, 内部学期, 课程号, 课程名, 课程英文名,
班号, 修读对象, 课程类别, 参考学分, 周学时, 总学时, 授课教师, 起止周, 上课时间, 备注.

```python
class CourseCatalogEntry(models.Model):
    term = FK(AcademicTerm, on_delete=CASCADE); department = CharField(64, blank=True)
    course_code = CharField(32); name = CharField(80); name_en = CharField(160, blank=True)
    class_no = CharField(8, blank=True); audience = CharField(32, blank=True); category = CharField(32, blank=True)
    credits = DecimalField(4, 1, null=True); hours_per_week = CharField(16, blank=True); total_hours = CharField(16, blank=True)
    teacher = CharField(80, blank=True); weeks_text = CharField(64, blank=True); time_text = CharField(200, blank=True)
    note = CharField(200, blank=True)
    slots = JSONField(default=list)   # best-effort parse of 起止周 + 上课时间 into LessonBlock-like dicts (weekday/sections/weeks/parity/room)
    unique_together = ('term', 'course_code', 'class_no')
```

`python manage.py import_course_catalog <xlsx> --term 26-27-1 [--sheet ...]`
upserts by `(term, course_code, class_no)` (openpyxl, already a dependency);
`--term` maps the 学年学期 column when it is absent/ambiguous. API:
`GET /api/v2/timetable/catalog/?term=&q=` → up to 20 `{id, course_code, name,
class_no, teacher, credits, time_text, slots}` matching name/code/teacher
(`icontains`), used by `entry-form.vue` to prefill a manual entry (one
`TimetableEntry` per slot).

Implementation notes (as built): `slots` items use exactly the LessonBlock
keys `weekday/start_section/end_section/week_start/week_end/parity/room`;
`credits` is a JSON number or null; an empty `q` returns `[]` (max length 64).
The import command routes each row by its 学年学期 column when that maps to
an existing `AcademicTerm`, uses `--term` when the column is missing or
unparseable, and skips (and reports) rows whose parsed term does not exist;
numeric course codes are zero-padded to 8 digits and class numbers to 2.

### 6.4 Academic calendar (校历) — `semester.CalendarEvent`, command `import_academic_calendar`

The university calendar decides which dates actually have classes. Source:
the PDF 校历 published each year (e.g. 北京大学 2026—2027 学年校历); an admin
transcribes it into one JSON file per term, imports it, and can edit the rows
in Django admin at any time. **The calendar changes** (调休, ad-hoc 停课), so
it is one mutable, global table in the base app `semester` that every
module reads at use time — never copied into other rows, never cached across
requests, never hardcoded. Activities, 书院课 scheduling and anything else
that needs "is this a class day / which weekday's timetable applies" must go
through `semester.calendar`.

```python
# semester/models.py — global, keyed by date (no FK to any term object)
class CalendarEvent(models.Model):
    class Kind(TextChoices):
        HOLIDAY = 'holiday'   # 放假，全校停课 — no classes
        EXAM = 'exam'         # 停课复习考试 — no classes
        SWAP = 'swap'         # 调休：按 follows_weekday 的课表上课
        INFO = 'info'         # annotation only (公休但课程照常 / 运动会 / 注册日)
    kind = CharField(choices=Kind); start_date = DateField(); end_date = DateField()   # inclusive
    name = CharField(64); follows_weekday = PositiveSmallIntegerField(null=True)      # 1..7, SWAP only
    note = CharField(200, blank=True)
    ordering = ['start_date', 'id']

# semester/calendar.py — the read API for the whole platform (fresh DB query each call)
def events_between(start, end) -> list[CalendarEvent]
class AcademicCalendar:            # built for a date range
    def kind_of(date) / event_of(date) / is_class_day(date) / effective_weekday(date) / label(date)
def calendar_between(start, end) -> AcademicCalendar
def is_class_day(date) -> bool; def effective_weekday(date) -> int
```

`timetable/calendar.py` is a thin adapter (`calendar_for(term)` =
`calendar_between(term.week1_monday, term.end_date())`, `day_info`).

Semantics (used by `expand_entries`, `week_view` and the ICS feed — every
stored-entry source, i.e. portal/paste/manual; live sources such as 书院课
activities, applied activities and appointments are real events and are left
untouched):

- a date covered by `HOLIDAY` or `EXAM` produces **no** stored-entry
  occurrences (the mini-program shows the day label instead);
- a `SWAP` date produces the occurrences of entries whose `weekday ==
  follows_weekday` (week range / parity checked against the swap date's own
  week number) and none of the entries of the real weekday;
- `INFO` changes nothing, it is only surfaced as a label;
- overlapping events: `HOLIDAY`/`EXAM` win over `SWAP`, which wins over `INFO`.

JSON import format (`python manage.py import_academic_calendar <file>`, in
`timetable`; upserts the `AcademicTerm` from `term`/`name`/`week1_monday`/
`total_weeks` and **replaces** the `semester.CalendarEvent` rows that overlap
that term's span with the file's events; events outside the span are kept;
idempotent):

```json
{
  "term": "26-27-1", "name": "2026-2027学年秋季学期",
  "week1_monday": "2026-09-07", "total_weeks": 18,
  "events": [
    {"kind": "holiday", "start": "2026-09-25", "end": "2026-09-25", "name": "中秋节放假"},
    {"kind": "info",    "start": "2026-09-26", "end": "2026-09-27", "name": "公休，课程照常进行"},
    {"kind": "info",    "start": "2026-09-30", "end": "2026-09-30", "name": "公休，课程照常进行"},
    {"kind": "holiday", "start": "2026-10-01", "end": "2026-10-07", "name": "国庆节放假"},
    {"kind": "info",    "start": "2026-10-10", "end": "2026-10-11", "name": "校本部秋季运动会"},
    {"kind": "exam",    "start": "2027-01-11", "end": "2027-01-17", "name": "停课复习考试"},
    {"kind": "holiday", "start": "2027-01-18", "end": "2027-02-21", "name": "寒假"}
  ]
}
```

`timetable/data/calendar_26-27-1.json` and `calendar_26-27-2.json` ship the
2026-2027 calendar transcribed from the PDF (spring: `week1_monday`
2027-02-22, 5/1–5/7 停课 (劳动节、调休、校庆), 5/8–5/9 公休课程照常 (info),
6/14–6/27 停课复习考试, 6/28 起暑假; 元旦 2027 is unknown until the State
Council publishes it — add it as a `HOLIDAY` row when known). A `swap` row
looks like `{"kind": "swap", "start": "2026-10-10", "end": "2026-10-10",
"name": "按周一课表上课", "follows_weekday": 1}`.

API changes (both additive):

```ts
interface CalendarEvent { kind: 'holiday'|'exam'|'swap'|'info'; start: string; end: string; name: string; follows_weekday: number | null }
interface Term { ...; calendar: CalendarEvent[] }                       // terms/ and week/.term
interface WeekDay { date: string; weekday: number; kind: CalendarEvent['kind'] | null; label: string | null; follows_weekday: number | null }
interface WeekView { ...; days: WeekDay[] }                              // one per week_dates entry
```

Mini-program: the date header shows `label` (red for holiday/exam, blue for
swap "按周一", grey for info) and shades holiday/exam columns; the poster does
the same; nothing else changes because the backend already omits the
occurrences.

Implementation notes (as built): `Term.calendar` lists the events overlapping
the term's **teaching span** `[week1_monday, date_of(total_weeks, 7)]`, so an
exam week or vacation after the last teaching week is not in it (it is still
in the table and in `week/` for those dates). The import command replaces
the events inside `[min(week1_monday, earliest event), max(end of teaching
span, latest event)]` so re-running a file is idempotent even when its exam
week / vacation lie outside the teaching weeks; the two seed files' windows
touch without overlapping. Helpers: `timetable.calendar.day_info(on,
calendar=None)`, `week_days(term, week, calendar=None)`, `calendars_for(terms)`
(one query for `terms/`); `expand_entries(entries, term, week_from, week_to,
calendar=None)`. Swap-day occurrences carry the real `date/weekday/week`.
`AcademicCalendar.event_of` raises `ValueError` for dates outside the range
it was built for. The JSON importer rejects unknown keys, a `week1_monday`
that is not a Monday, duplicate events and events outside
`week1_monday − 42d .. + 364d`.

### 6.5 Home agenda, week picker, day view (product changes of 2026-09-09)

Sources are now four, each switchable in settings and honoured everywhere
(week view, agenda, ICS): 学校课表 (stored entries: portal/paste/manual)
`show_courses`, 书院课 `show_college`, 我参与的活动 `show_activities`, 地下室预约
`show_appointments`. `TimetableSettings.show_courses` (default true) is
added; `build_ics(person)` and the ICS feed use the same four flags.

Agenda API — `GET /api/v2/timetable/agenda/?from=<date>&days=<n>` (defaults:
today, 7; max 14; auth as usual): consecutive days starting at `from`,
spanning term boundaries (days outside any term have `term: null` and no
stored-entry occurrences; live sources still apply), each day carrying its
calendar label:

```ts
interface AgendaDay { date: string; weekday: number; term: string | null; week: number | null;
  kind: CalendarEvent['kind'] | null; label: string | null; occurrences: Occurrence[] }
interface AgendaOut { from: string; days: AgendaDay[]; sources: { key: string; label: string }[] }
```

Mini-program:

- **Home** (`pages/index/index.vue`): the three activity tabs become two —
  「我的日程」(default; the agenda for today + the next 6 days as a grouped
  list: date header with calendar label, then occurrences with time,
  title, location, kind badge; tap → the same detail actions as the
  timetable page; a top-right button 「本周课表」 opens
  `/pages/timetable/index`; an empty agenda shows the import CTA) and
  「最新发布」(the external feed: newly released activities from
  `getActivityOverview().newly_released_activities` plus the latest unread
  notifications from `/api/v2/notification/`, merged by time; questionnaires
  later). The old 「今日活动」 tab is removed. A small source-chip row on
  the agenda (课表 / 书院课 / 活动 / 预约) toggles `show_*` via
  `PATCH settings/`.
- **Week picker** (`pages/timetable/index.vue`): the 第 N 周 label becomes a
  button opening a `uv-popup` grid of all weeks (number + Mon–Sun dates,
  current week highlighted, holiday weeks marked); tapping jumps to that
  week. ‹ › stay.
- **Day view**: tapping a date header (or a 「日」/「周」 segment control)
  opens the day view for that date — a full-height list of that day's
  occurrences with complete titles, time, location, teacher/subtitle and
  status, swipe or ‹ › to move by day; same detail actions. Implemented as
  `pages/timetable/day.vue?date=YYYY-MM-DD` (uses `agenda/` with `days=1`),
  reachable from the week grid and from the home agenda's date headers.
- Export: the settings section explains that the ICS subscription follows
  the same four source toggles.

Implementation notes (as built): sources gained an optional
`occurrences_between(person, span: DateSpan, settings)`; `DateSpan`
(`timetable/sources/base.py`) resolves the active terms for a date range
once and is shared by all sources; term-based sources fall back to a default
implementation. For dates outside any term `Occurrence.week` is counted
relative to the latest started term (0 when there is none) while
`AgendaDay.week` stays null. `days` above 14 is truncated (not an error);
`days < 1`, non-integers and a malformed `from` answer 400; empty values
mean "omitted"; with no term at all `agenda/` still answers 200 with
`term: null` days. In date mode 书院课 are taken from every successful,
non-aborted enrolment and selected by date (week mode still filters by the
YPPF semester). `show_courses` also silences class reminders for school
courses, like the other three toggles do for theirs.

## 7. Verification

- Backend: `python manage.py test pku_account timetable api.pku_account api.timetable`
  inside the dev container (see AGENTS.md). Parsers get fixture-based unit
  tests (portal JSON, portal HTML, elective HTML + plain text); services get
  DB tests for upsert/replace semantics, week expansion (parity, week range,
  term boundaries), college adapter (generated Activity vs expansion), ICS
  output; API tests cover auth (401/403), the 409 `PKU_LOGIN_REQUIRED` path
  and that credentials never appear in logs. HTTP to pku.edu.cn is always
  mocked in tests.
- Mini-program: `pnpm type-check`, `pnpm exec eslint <changed files>`,
  `pnpm build:mp` must pass; manual walkthrough in WeChat DevTools.

## 8. Iteration 3 (2026-09-10) — catalog links & 旁听, scoped edits & details, tags & filter, exam weeks & exam schedule, poster styles

Product asks behind this section (from the maintainer, 2026-09-10):

1. 旁听: students can add any school course from the catalog to their
   timetable even when not enrolled; imported courses that exist in the
   catalog point at the catalog row instead of duplicating it, but the
   student's own values always win.
2. The home page's per-source buttons do not scale once tags multiply; the
   entry to the full timetable should read 「完整课表」.
3. Tapping a lesson lets the student edit it, choosing between this
   occurrence only / this and following / every occurrence.
4. A course can carry details (notes, code, teacher, credits…) that are not
   drawn in the grid but shown on tap.
5. Weeks 17/18 (course exams) and the university exam period are marked; a
   term's exam schedule can be brought into the timetable without retyping.
6. The poster must be worth sharing: preset styles, and the mini-program /
   official-account QR codes attached by default (removable).

Everything below is additive to §4–§6; unchanged fields keep their meaning.

### 8.1 Catalog-linked entries and 旁听 (audit) courses

```python
class TimetableEntry(models.Model):                       # additions
    class Role(TextChoices): ENROLLED = 'enrolled', '已选'; AUDIT = 'audit', '旁听'
    class Category(TextChoices): COURSE = 'course', '课程'; EXAM = 'exam', '考试'; OTHER = 'other', '其它'
    catalog_entry = FK(CourseCatalogEntry, null=True, blank=True, on_delete=SET_NULL, related_name='timetable_entries')
    role = CharField(16, choices=Role, default=ENROLLED)
    category = CharField(16, choices=Category, default=COURSE)
    tag = CharField(24, blank=True)          # §8.3
    note = TextField(blank=True)             # was CharField(200); API caps at 2000 chars
```

`kind` (and `Occurrence.kind`) is derived from `category`: `exam` → `'exam'`,
`other` → `'custom'`, `course` → `'course'`. Migration: existing manual rows
get `category='other'` (they were rendered as custom before), imported rows
`'course'`; `role` defaults to `enrolled`.

**Linking on import.** `timetable.catalog.match_catalog(term, *, course_code,
class_no, name, teacher) -> CourseCatalogEntry | None` (pure lookup, one
query per call is fine): (1) `course_code` and `class_no` both given → exact
row of `(term, course_code, class_no)`; (2) only `course_code` → the row of
that code when the term has exactly one; (3) otherwise the row whose `name`
equals the block's name (whitespace/case-insensitive) — and `teacher` when
the block has one — when exactly one matches; ambiguous → `None`. Numeric
codes are zero-padded like the import command does. `upsert_entries` sets
`catalog_entry` for every portal/paste block and fills **blank** `teacher`,
`course_code`, `class_no` from the catalog; a non-blank value from the
student's import is never overwritten. Re-imports keep `hidden`, `color`,
`tag`, `role` and the overrides of §8.2 (they are not in `_entry_fields`).

**Quick add from the catalog.** `POST /api/v2/timetable/catalog/<id>/add/`
body `{role?: 'audit'|'enrolled' (default 'audit'), slots?: number[]
(indices into CatalogEntry.slots; default all), term?: string}` → `201
Entry[]`: one manual entry per selected slot, `catalog_entry` set,
`category='course'`, `name/course_code/class_no/teacher` and the slot's
`room/weekday/sections/weeks/parity` copied, `external_key` a fresh uuid,
`raw_text=''`. Errors: 404 `timetable.catalog_not_found` (wrong term/id),
409 `timetable.catalog_already_added` when the person already has an entry
in that term linked to this catalog row (message names the course; the
client refreshes), 400 `timetable.catalog_no_slots` when the row has no
parsable slot (client falls back to the manual form prefilled with the
catalog fields), 400 `errors.slots` on out-of-range indices.

`POST entries/` (manual create) accepts `catalog_id?: number | null`
(same-term catalog row → link) plus `role`, `category`, `tag`; `PATCH
entries/<id>/` with `scope='all'` accepts `catalog_id` (`null` unlinks),
`role`, `tag`, `category` for **any** source (they are the student's own
annotations and survive re-import).

`GET catalog/?term=&q=` items gain `department, category, audience,
credits, hours_per_week, weeks_text, note` and `added: boolean` (the person
already has an entry linked to the row in that term). `q` semantics
unchanged (name / English name / code / teacher, `icontains`, ≤20 rows).

Implementation notes (as built): matching lives in
`timetable.catalog.CatalogIndex` (one query per import through
`for_term`; `match_catalog` wraps it for single lookups). Names and
teachers are compared with whitespace removed, case-folded and full-width
brackets unified; numeric codes are zero-padded to 8 and class numbers to
2. Step (3) narrows by teacher only when some row of that name carries
that teacher — a name that is unique in the term links even when the
teacher spelling differs (portal 束琳 vs catalog 束琳(教授)). A re-import
sets `catalog_entry` on new entries and on entries not linked yet; an
existing link (from an earlier import or the student's `catalog_id`) is
kept, so an explicit unlink (`catalog_id: null`) is re-linked by the next
import when the matcher finds a row — there is no "never link" flag.
`note` is capped at 2000 characters for imports as well. New manual
entries default to `category='course'` (kind `course`) unless the client
sends `category`; only pre-existing manual rows were migrated to `other`.
Quick add clamps a slot's week range into `1..total_weeks`, skips a slot
that cannot be placed (all skipped → `timetable.catalog_no_slots`),
collapses duplicate indices and is serialised per person (row lock), so
two concurrent taps cannot add a course twice. `added` is computed for
the ≤20 returned rows with one query.

### 8.2 Scoped edits (this occurrence / following / all) and details

```python
class TimetableEntryOverride(models.Model):
    entry = FK(TimetableEntry, on_delete=CASCADE, related_name='overrides')
    week_start = SmallIntegerField(null=True)   # None = the entry's first week
    week_end = SmallIntegerField(null=True)     # None = the entry's last week
    canceled = BooleanField(default=False)      # occurrences in range are dropped
    fields = JSONField(default=dict)            # only the overridden keys, see below
    created_at / updated_at
    class Meta: ordering = ['id']
```

`fields` keys ⊆ `{name, teacher, room, weekday, start_section, end_section,
start_time, end_time, note, tag, color}`; times as `'HH:MM'`; a key that is
present is the effective value, an absent key means "unchanged". Ranges may
overlap; when expanding week *w*, the applicable overrides (`week_start ≤ w
≤ week_end`, `None` bounds open) are applied in order of **descending range
width, then ascending id**, so a narrower or newer override wins for every
key, `canceled` included (the last applied override's value). `week_start`
/`week_end` are validated against the entry's own week span.

`PATCH /api/v2/timetable/entries/<id>/` gains `scope` (`'all'` default,
`'single'`, `'following'`) and `week` (required for single/following, must
lie in `week_start..week_end`, else 400 `errors.week`):

- `all`: manual entries update the row as before. Any source: `hidden`,
  `color`, `tag`, `role`, `category`, `catalog_id` update the row. For
  portal/paste entries the other editable keys (`name, teacher, room,
  weekday, start_section, end_section, start_time, end_time, note`) are
  stored in the entry's whole-range override (`week_start=None,
  week_end=None`; created on demand, keys merged) so they survive
  re-import. `canceled` is rejected here (400) — hide or delete instead.
- `single`: upsert the override with `(week, week)`, merging the given keys
  into `fields`; `canceled: true|false` allowed ("本次停课").
- `following`: upsert the override with `(week, None)` (so a later re-import
  that shortens the entry still works); keys merged; `canceled` allowed.
- `hidden`, `role`, `category`, `catalog_id` are rejected with a scope other
  than `all` (400 `errors.scope`).
- Sections given without times derive times from the term table as in
  create; `weekday`/sections/times validated as for create.

`GET entries/<id>/` (new retrieve) and every `Entry` payload gain:

```ts
role: 'enrolled' | 'audit'; category: 'course' | 'exam' | 'other'; tag: string
catalog: { id, course_code, name, class_no, teacher, credits, department, category, time_text, weeks_text, note } | null
overrides: { id: number; week_start: number | null; week_end: number | null; canceled: boolean;
             fields: Partial<{ name, teacher, room, weekday, start_section, end_section, start_time, end_time, note, tag, color }>;
             updated_at: string }[]
exam: { id, start, end, room, method, note } | null      // §8.4, first matching CourseExam by time
```

`DELETE entries/<id>/overrides/<oid>/` → 204 (恢复该次/该段), `DELETE
entries/<id>/overrides/` → 204 (恢复全部). Both 404 for another person's
entry.

`Occurrence` gains `role` (`'enrolled' | 'audit' | ''`; `''` for live
sources), `tag` (string), `modified` (bool: at least one override applied
to this occurrence) and `note` is **not** added (details are fetched via
`GET entries/<id>/` when the sheet opens; the occurrence stays small).
Expansion honours overrides: an overridden `weekday` moves the lesson to
that weekday of the same teaching week (calendar rules of the target date
apply), `canceled` drops it, `hidden`/`hidden_tags` (§8.3) filter as before.
ICS and reminders consume occurrences and therefore follow automatically.

Implementation notes (as built): resolution is `timetable/overrides.py`
(`applicable_overrides`, `resolve_week`, pure over model instances);
`expand_entries(..., overrides=None)` takes `{entry id: overrides}`, reads
the `overrides` prefetch when present and otherwise costs one query for
all entries (the stored source prefetches). `modified` is true whenever at
least one override applies, even one that changes nothing. Override
values are coerced: a weekday outside 1..7, a non-integer section or a
malformed time is ignored; sections overridden without times take the
times of `term.section_times`; a pair whose end does not follow its start
falls back to the entry's own times. `PATCH` validates a body against the
entry with the override of the same range applied (partial bodies are
checked against what the student currently sees); `week_start`,
`week_end` and `parity` of an imported entry answer 400 `errors.<field>`
(no longer 403), with a scope other than `all` they answer 400
`errors.scope` like `hidden`/`role`/`category`/`catalog_id`; `canceled`
with scope `all` answers 400 `errors.canceled`; an empty body is a no-op
200. Overrides of an entry removed by a re-import are deleted with it.
`overrides[].updated_at` is `YYYY-MM-DDTHH:MM:SS`; `entries/` and the
quick-add response use one query for catalog rows, overrides and exams
each. OpenAPI: the two `DELETE …/overrides/` operations carry explicit
operation ids and the entry enums are named through
`SPECTACULAR_SETTINGS['ENUM_NAME_OVERRIDES']`.

### 8.3 Tags, the filter sheet and the sources legend

- `TimetableEntry.tag` (≤24 chars, any source) is shown as a small label in
  the grid/list and is filterable. `TimetableSettings.hidden_tags =
  JSONField(default=list)` lists tags whose entries are skipped by the
  stored source (week view, agenda, ICS, reminders); `show_exams =
  BooleanField(default=True)` toggles the exam source (§8.4).
- `GET settings/` adds `hidden_tags: string[]`, `show_exams: boolean` and two
  read-only lists: `sources: { key: string; label: string; setting: string }[]`
  (the registered sources in config order, `setting` = the boolean that
  toggles it: `show_courses` for `stored`, `show_college`, `show_activities`,
  `show_appointments`, `show_exams`) and `tags: string[]` (distinct non-empty
  tags of the person's entries, all terms, sorted). `PATCH settings/`
  accepts `hidden_tags` (list of ≤24-char strings, deduplicated) and
  `show_exams` in addition to the existing booleans.
- Mini-program home: the chip row is replaced by one 「筛选」 button
  (badge shows *enabled/total* when anything is off) opening a bottom sheet
  built from `settings.sources` (switch per source) and `settings.tags`
  (switch per tag, off when in `hidden_tags`); saving patches the settings
  and reloads the agenda. The header link reads 「完整课表 ›」. The same
  sheet is reachable from the timetable page's 设置 / import page.

Implementation notes (as built): every source class declares a `setting`
attribute (`'show_courses'`, …, `'show_exams'`); a third-party source
without one is listed with `setting: ''`. `hidden_tags` filters on the
*effective* tag of an occurrence (an override may re-tag one week), and
the exam source skips the exams of courses whose tag is hidden. `GET`
returns `hidden_tags` sorted; `PATCH` trims, drops blanks, deduplicates
and accepts at most 200 tags; the entry list is never filtered by tags so
a tag can be un-hidden. `services.settings_payload` builds the payload
(`SettingsOutSerializer` documents it).

### 8.4 Exam weeks and the exam schedule

```python
class AcademicTerm(models.Model):                  # addition
    exam_week_start = PositiveSmallIntegerField(null=True, blank=True)   # weeks ≥ this are 考试周

    @property
    def teaching_weeks(self) -> int                # exam_week_start - 1 when set (≥1), else total_weeks
```

`total_weeks` now spans the whole term **including** exam weeks (the
official calendar numbers teaching weeks only; PKU practice is 16 teaching
weeks + 17/18 course exams + the university 停课复习考试 period). Seeds:
`calendar_26-27-1.json` → `total_weeks: 19, exam_week_start: 17` (weeks 17–18
课程考试, week 19 = 停课复习考试 2027-01-11..17 already a calendar `exam`
event); `calendar_26-27-2.json` → `total_weeks: 18, exam_week_start: 17`
(6/14–6/27 exam period = weeks 17–18). `import_academic_calendar` reads the
optional `exam_week_start` key. `Term` payload adds `exam_week_start:
number | null` and `teaching_weeks: number`; defaults for new manual
entries and catalog slots without a week range use `teaching_weeks`.

Week picker / week header: a week ≥ `exam_week_start` is labelled 考试周
unless a calendar event already labels it (放假 / 停课复习考试 win);
lessons still follow the entry's own week range (a 1–18 course keeps
showing in weeks 17–18) — only the calendar's `exam` days suspend classes.

```python
class CourseExam(models.Model):
    term = FK(AcademicTerm, on_delete=CASCADE, related_name='exams')
    course_code = CharField(32); class_no = CharField(8, blank=True); name = CharField(100)
    teacher = CharField(80, blank=True)
    start = DateTimeField(); end = DateTimeField()
    room = CharField(100, blank=True); method = CharField(32, blank=True)   # 考试方式
    note = CharField(200, blank=True); raw_time = CharField(64, blank=True)
    class Meta: unique_together = ('term', 'course_code', 'class_no', 'start'); ordering = ['start', 'course_code']
```

Command `import_exam_schedule <xlsx|csv> --term 26-27-1 [--sheet]` loads
the 教务部 exam table with header matching like `import_course_catalog`
(aliases: 课程号/课程编号, 课程名/课程名称, 班号, 教师/授课教师/任课教师,
考试时间/考试日期时间/时间, 考试日期 + 开始时间/结束时间 as separate
columns, 考试地点/教室/考场/地点, 考试方式, 备注, 学年学期 optional) and
upserts on `(term, course_code, class_no, start)` (rows of other keys are
kept; `--replace` deletes the term's rows first). Time parsing lives in
`timetable/exams.py` as pure `parse_exam_time(text, term) -> (datetime,
datetime) | None` accepting `2027-01-11 08:30-10:30`, `2027/1/11 8:30～10:30`,
`2027年1月11日 08:30-10:30`, `1月11日（周一）8:30-10:30` (year from the term
span), `第19周 周一 08:30-10:30` (resolved via `term.date_of`), and a
date-only cell with separate start/end cells; missing end defaults to
start + 2 h. Unparseable rows are skipped and reported.

Source `timetable.sources.exam.ExamSource` (key `exam`, label `考试`,
registered in `config.json → timetable.sources` and the template) emits,
for the person's non-hidden `category='course'` entries of the term, one
occurrence per matching `CourseExam`: match by `(course_code, class_no)`
(catalog values when linked, else the entry's), then by `course_code`
alone when unique, then by exact `name`; each exam is emitted once even if
several entries (slots) match. Occurrence: `id='exam:{exam.id}:{date}'`,
`source='exam'`, `kind='exam'`, `title=f'{name} 考试'`, `subtitle=method or
teacher`, `location=room`, `start/end` from the row, `start_section/
end_section=None`, `color_key=name`, `ref={'exam_id', 'entry_id'}`,
`role=''`. Honours `settings.show_exams`. Manual exams (entry-form 类别 =
考试) are ordinary entries with `category='exam'`, `week_start == week_end`.

The portal may expose the student's own exam list; that is not known yet
(needs a real account — `pku_probe.py`), so no per-student import exists in
this iteration. The import page explains that exams appear automatically
once the term's schedule is loaded.

Implementation notes (as built): `teaching_weeks` is clamped into
`1..total_weeks`; `AcademicTerm.is_exam_week(week)` is the helper behind
the picker label. The calendar JSON accepts an optional integer
`exam_week_start` in `1..total_weeks`; a file without it resets the term's
value to null. Terms that already exist keep their old `total_weeks`
until the seed files are re-imported (`import_academic_calendar
timetable/data/calendar_26-27-1.json`, then `…-2.json`).
`parse_exam_time(text, term, *, start_text='', end_text='')` also reads
dotted dates (`2027.1.11`), `8点30分`/`8时30分`, 上午/下午/晚上 markers,
`星期一`/`周1` tokens, workbook `datetime`/`date`/`time` cells, and takes
the date from `start_text` when `text` is blank; an end at or before the
start is replaced by start + 2 h. `import_exam_schedule` reads csv by
extension (UTF-8 with or without BOM), skips and reports rows whose
学年学期 names another term, refuses `--sheet` for csv and upserts with
zero-padded codes; the summary lists every skipped row with its reason.
`ExamSource` selects the term's exams by the week span of their `start`,
each exam is emitted once (the lowest entry id keeps it) and code-only /
name-only matches require every row of that key to belong to one class.
Exam occurrences reach reminders and ICS like any other (`CATEGORIES:考试`,
reminder title unchanged). `Entry.exam` uses the same matcher, first by
time; `entries/` resolves all entries with one exam query.

### 8.5 Poster styles and share assets

`GET /api/v2/timetable/share/assets/` → `{ miniapp_qrcode: string | null,
official_qrcode: string | null, slogan: string }` (absolute URLs). The
mini-program code is produced with `wxacode.getUnlimited`
(`POST https://api.weixin.qq.com/wxa/getwxacodeunlimit?access_token=`, body
`{scene: 'timetable', page: CONFIG.share.miniapp_page, check_path: false,
env_version: CONFIG.share.env_version, width: 430}`) through
`extern.wx_miniapp.fetch_miniapp_code(scene, page) -> bytes | None`, using
`api.auth.wechat_api.get_wechat_access_token`; the PNG is cached at
`MEDIA_ROOT/timetable/share/miniapp_<scene>.png` for 30 days and served
from `MEDIA_URL`. Failures (mock URL in dev, quota, network) log a warning
and answer `null` — never an error. `official_qrcode` is
`wx_miniapp.share.official_qrcode_url` (absolute URL or a path relative to
`MEDIA_URL`; empty → `null`); `slogan` defaults to `元培智慧书院 · YPPF`.
Config (`config_template.json`): `wx_miniapp.share = {"miniapp_page":
"pages/timetable/index", "env_version": "release", "official_qrcode_url":
"", "slogan": "元培智慧书院 · YPPF"}`. Production must whitelist the
backend host as a `downloadFile` domain for the canvas to load the images.

Mini-program poster (`pages/timetable/poster.vue`): four presets selectable
above the canvas and remembered locally — `clean` 清爽 (white, cool grey
grid, blue accent), `dark` 深夜 (deep navy, pastel blocks, light text),
`paper` 暖纸 (cream paper, warm brown ink, serif-like headline), `pop` 活力
(gradient header, chunky rounded blocks, bold numerals). Common layout:
headline (name's 课表 / 我的课表), term + week + date range, weekday/date
header with calendar labels, the grid, footer with the slogan and, when
「附二维码」 is on (default on when assets exist), the two QR codes with
captions 「小程序」「公众号」. Toggles: 附二维码, 显示姓名 (existing
`share_show_name`). Save to album and `onShareAppMessage` as before.

Implementation notes (as built): `extern.wx_miniapp.fetch_miniapp_code`
treats any JSON body (by content type or a leading `{`) as a failure,
clears the cached access token on 40001/42001 and logs only the error
code, never the token; the config block is read through
`api.config.get_share_config()` (defaults filled in) and the cache logic is
`timetable/share.py`. WeChat returns JPEG bytes; they are stored under the
contract's `miniapp_<scene>.png` name (image decoders sniff the content)
and written atomically. When a refresh fails but a cached image exists,
the stale image is still served (with a warning) — `null` only when no
image was ever produced. URLs are built with `build_full_url` from
`MEDIA_URL`, so `global.base_url` must be the public host and the media
directory must be served (`boot/urls.py` does so in debug; production
needs the web server to serve `MEDIA_ROOT`). `official_qrcode_url`
accepts an absolute URL, a site path with a leading `/` (joined with
`global.base_url`; the repository ships
`/static/assets/img/yppf_official_qrcode.png`, the template's default) or a
bare name resolved under `MEDIA_URL` (drop the file into
`MEDIA_ROOT/timetable/share/` and configure `timetable/share/<name>.png`).
The mini-program bundles the same image (`src/static/share/`) as a
fallback for when the endpoint answers `null` or fails.

### 8.6 API delta (routes)

```
GET    /api/v2/timetable/entries/<id>/                     retrieve (new)
PATCH  /api/v2/timetable/entries/<id>/                     + scope, week, canceled, tag, role, category, catalog_id
DELETE /api/v2/timetable/entries/<id>/overrides/           reset all overrides (new)
DELETE /api/v2/timetable/entries/<id>/overrides/<oid>/     reset one (new)
POST   /api/v2/timetable/catalog/<id>/add/                 quick add 旁听 (new)
GET    /api/v2/timetable/catalog/                          + department, category, audience, credits, hours_per_week, weeks_text, note, added
GET/PATCH /api/v2/timetable/settings/                      + show_exams, hidden_tags; read-only sources, tags
GET    /api/v2/timetable/share/assets/                     poster QR assets (new)
```

Error codes follow the envelope of §4.6 (`{code, message, errors}`): new
codes `timetable.catalog_not_found`, `timetable.catalog_already_added`,
`timetable.catalog_no_slots`, `timetable.override_not_found`; validation
errors use `errors.<field>`.

## 9. Deployment checklist

`python manage.py deploy_check` (the project-wide command; `--app timetable
--app pku_account` narrows it, `--online` adds network probes) prints the
checks as `[OK]` / `[WARN]` / `[FAIL]` lines and exits non-zero on failures
(`--warn-only` for a preflight that must not block). This feature contributes
two plugins: `timetable/deploy_checks.py` (sources, subscribe template, share
assets, reminder job, current / upcoming term with calendar, exam weeks,
catalog and exams; online: the poster's mini-program code) and
`pku_account/deploy_checks.py` (feature switch, session key, bound accounts;
online: IAAA reachability and whether the portal data endpoints still exist —
they answered 404 on 2026-09-10). The order to follow on a fresh deployment:

1. `config.json` (see `config_template.json`): `pku_portal.enabled: true`
   (optional `session_key`, else derived from `SECRET_KEY`);
   `timetable.sources` including `timetable.sources.exam.ExamSource`;
   `wx_miniapp.subscribe_templates.class_reminder.id` once the template is
   approved; `wx_miniapp.share` — the official-account QR code ships at
   `/static/assets/img/yppf_official_qrcode.png` (a leading `/` means a
   site path joined with `global.base_url`, a bare name a file under
   `MEDIA_URL`); `global.base_url` must be the public host.
2. `python manage.py migrate` (`timetable.0004` carries a data step).
3. `python manage.py import_academic_calendar timetable/data/calendar_26-27-1.json`
   (then `calendar_26-27-2.json`): creates or updates the `AcademicTerm`
   with `total_weeks` / `exam_week_start` and replaces the term's calendar
   events; re-run whenever the university amends the calendar.
4. `python manage.py import_course_catalog <xlsx> --term 26-27-1` (旁听 and
   catalog linking) and, when the 教务部 table is published,
   `python manage.py import_exam_schedule <xlsx|csv> --term 26-27-1 [--replace]`.
5. Keep `python manage.py runscheduler` running (`collect_jobs` discovers
   `timetable.jobs`; class reminders are sent every 5 minutes).
6. Mini-program console: the subscribe-message template, `request` **and
   `downloadFile`** legitimate domains for the backend host (the poster
   loads the QR images from it), and a release whose `env_version`
   matches `wx_miniapp.share.env_version`.
7. First real-account check from the server (campus network, no OTP
   expected): `POST /api/v2/pku/login/` then `POST /api/v2/timetable/import/portal/`;
   the local probe `pku_probe.py` (kept outside the repository) shows the
   raw portal payloads when a parser needs adjusting.
