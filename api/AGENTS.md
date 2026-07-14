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
| `signed_openid` | Proves the WeChat identity only during first-time account binding. It is not an API login credential. | `_sign_openid()` after an unbound `wx.login` exchange. | `signed_openid_ttl_minutes` (10 minutes by default). Signed with Django's `TimestampSigner`; it is short-lived but not consumed on use. | JSON body of `POST /api/v2/auth/wx/bind/`. |
| JWT access token | Authenticates normal mini-program API requests and identifies the currently selected person or organization account. | `_issue_jwt_for_user()` after login or binding. | `token_expire_minutes` (120 minutes by default). The client stores it and obtains a new token by logging in again; there is currently no refresh-token endpoint. | `Authorization: Bearer <token>`. Never place it in a URL. |
| WebView ticket | Converts an authenticated mini-program identity into a Django session for a website WebView without exposing the JWT in the URL. | `POST /api/v2/auth/ticket/`, which requires a valid JWT. | `ticket_ttl_seconds` (60 seconds by default). Stored in Django cache and deleted when consumed. | Query parameter to `/redirect/?ticket=<ticket>&to=<path>`. |

The relevant implementation is split across `api/auth/views.py` (flows and
token issuance), `api/auth/ticket.py` (ticket creation/consumption),
`api/authentication.py` (DRF authenticators), `generic/models.py`
(`UserWechatProfile`), and `generic/views.py` (the WebView redirect bridge).

### First-time binding

1. The mini-program calls `wx.login()` and sends its temporary `code` to
   `POST /api/v2/auth/wx/login/`. This endpoint is public (`AllowAny`).
2. The backend exchanges the code for an `openid` through the configured
   WeChat `jscode2session` endpoint. App ID, secret, endpoint, and TTL values
   come from `api.config.CONFIG`; they must not be hard-coded.
3. If no `UserWechatProfile` has that `openid`, the response has
   `status="unbound"` and a short-lived `signed_openid`. This signed value is
   tamper-evident and time-limited, but it is only a handoff between login and
   binding; do not accept it as authentication for another endpoint.
4. The client sends `signed_openid`, the YPPF `username`, and `password` to
   `POST /api/v2/auth/wx/bind/`, which is also public.
5. The backend verifies the signature and age, authenticates the YPPF
   credentials, and requires a personal account. Organizations must be used
   through a personal administrator and cannot be bound directly.
6. Inside a transaction, the backend creates or updates
   `UserWechatProfile`. Its one-to-one `user` field and unique `openid` field
   enforce at most one WeChat identity per user and one user per WeChat
   identity. Binding fails if the `openid` belongs to another user.
7. A successful binding immediately returns the user's JWT access token.

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
   caches the selected user's primary key under a short TTL.
3. The client opens `/redirect/?ticket=<ticket>&to=<path>` in the WebView.
4. `TicketAuthentication` consumes and deletes the cache entry, loads the
   user, and `redirect_to_webview()` establishes a normal Django session
   before redirecting to `to`.

A ticket is single-purpose, short-lived, and intended for one use. Never use
`TicketAuthentication` on ordinary API endpoints, persist tickets, retry a
consumed ticket, or send it to another host. Ticket creation and redirect
consumption must share the same Django cache; a multi-host deployment needs a
cache backend shared by all participating processes. The current redirect
handler passes `to` to Django without validating that it is local, so callers
must supply an internal path and any new redirect implementation must reject
external, protocol-relative, or otherwise unsafe destinations.

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
  reserve `signed_openid` for `/wx/bind/`. Neither may replace JWT
  authentication on feature APIs.

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
