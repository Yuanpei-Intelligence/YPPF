# rollout — gradual feature release and the preview channel

`rollout` lets a new feature reach a few accounts first, collect feedback and
fix problems, and only then be released to everyone or withdrawn. There is one
deployment and one database: experimental code ships switched off, and an
administrator widens access at runtime in the admin site without redeploying.

The website, the mini-program API, templates and scheduled jobs all ask this
app the same question — *is feature `key` enabled for this account?* — so one
account sees the same thing in every entry point.

## Concepts

- **Feature** (`rollout.Feature`, admin: 灰度功能). One experimental capability,
  referenced from code by a stable `key` such as `grades`. A key that has no row
  is treated as switched off, so code can ship before the row is created.
- **Stage.** Who may use the feature. Stages widen access cumulatively.
- **Allow list** (`Feature.allow_users`). Developers, testers and the WeChat
  review test account. Applies in every stage except `off`.
- **Preview channel** (体验通道, `rollout.PreviewMember`). Accounts that opted
  in to try experimental features. Active personal accounts join and leave by
  themselves in the mini program; administrators can add or remove any account.
- **Audience** (`Feature.audience`). A targeted group described by account
  attributes, such as residential counselors or one grade.
- **Percentage** (`Feature.percent`). A stable share of logged-in accounts in
  the `rollout` stage.

## Stages and evaluation

| Stage | Label | Enabled for |
|---|---|---|
| `off` | 关闭 | nobody, not even the allow list (kill switch) |
| `internal` | 内测 | allow list |
| `preview` | 体验 | allow list, preview channel members, audience |
| `rollout` | 放量 | as `preview`, plus `percent`% of logged-in accounts |
| `ga` | 全量 | everyone, including anonymous visitors |

For a logged-in account the first matching rule wins and becomes the reported
`reason`:

1. stage `off` → disabled
2. stage `ga` → enabled, reason `ga`
3. account in `allow_users` → enabled, reason `allowlist`
4. stage `internal` → disabled
5. account is a preview channel member → enabled, reason `preview`
6. `audience` matches the account → enabled, reason `audience`
7. stage `rollout` and `bucket < percent` → enabled, reason `rollout`
8. otherwise → disabled

Anonymous visitors only get `ga` features. Evaluation follows the account that
is currently logged in (`request.user`): after a person switches to an
organization account, that organization's own access applies.

**Bucket.** `int(sha256("<global.hash_salt>:<key>:<username>")[:8]) % 100`.
It never changes for an account, so the website and the mini program agree,
and each feature samples a different cohort. Changing `global.hash_salt`
reshuffles every rollout. Raising `percent` only adds accounts.

**Audience.** A JSON object; all listed keys must match, and the values in one
list are alternatives. `{}` targets nobody.

| Key | Value type | Meaning |
|---|---|---|
| `utype` | `str` | `generic.User.Type` value, e.g. `"Student"`, `"Organization"` |
| `identity` | `int` | `NaturalPerson.Identity`: 0 teacher/staff, 1 student |
| `status` | `int` | `NaturalPerson.GraduateStatus`, e.g. 2 residential counselor |
| `stu_grade` | `str` | `NaturalPerson.stu_grade`, e.g. `"2026"` |

`identity`, `status` and `stu_grade` never match an organization account.
Example: `{"identity": [1], "stu_grade": ["2025", "2026"]}`.

**Queries.** Evaluating all features for one account costs at most four small
queries regardless of the number of features. There is no cross-request cache,
so a change in the admin site applies to the next request.

## Backend usage

Every entry point of an experimental feature must check the same key. Hiding
an entry in a template or in the mini program is not access control.

```python
# Mini-program API endpoint: authenticate first, then require the feature.
from rest_framework.permissions import IsAuthenticated
from api.authentication import WxJWTAuthentication
from rollout.permissions import feature_permission


class GradeView(APIView):
    authentication_classes = [WxJWTAuthentication]
    permission_classes = [IsAuthenticated, feature_permission('grades')]
```

```python
# Website view: below the two existing decorators.
from rollout.permissions import feature_required


@login_required(redirect_field_name='origin')
@utils.check_user_access(redirect_url='/logout/')
@feature_required('grades')
def grade_page(request): ...
```

```django
{# Template entry, evaluated only when a page reads the variable. #}
{% if rollout_features.grades %}<a href="/grades/">我的成绩</a>{% endif %}
```

```python
# Jobs, domain utilities and anything else.
from rollout.api import is_feature_enabled, enabled_features

if is_feature_enabled(user, 'grades'):
    ...
```

`feature_permission` returns HTTP 403 for an authenticated account without
access and leaves unauthenticated requests to DRF's HTTP 401, which the mini
program answers by renewing its token. `feature_required` raises Django's
`PermissionDenied` (HTTP 403).

## Mini-program API

All endpoints require `WxJWTAuthentication` (missing, malformed or expired
token → 401).

### `GET /api/v2/rollout/features/`

