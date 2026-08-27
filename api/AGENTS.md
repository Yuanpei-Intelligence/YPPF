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
| `signed_openid` | Proves the WeChat identity only during first-time account binding. It is not an API login credential. | `issue_binding_credential()` in `api/auth/binding.py` after an unbound `wx.login` exchange. | `signed_openid_ttl_minutes` (10 minutes by default). Its versioned, purpose-bound signed random nonce is returned only to the client; one `PendingWechatBinding` per openid stores the digest, expiry, and shared failed-attempt count. Reissuance rotates the nonce without resetting failures. Success deletes the row; exhaustion retains a locked tombstone until expiry. | JSON body of `POST /api/v2/auth/wx/bind/`. |
| JWT access token | Authenticates normal mini-program API requests and identifies the currently selected person or organization account. | `_issue_jwt_for_user()` after login or binding. | `token_expire_minutes` (120 minutes by default). The client stores it and obtains a new token by logging in again; there is currently no refresh-token endpoint. | `Authorization: Bearer <token>`. Never place it in a URL. |
| WebView ticket | Converts an authenticated mini-program identity into a Django session for a website WebView without exposing the JWT in the URL. | `POST /api/v2/auth/ticket/`, which requires a valid JWT. | `ticket_ttl_seconds` (60 seconds by default). Stored in Django cache and deleted when consumed. | Query parameter to `/redirect/?ticket=<ticket>&to=<path>`. |

The relevant implementation is split across `api/auth/views.py` (flows and
JWT issuance), `api/auth/binding.py` (digest-only pending credential issuance
and atomic one-time redemption), `api/auth/ticket.py` (ticket
creation/consumption), `api/authentication.py` (DRF authenticators),
`generic/models.py` (`UserWechatProfile` and `PendingWechatBinding`), and
`generic/views.py` (the WebView redirect bridge).

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

## Exception Handling and Error Responses

New mini-program endpoints use one error contract. The same contract is the
default for a new error branch in an existing endpoint and for an endpoint
whose exception handling is substantially changed. An untouched legacy
endpoint may retain its documented response for compatibility, but legacy
shapes are exceptions, not examples to copy. In particular, the activity
ViewSet currently has its own three-field normalizer whose `errors` values are
string lists; it remains a legacy exception until that whole ViewSet is moved
to the shared handler below. Unless a route or schema explicitly documents a
compatibility exception, implement the new contract first.

Successful responses keep their endpoint-specific body. Do not wrap them in a
new `data`, `code`, or `success` envelope. Every error from an opted-in view has
exactly these top-level fields:

```json
{
  "code": "validation_error",
  "message": "请求参数有误。",
  "errors": {
    "items.0.quantity": [
      {
        "code": "min_value",
        "message": "请确保该值大于等于 1。"
      }
    ]
  }
}
```

The fields have independent purposes:

- `code` is the stable, non-localized machine decision. Generic codes use
  lower-case `snake_case`, such as `validation_error`, `not_authenticated`,
  `invalid_token`, `permission_denied`, `not_found`, `method_not_allowed`,
  `throttled`, and `internal_error`. A domain condition uses a lower-case
  feature namespace and reason, such as `activity.capacity_full`. Do not put
  the HTTP status or a translated sentence in this field. Once consumed by a
  client, a code is a public interface and must not be silently repurposed.
- `message` is a concise, safe, user-facing summary suitable for a toast. It
  may be localized and may change without changing `code`. It must not expose
  a traceback, exception representation, SQL, filesystem path, credential,
  token, upstream response body, or other internal diagnostic information.
- `errors` is always an object, including `{}` for a non-validation error.
  Each key is a request field path and each value is a list of objects with
  exactly `code` and `message`. Join nested serializer keys and zero-based list
  indexes with dots, for example `items.0.quantity`. Use
  `non_field_errors` when the problem belongs to the request as a whole.
  Preserve DRF `ErrorDetail.code` or the equivalent Pydantic validation type;
  clients must not parse the translated message to identify `required`,
  `invalid`, or `min_value` failures.

### Status codes and exception selection

The HTTP status is authoritative for transport behavior; `code` refines the
reason. Use the following mapping consistently:

| Status | Meaning | Typical top-level code |
| --- | --- | --- |
| 400 | Malformed input, serializer validation, or an ordinary rejected business precondition | `parse_error`, `validation_error`, or a feature code |
| 401 | No valid identity can be established; obtaining a new token may fix the request | `not_authenticated`, `invalid_token` |
| 403 | Authentication succeeded but this account cannot perform the action | `permission_denied` or a feature code |
| 404 | The caller-scoped object does not exist, including an intentionally hidden object | `not_found` |
| 405 | The resource does not support the HTTP method | `method_not_allowed` |
| 406 | The requested response representation cannot be produced | `not_acceptable` |
| 409 | A genuine concurrent or current-resource-state conflict, not ordinary form validation | `conflict` or a feature code |
| 415 | Unsupported request content type | `unsupported_media_type` |
| 429 | Request throttling; retain the native `Retry-After` header | `throttled` |
| 500 | An unexpected server failure whose internal detail is logged, not returned | `internal_error` |

Do not return FastAPI's default 422 for request validation when implementing
this shared contract; its validation handler must translate that case to 400.
The existing mini-program interceptor treats HTTP or business-code 401 as a
request to log in and retry, so the 401/403 distinction in the preceding
authentication section remains mandatory. Never use 401 for an authenticated
permission failure or 403 for a missing, malformed, expired, or invalid JWT.

