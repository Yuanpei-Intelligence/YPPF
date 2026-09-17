## Overview

This directory contains the Django REST Framework backend for the YPPF WeChat
mini-program. These scoped instructions supplement the repository-wide rules
in [`../AGENTS.md`](../AGENTS.md); both apply to files under `api/`. The
mini-program frontend is maintained separately at
https://github.com/HelloWorldZTR/YPPF-mini.

## Development

When debugging is enabled, inspect the generated drf-spectacular schema at
`/api/schema/`, Swagger UI at `/api/docs/`, or ReDoc at
`/api/docs/redoc/`.

Use the development environment and project-wide test workflow documented in
[`../AGENTS.md`](../AGENTS.md). API-only tests may be run inside the configured
container with `python manage.py test api`, but changes that touch shared
models or website services require the full `python manage.py test` suite.
Mini-program configuration is declared in `api/config.py` and stored under
the `wx_miniapp` section of the local `config.json`; follow the root
configuration rules and never hard-code or commit credentials.

## File Structure

`boot/urls.py` mounts `api/urls.py` at `/api/`. The API root router then mounts
feature modules under `/api/v2/<module>/`. Do not place endpoint
implementations directly in the `api/` root. Each feature module should own
its `urls.py`, `views.py`, serializers, tests, and feature-specific helpers,
then be registered with `include()` in `api/urls.py`.

| Path | Responsibility | Route prefix |
| --- | --- | --- |
| `urls.py` | Root mini-program router and debug-only OpenAPI, Swagger, and ReDoc registration. | `/api/`; feature APIs begin at `/api/v2/`, while documentation uses `/api/schema/`, `/api/docs/`, and `/api/docs/redoc/`. |
| `authentication.py` | Shared DRF authentication classes for JWT and one-time webview tickets, plus schema integration. | Used by views and authentication settings; it has no routes of its own. |
| `config.py` | Typed `WXMiniappConfig` access to app ID, secret, WeChat session endpoint, token lifetimes, and ticket TTL. | No routes. |
| `auth/` | WeChat code login, account binding/unbinding, login checks, account listing, and one-time webview ticket exchange. | `/api/v2/auth/` |
| `user/` | Current-user profile and daily-login reward. | `/api/v2/user/` |
| `notification/` | Notification listing, statistics, and read/status updates. | `/api/v2/notification/` |
| `feedback/` | Feedback metadata, creation, listing, detail, and updates. | `/api/v2/feedback/` |
| `appoint/` | Room availability, appointment creation/cancellation/renewal, checkout, violations, agreements, and user search. | `/api/v2/appoint/` |
| `activity/` | Activity homepage/listing and activity signup/check-in operations. | `/api/v2/activity/` |
| `library/` | Library welcome/configuration, book search, reader data, and lending records. | `/api/v2/library/` |
| `YQpools/` | YQPoint balance, prize-pool listing, exchange, lottery, and random purchase. Preserve the directory and URL capitalization. | `/api/v2/YQpools/` (case-sensitive) |
| `org/` | Organization subscription listing and subscription status updates. | `/api/v2/org/` |
| `generic/` | Cross-feature mini-program data, currently the homepage carousel. | `/api/v2/generic/` |
| `pku_account/` | PKU (IAAA) account binding: portal login with one-time credentials, binding status, consents, unbinding. Contract in `timetable/README.md` §3. | `/api/v2/pku/` |
| `timetable/` | Personal timetable: terms, week view and agenda following the university calendar (suspended lessons, 调休 copies, 照常上课 overrides), whole-term overview for the poster, stored entries with per-week overrides (scoped edits) and catalog links, catalog search and quick add (旁听), portal/text import, settings (source toggles, hidden tags), ICS link, subscribe-message quota, exam schedule source, poster share assets. Contract in `timetable/README.md` §4, §6, §8, §10 and §11. | `/api/v2/timetable/` |
| `academic_record/` | Consent-gated grade records fetched through the PKU binding: stored grades, live sync, deletion. Contract in `timetable/README.md` §6.2. | `/api/v2/grades/` |

