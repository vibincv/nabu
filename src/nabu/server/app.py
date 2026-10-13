"""Review window local API and UI host (Section 10.2).

Security rules implemented here:
- API-1: Host header must be 127.0.0.1:<port> or localhost:<port>; Origin, when sent, must match.
  Every /api request carries the per-run token, which is embedded in the served page.
- API-3: Content-Security-Policy default-src 'self' (plus tight extras below).
- API-5: Cache-Control: no-store and Referrer-Policy: no-referrer on every response.
- API-6: the token is read only from the X-Nabu-Token header, never from the URL.
- The first browser to open the window claims it: it gets an HttpOnly, SameSite=Strict cookie,
  and only a request with that cookie is served the token. Without this, any program or user
  on the computer could fetch the page, read the token and call the API (loopback is shared
  by every local user). A later claimant sees "already open" instead of the window, which
  also makes a hijack visible. Every /api request needs the cookie and the token.
- WebSocket connections are refused; nothing here uses them, and they would skip these checks.

Residual: cookies are not port-specific. If the user opens, in the same browser, a page served
by another program on this machine (another port), that program receives the cookie and could
then open the window itself. This needs a hostile local program and the user's click; it is
documented in the README.
"""

from __future__ import annotations

import platform
import secrets
from collections.abc import Callable
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nabu import __version__, netguard

UI_DIST = Path(__file__).parent / "ui_dist"
TOKEN_HEADER = "x-nabu-token"  # noqa: S105 (header name, not a secret)
TOKEN_PLACEHOLDER = '<meta name="nabu-token" content="">'  # noqa: S105
COOKIE = "nabu_window"

ALREADY_OPEN = """<!doctype html><html lang="en" translate="no"><head><meta charset="utf-8">
<title>Nabu</title></head><body><h1>Nabu is already open</h1><p>The review window is open in
another browser. Use that window, or stop and restart <code>nabu serve</code>.</p>
</body></html>"""

SECURITY_HEADERS: dict[str, str] = {
    "content-security-policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
        "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "cache-control": "no-store",
    "pragma": "no-cache",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
}

UI_NOT_BUILT = """<!doctype html><html lang="en" translate="no"><head><meta charset="utf-8">
<meta name="google" content="notranslate"><title>Nabu</title></head>
<body><h1>Nabu</h1><p>The review UI is not built. Run <code>npm ci && npm run build</code>
in <code>ui/</code>, then restart <code>nabu serve</code>.</p></body></html>"""


class WindowClaim:
    """The per-run token and the cookie of the browser that opened the window first."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.cookie: str | None = None

    def matches(self, cookie: str | None) -> bool:
        return (self.cookie is not None and cookie is not None
                and secrets.compare_digest(cookie.encode("latin-1"), self.cookie.encode()))


def _cookie(headers: dict[str, str]) -> str | None:
    for part in headers.get("cookie", "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE:
            return value
    return None


class GuardMiddleware:
    """Pure ASGI middleware: Host/Origin/cookie/token checks and security headers."""

    def __init__(self, app: ASGIApp, port: int, claim: WindowClaim) -> None:
        self.app = app
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.allowed_origins = {f"http://{h}" for h in self.allowed_hosts}
        self.claim = claim

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":  # websocket: refused before accept
            await send({"type": "websocket.close", "code": 1008})
            return

        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        origin = headers.get("origin")
        path: str = scope["path"]

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                raw = [(k, v) for k, v in message.get("headers", [])
                       if k.decode("latin-1").lower() not in SECURITY_HEADERS]
                raw += [(k.encode(), v.encode()) for k, v in SECURITY_HEADERS.items()]
                message["headers"] = raw
            await send(message)

        def deny(status: int, msg: str) -> Response:
            return JSONResponse({"error": msg}, status_code=status)

        if host not in self.allowed_hosts:
            await deny(421, "wrong host")(scope, receive, send_with_headers)
            return
        if origin is not None and origin not in self.allowed_origins:
            await deny(403, "wrong origin")(scope, receive, send_with_headers)
            return
        if path.startswith("/api/"):
            supplied = headers.get(TOKEN_HEADER, "").encode("latin-1")
            if (not secrets.compare_digest(supplied, self.claim.token.encode())
                    or not self.claim.matches(_cookie(headers))):
                await deny(401, "missing or wrong token")(scope, receive, send_with_headers)
                return
        await self.app(scope, receive, send_with_headers)


def create_app(port: int, token: str | None = None, on_quit: Callable[[], None] | None = None,
               ui_dist: Path = UI_DIST) -> tuple[Starlette, str]:
    netguard.install()
    token = token or secrets.token_urlsafe(32)
    claim = WindowClaim(token)

    async def index(request: Request) -> Response:
        idx = ui_dist / "index.html"
        if not idx.exists():
            return HTMLResponse(UI_NOT_BUILT)
        new_claim = claim.cookie is None
        if not new_claim and not claim.matches(request.cookies.get(COOKIE)):
            return HTMLResponse(ALREADY_OPEN, status_code=409)
        html = idx.read_text(encoding="utf-8")
        if TOKEN_PLACEHOLDER not in html:
            return HTMLResponse("UI build is missing the token placeholder", status_code=500)
        html = html.replace(TOKEN_PLACEHOLDER, f'<meta name="nabu-token" content="{token}">')
        response = HTMLResponse(html)
        if new_claim:  # no await since the check above: two requests cannot both claim
            claim.cookie = secrets.token_urlsafe(32)
            response.set_cookie(COOKIE, claim.cookie, httponly=True, samesite="strict", path="/")
        return response

    async def health(_: Request) -> Response:
        return JSONResponse({"ok": True, "version": __version__})

    async def doctor(_: Request) -> Response:
        # Full report lands with nabu.doctor in M1 (FR-1.1).
        return JSONResponse({"os": platform.system(), "os_version": platform.release(),
                             "python": platform.python_version()})

    async def quit_(_: Request) -> Response:
        if on_quit:
            on_quit()
        return JSONResponse({"ok": True})

    routes = [
        Route("/", index),
        Route("/api/health", health),
        Route("/api/doctor", doctor),
        Route("/api/quit", quit_, methods=["POST"]),
    ]
    assets = ui_dist / "assets"
    if assets.exists():
        routes.append(Mount("/assets", StaticFiles(directory=assets), name="assets"))

    app = Starlette(routes=routes,
                    middleware=[Middleware(GuardMiddleware, port=port, claim=claim)])
    return app, token
