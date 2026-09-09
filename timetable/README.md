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
        "timetable.sources.appoint.AppointSource"
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
be un-hidden. Every error body is `{code, message}` (validation errors add
`errors`).

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

## 6. Sprint 2 (not in the first PR)

- `timetable/reminders.py` + `timetable/jobs.py`: a daily `@periodical`
  job materialises next-day class reminders per user with
  `reminder_enabled`; channel preference: WeChat mini-program subscribe
  message (template ids from `config.json → wx_miniapp.subscribe_templates`,
  quota collected by the client via `wx.requestSubscribeMessage` on each
  timetable open and stored as `SubscribeQuota(user, template, count)`),
  falling back to 站内通知 (`app.notification_utils.notification_create`) +
  `extern.wechat.send_wechat`. Nothing in sprint 1 assumes a channel.
- `academic_record` app: `GradeRecord(person, term_code, course_code, name,
  credits, score, gpa, raw)` written only when `consent_grades` is true;
  otherwise fetched-and-shown only. API `/api/v2/grades/` + page.
- Course catalog import: management command consuming the xlsx produced by
  ICUlizhi/PKU-Course-Crawler → `CourseCatalog` rows (per term), used to
  autocomplete manual entries and, later, activity recommendation.

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