Many modules use DRF `DefaultRouter`; routes generated from ViewSets and
`@action` methods may therefore not appear as explicit `path()` entries. When
adding an endpoint, inspect both the module router and `api/urls.py`, preserve
existing basename and route naming conventions, add serializers for request
and response contracts, and add tests in the same feature module.

## Authentication and Interaction

The mini-program uses three separate credentials. They are not
interchangeable:

| Credential | Purpose | Issued by | Lifetime and storage | Transport |
| --- | --- | --- | --- | --- |
| `signed_openid` | Proves the WeChat identity only during first-time account binding. It is not an API login credential. | `issue_binding_credential()` in `api/auth/binding.py` after an unbound `wx.login` exchange. | `signed_openid_ttl_minutes` (10 minutes by default). Its versioned, purpose-bound signed random nonce is returned only to the client; one `PendingWechatBinding` per openid stores the digest, expiry, and shared failed-attempt count. Reissuance rotates the nonce without resetting failures. Success deletes the row; exhaustion retains a locked tombstone until expiry. | JSON body of `POST /api/v2/auth/wx/bind/`. |
| JWT access token | Authenticates normal mini-program API requests and identifies the currently selected person or organization account. | `_issue_jwt_for_user()` after login or binding. | `token_expire_minutes` (120 minutes by default). The client stores it and obtains a new token by logging in again; there is currently no refresh-token endpoint. | `Authorization: Bearer <token>`. Never place it in a URL. |
| WebView ticket | Converts an authenticated mini-program identity into a Django session for a website WebView without exposing the JWT in the URL. | `POST /api/v2/auth/ticket/`, which requires a valid JWT. | `ticket_ttl_seconds` (60 seconds by default). Only a digest, user, purpose, and expiry are stored in `PendingWebviewTicket`; redemption locks and deletes the database row atomically. | Query parameter to `/redirect/?ticket=<ticket>&to=<path>`. |

The relevant implementation is split across `api/auth/views.py` (flows and
JWT issuance), `api/auth/binding.py` (digest-only pending credential issuance
and atomic one-time redemption), `api/auth/ticket.py` (ticket
creation/consumption), `api/authentication.py` (DRF authenticators),
`generic/models.py` (`UserWechatProfile`, `PendingWechatBinding`, and
`PendingWebviewTicket`), and `generic/views.py` (the WebView redirect bridge).

### First-time binding

1. The mini-program calls `wx.login()` and sends its temporary `code` to
   `POST /api/v2/auth/wx/login/`. This endpoint is public (`AllowAny`).
2. The backend exchanges the code for an `openid` through the configured
   WeChat `jscode2session` endpoint. App ID, secret, endpoint, and TTL values
   come from `api.config.CONFIG`; they must not be hard-coded.
3. If no `UserWechatProfile` has that `openid`, the response has
   `status="unbound"` and a short-lived `signed_openid`. Its bearer value is a
   versioned, purpose-bound signed random nonce, not an openid. The database
   stores only its digest, openid, expiry, and failed-attempt count; it is a
   one-time handoff between login and binding, never authentication for
   another endpoint. Reissuing for the same openid rotates the nonce and
   invalidates the prior credential without resetting failures.
4. The client sends `signed_openid`, the YPPF `username`, and `password` to
   `POST /api/v2/auth/wx/bind/`, which is also public.
5. The backend verifies the signature and age, locks the pending credential
   row, authenticates the YPPF credentials, and requires a personal account.
   Organizations must be used through a personal administrator and cannot be
   bound directly. The default password-attempt limit is 5 per openid across
   all credentials issued during the current TTL window.
6. Inside the profile-creation transaction, the backend creates a
   `UserWechatProfile` only for an unbound account and consumes the locked
   pending row. Its one-to-one `user` field and unique `openid` field enforce
   at most one WeChat identity per user and one user per WeChat identity.
   Binding rejects an existing account or openid binding; it never silently
   rebinds or updates a profile.
7. A successful binding immediately returns the user's JWT access token.
   Clients must restart `wx.login()` after credential expiry or replay. After
   failed-attempt exhaustion, new issuance remains blocked until the retained
   ledger row expires.

Never log the WeChat code, raw `openid`, `signed_openid`, password, app secret,
JWT, or ticket. Binding changes must preserve signature expiry, database
uniqueness, transaction locking, and the restriction to personal accounts.