```json
{
  "account": "2600012345",
  "features": {"grades": true},
  "experiments": [
    {
      "key": "grades",
      "name": "我的成绩",
      "description": "在小程序里查看成绩，欢迎反馈显示问题",
      "stage": "preview",
      "enabled": true,
      "reason": "preview"
    }
  ],
  "preview": {
    "joined": true,
    "joined_at": "2026-09-12T20:00:00",
    "can_join": true,
    "join_block_code": null,
    "join_block_message": null
  },
  "feedback": {
    "type_name": "体验反馈",
    "org_type_name": "…",
    "org_name": "智慧书院项目组"
  }
}
```

- `account` is the username of the account the state was evaluated for (the
  account behind the token). A client must not store the state under any other
  account; if its local account differs, its user information is stale.
- `features` lists only enabled keys; a missing key means disabled.
- `experiments` lists features in the `preview` and `rollout` stages, plus
  `internal` features the account is allow-listed for. `ga` and `off`
  features are not listed. `reason` is `null` when `enabled` is `false`.
- `preview.can_join` reports whether the account may join by itself;
  otherwise `join_block_code` is one of the codes below.
- `feedback` is `null` until the preview feedback type and receiving group
  exist (see below).
- The body deliberately has no top-level `code` or `data` key.

### `POST /api/v2/rollout/preview/` and `DELETE /api/v2/rollout/preview/`

Join or leave the preview channel. Both are idempotent and return the same
body as `GET /api/v2/rollout/features/`. Leaving is always allowed.

### Error bodies

Rollout errors use the `{code, message, errors}` envelope that the mini
program's `RequestError` parses:

| Status | `code` | When |
|---|---|---|
| 403 | `feature_not_enabled` | a gated endpoint is called without access; the body also carries `"feature": "<key>"` |
| 403 | `preview_closed` | joining while `rollout.preview_channel.open` is `false` |
| 403 | `preview_person_only` | an organization account tries to join |
| 403 | `preview_inactive` | an inactive (graduated/retired) account tries to join |

### Expected client behavior

- Fetch the state after login, after switching accounts and when the app
  returns to the foreground (throttled). Keep it per account and clear it on
  logout.
- Filter menu entries by `features[key]`.
- Also guard the page itself: pages opened from a share card or QR code bypass
  the menu. Show a placeholder that offers to join the preview channel instead
  of a blank page, and treat `feature_not_enabled` from an API call the same
  way.
- Provide a preview channel page to join or leave, list `experiments`, and
  open feedback for an experiment.
- Experimental front-end code ships in the reviewed release build. Add the
  WeChat review test account to the allow list of every feature under test
  (WeChat review rules 3.1.4 and 3.3.4 require hidden features to be usable
  with the test account).

## Preview feedback

Preview feedback goes to the receiving group configured in
`rollout.feedback.org_name` (智慧书院项目组) through the feedback type
`rollout.feedback.type_name` (体验反馈). Create the type once per deployment:

```bash
python manage.py setup_preview_feedback
```

The command is idempotent. It fails if the receiving group does not exist, or
if a type with that name already points to another group.

`POST /api/v2/feedback/` accepts two optional fields:

- `feature_key`: an existing feature key. When present, `type` must be the
  preview feedback type and `org`/`otype` (when given) must be the configured
  receiving group. A draft may leave `org`/`otype` empty. The key cannot be
  changed afterwards, and every later modification or submission of that
  feedback — through the API or the website — is checked the same way
  (`rollout.api.preview_feedback_routing_errors`).
- `client_info`: at most 8 short strings describing the client, e.g.
  `{"platform": "mp-weixin", "env_version": "release", "app_version": "1.4.0",
  "page": "pages-timetable/grades"}`. No personal data.

Both are stored on `feedback.Feedback` and visible in the admin site, where
feedback can be filtered by `feature_key`. Preview feedback should default to
not public on the client.

## Configuration

```json
"rollout": {
    "preview_channel": {"open": true},
    "feedback": {"type_name": "体验反馈", "org_name": "智慧书院项目组"}
}
```

Every setting has this default, so a `config.json` without the `rollout`
section still starts. Restart the process after editing `config.json`.
Runtime access is changed in the admin site, not here.

## Releasing a feature

1. **Build it switched off.** Put the feature in its own app or module, keep
   migrations additive (new tables, nullable columns), and gate every entry
   point with one key. Scheduled jobs must check the key too.
2. **Create the feature row** in the admin site with stage `internal`, an
   owner and a review date. Add developers and the WeChat review test account
   to the allow list, then deploy and submit the mini program for review.
3. **Preview.** Move to `preview`, optionally with an audience. Announce the
   preview channel; watch preview feedback filtered by `feature_key`.
4. **Roll out.** Move to `rollout` and raise `percent` step by step.
5. **Decide by the review date.** Either move to `ga` and, in the next release,
   delete the checks and the feature row; or move to `off`, remove the code and
   only then drop its data.

Use stage `off` as the kill switch at any time.

## Pilot: grades

Grades (`academic_record`, sprint 2 of the timetable work) is the first
feature released this way. After both this app and the timetable backend are
merged:

1. Add `feature_permission('grades')` to the grade endpoints and
   `feature_required('grades')` to any grade website view.
2. Create the `grades` feature (stage `internal`) and allow-list the team.
3. In the mini program, tag the 我的成绩 entry and page with `grades`.