Raise DRF native exceptions for framework conditions: serializer
`ValidationError`, `NotAuthenticated`/`AuthenticationFailed`,
`PermissionDenied`, `NotFound`, `MethodNotAllowed`, `ParseError`,
`UnsupportedMediaType`, or `Throttled`. Raise `api.exceptions.APIError` for a
stable domain-specific API failure. Prefer a semantic `APIError` subclass
when the same failure is reused; a one-off translation at the HTTP boundary
may pass an explicit `code`, `message`, status, and field errors. Do not build
a new error with `Response(...)`, return HTTP 200 with `succeed=false`, or add
new `detail`, `msg`, `warn_code`, or `warn_message` error bodies.

Domain utilities must remain independent of DRF and FastAPI. They may raise a
feature-domain exception; the view catches that narrow expected exception and
translates it to `APIError` with `raise ... from exc`. Catch an anticipated
`IntegrityError` only around the conflicting database statement and translate
it after the transaction is usable. Never send a raw database, external
service, or unexpected Python exception to the client. Unexpected exceptions
are logged by the standardized handler and become a sanitized 500 response.

### Django REST Framework implementation

The shared implementation is opt-in and lives in `api.exceptions`. It is not
configured as the project-wide `REST_FRAMEWORK.EXCEPTION_HANDLER`, because
the repository still contains non-mini-program DRF routes and legacy API
contracts. Place the mixin before the DRF base class so Python resolves its
`get_exception_handler()` method first:

```python
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.authentication import WxJWTAuthentication
from api.exceptions import APIError, StandardizedExceptionHandlerMixin


class FeatureView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = [WxJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FeatureRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = perform_feature(request.user, **serializer.validated_data)
        except CapacityFull as exc:
            raise APIError(
                code="feature.capacity_full",
                message="当前名额已满。",
                status_code=status.HTTP_409_CONFLICT,
            ) from exc
        return Response(FeatureSerializer(result).data)


class FeatureViewSet(StandardizedExceptionHandlerMixin, viewsets.ViewSet):
    authentication_classes = [WxJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def retrieve(self, request, pk=None):
        try:
            feature = caller_scoped_features(request.user).get(pk=pk)
        except Feature.DoesNotExist:
            raise NotFound("记录不存在。")
        return Response(FeatureSerializer(feature).data)
```

The handler delegates recognized exceptions to DRF first, then replaces only
the response body. This preserves native status handling and headers such as
`WWW-Authenticate` and `Retry-After`. It flattens nested DRF validation data
to dotted field paths and retains each `ErrorDetail.code`. Unknown exceptions
are logged server-side and return only `internal_error`.

Use the shared serializer when documenting every expected error status; do
not describe only the status while leaving the response shape unspecified:

```python
from drf_spectacular.utils import OpenApiResponse, extend_schema

from api.exceptions import APIErrorResponseSerializer


@extend_schema(
    responses={
        400: OpenApiResponse(
            response=APIErrorResponseSerializer,
            description="请求参数有误",
        ),
        401: OpenApiResponse(
            response=APIErrorResponseSerializer,
            description="未认证或令牌无效",
        ),
        409: OpenApiResponse(
            response=APIErrorResponseSerializer,
            description="资源状态冲突",
        ),
    }
)
def post(self, request):
    ...
```

Tests for an opted-in endpoint must assert the HTTP status, top-level `code`,
safe `message`, exact `errors` item shape, and any meaningful field codes.
Also cover authentication headers, throttling headers, and sanitization when
those cases apply. A documented compatibility endpoint may assert its legacy
shape, but new tests must not broaden the exception.

### Equivalent FastAPI implementation

FastAPI services use the same JSON contract and status meanings, but integrate
through FastAPI's native exception registration rather than importing this
Django module. Define equivalent Pydantic response models and register
handlers for a service-local domain `APIError`, `RequestValidationError`, and
Starlette/FastAPI `HTTPException`:

```python
import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


class ErrorItem(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    code: str
    message: str
    errors: dict[str, list[ErrorItem]] = Field(default_factory=dict)


class APIError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        errors: dict[str, list[dict[str, str]]] | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.errors = errors or {}


app = FastAPI()


@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "message": exc.message,
            "errors": exc.errors,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors: dict[str, list[dict[str, str]]] = {}
    for item in exc.errors():
        loc = list(item["loc"])
        if loc and loc[0] in {"body", "query", "path", "header", "cookie"}:
            loc = loc[1:]
        field = ".".join(str(part) for part in loc) or "non_field_errors"
        errors.setdefault(field, []).append(
            {"code": item["type"], "message": item["msg"]}
        )
    return JSONResponse(
        status_code=400,
        content={
            "code": "validation_error",
            "message": "请求参数有误。",
            "errors": errors,
        },
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    code_by_status = {
        401: "not_authenticated",
        403: "permission_denied",
        404: "not_found",
        405: "method_not_allowed",
        415: "unsupported_media_type",
        429: "throttled",
    }
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "code": code_by_status.get(exc.status_code, "api_error"),
            "message": (
                exc.detail if isinstance(exc.detail, str) else "请求失败。"
            ),
            "errors": {},
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled API exception",
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return JSONResponse(
        status_code=500,
        content={
            "code": "internal_error",
            "message": "服务器暂时无法处理该请求。",
            "errors": {},
        },
    )
```

Use `responses={...: {"model": ErrorResponse}}` in route declarations so
OpenAPI clients see the same response schema. A production FastAPI application
may provide more specific safe messages and feature codes, but it must retain
headers from `HTTPException` and keep unexpected exception details in logs.
This is a cross-framework implementation reference only; do not add FastAPI
or Pydantic as a dependency of this Django project solely for error handling.