### JWT login and account selection

For later logins, the client again sends a fresh `wx.login()` code to
`POST /api/v2/auth/wx/login/`. The resolved `openid` selects the bound
personal account through `UserWechatProfile`:

- Without `username`, the backend issues a JWT for the bound personal account.
- With `username`, the backend treats the bound person as the main account and
  verifies that the requested account is either that person or an organization
  for which the person has an active administrator position. The JWT's user is
  the selected account, while `account_id` remains the main person's username.
- Account switching is another call to the same login endpoint with the target
  `username`; clients must not edit claims or reuse another account's token.

Issued tokens include SimpleJWT's user identity plus `sub`, `username`,
`name`, `account_id`, `iat`, `exp`, and `scope="wx_miniapp"`. In protected
views, `request.user` is the selected person or organization and
`request.auth` is the validated token. `account_id` identifies the bound main
person; it is not a substitute for checking the selected user's current
database permissions. `WxJWTAuthentication` delegates signature, expiry, and
user validation to SimpleJWT and additionally turns a missing bearer header
into a 401 response. The current authenticator does not explicitly enforce
the `scope` claim, so new authorization logic must not assume that merely
checking `scope` is sufficient unless scope validation is added centrally.

The protected authentication-management endpoints `/wx/unbind/`,
`/my-accounts/`, `/check-login/`, and `/ticket/` use the same JWT pairing.
The `access_token` obtained by `api/auth/wechat_api.py` is different: it is a
server-to-WeChat API credential cached by the backend, never a user identity
or a token accepted from the mini-program client.

### WebView ticket bridge

1. An authenticated client sends `POST /api/v2/auth/ticket/` with its bearer
   JWT.
2. `create_webview_ticket()` creates a cryptographically random token and
   stores only its digest, selected user, `webview_login` purpose, and expiry
   in the shared database.
3. The client opens `/redirect/?ticket=<ticket>&to=<path>` in the WebView.
4. `TicketAuthentication` locks and atomically deletes the database row,
   loads the user, and `redirect_to_webview()` establishes a normal Django
   session before redirecting to the validated local `to` path.

A ticket is single-purpose, short-lived, and intended for one use. Never use
`TicketAuthentication` on ordinary API endpoints, persist raw tickets, retry
a consumed ticket, or send it to another host. Ticket creation and redirect
consumption must use the same database. Redirect targets accept single-slash local paths and HTTP(S) absolute URLs
whose host and port exactly match `global.base_url`, preserving compatibility
with existing mini-program clients. HTTPS requests reject HTTP targets.
Protocol-relative, backslash, untrusted-host, and other unsafe destinations
fall back to a fixed local path. Configure `global.base_url` with the public
website address; request Host headers do not expand the trusted host set.

### Embedded WebView navigation patch

Pages based on `templates/base.html` load `static/assets/js/custom.js`, which
contains a small client-side patch for the WeChat mini-program WebView. It
checks whether `navigator.userAgent` contains the case-sensitive string
`miniProgram`. When matched, it hides `.header-container`,
`.sub-header-container`, and `.sidebar-wrapper`, then resets every margin and
padding on `#content` to zero. This prevents the website navbar/sidebar from
duplicating the mini-program's native navigation and gives embedded content
the full viewport.

This behavior is not a server-side template flag and does not automatically
apply to standalone templates that omit `custom.js`, including pages outside
the main base-template family. A new website page intended for mini-program
WebView use should extend `base.html` or deliberately load the same shared
script, retain the selectors expected by the patch, and avoid copying the
detection snippet into another template. Test the page both in an ordinary
browser, where navigation must remain visible, and inside the mini-program,
where the website navigation and extra content spacing must disappear.

### Configuring permissions for new endpoints

Authentication establishes identity; permissions decide whether that
identity may perform the action. Configure both explicitly on every new API
view or ViewSet instead of relying on the project-wide DRF defaults.

For the normal case—any logged-in mini-program user—use:

```python
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from api.authentication import WxJWTAuthentication


class FeatureView(APIView):
    authentication_classes = [WxJWTAuthentication]
    permission_classes = [IsAuthenticated]
```

This pairing is required: `WxJWTAuthentication` validates the bearer token
and produces `request.user`, while `IsAuthenticated` rejects unauthenticated
users. Do not use the global `SessionAuthentication` or standard
`JWTAuthentication` for mini-program-only endpoints; the custom class keeps
missing credentials consistently at HTTP 401 rather than treating them as an
anonymous request that later becomes HTTP 403.

Use the following decision rules:

- Public bootstrap/content endpoints use `permission_classes = [AllowAny]`.
  If the endpoint must ignore all credentials, also set
  `authentication_classes = []`, as `api/generic/CarouselView` does. Login and
  binding are the only public endpoints allowed to exchange WeChat or YPPF
  credentials.
- Role-, capability-, or object-restricted endpoints still start with
  `WxJWTAuthentication` and `IsAuthenticated`, then add a focused DRF
  `BasePermission` or an explicit domain check. Use `has_permission()` for
  request-level rules and `has_object_permission()` for a retrieved object.
- Scope querysets by `request.user` before lookup so another user's object is
  not exposed before object permission runs. DRF does not automatically apply
  object permissions to arbitrary custom ViewSet actions; call
  `check_object_permissions()` when needed.
- When using Django permissions, call
  `request.user.has_perm('app_label.codename')` so the project's
  `BlacklistBackend` and permission blacklist are honored. Do not inspect
  groups or permission tables manually in a view.
- For organization actions, authorize the current selected account from
  `request.user` and re-check current `Position`/domain data where a personal
  administrator relationship matters. Do not trust a client-supplied
  username, `account_id`, or other JWT display claim as the authorization
  decision by itself.
- Reserve `TicketAuthentication` for the `/redirect/` WebView bridge and
  reserve `signed_openid` for `/wx/bind/`. `signed_openid` is a signed random
  versioned, purpose-bound nonce backed by a digest-only pending row;
  redemption locks and consumes it in the profile-creation transaction. Only
  one row exists per openid, and rotating its nonce does not reset its shared
  failure count. It expires, is one-time, permits 5 failed password attempts
  by default, and remains locked after exhaustion until expiry. Neither
  credential may replace JWT authentication on feature APIs.

Document the authentication requirement and 401/403 responses with
`extend_schema`. Add tests for anonymous access, missing/malformed/expired
JWTs, authorized and unauthorized users, cross-user object access, and any
person-versus-organization behavior. Authentication changes must additionally
test expired or forged `signed_openid` values and ticket expiry/replay as
applicable.

### Why HTTP 401 and 403 must remain distinct

The distinction is part of the contract with the YPPF mini-program frontend,
not merely an HTTP style preference. In the sibling frontend repository,
`src/store/token.ts` exposes `wxLogin()` to obtain and persist a replacement
JWT. The response interceptor in `src/http/http.ts` interprets every HTTP or
business-code 401 as an authentication failure: outside its login/binding
exclusion list, it calls `tokenStore.wxLogin()` and then retries the original
request. A 403 follows the ordinary error path and does not trigger token
renewal.

Backend endpoints must therefore use the status codes consistently:

- Return **401 Unauthorized** only when the server cannot establish a valid
  identity: the bearer token is missing, malformed, expired, has an invalid
  signature, refers to an invalid user, or otherwise fails authentication.
  This tells the client that obtaining a new JWT may make the request valid.
- Return **403 Forbidden** only after authentication succeeded but the current
  person or organization is not allowed to perform the requested action. A
  new token for the same account will not grant the missing permission, so the
  client must not enter its automatic relogin-and-retry path.
- Use **400 Bad Request** (or another appropriate non-authentication status)
  for invalid input and business-rule failures that are unrelated to identity
  or permission.

If a missing or expired token is incorrectly returned as 403, the frontend
will not refresh the login and the user remains stuck on an otherwise
recoverable request. If insufficient permission is incorrectly returned as
401, the frontend may perform an unnecessary WeChat login, retry the same
forbidden request, show misleading login/binding UI, or create a retry loop.
This is why protected endpoints must use both `WxJWTAuthentication` and
`IsAuthenticated`: authentication failures reliably become 401, while a
permission class or domain authorization failure after successful
authentication becomes 403. Never use 401 as a generic "access denied"
response or 403 as a generic "not logged in" response.
