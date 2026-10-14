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

import json
import platform
import secrets
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import anyio
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nabu import __version__, netguard
from nabu.errors import NabuError, TooLarge, UnreadableInput, UnsupportedFormat
from nabu.router import Upload, check_combination, classify
from nabu.server.documents import Conflict, DocumentService, Invalid, NotFound, ReviewDocument

UI_DIST = Path(__file__).parent / "ui_dist"
FILES_HEADER = "x-nabu-files"  # [{"name": ..., "size": ...}] for the raw upload body (no multipart)
MAX_FILES = 20
SSE_KEEPALIVE_S = 15.0
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


def _error(e: NabuError) -> Response:
    status = {NotFound: 404, Conflict: 409, Invalid: 400, TooLarge: 413, UnsupportedFormat: 415,
              UnreadableInput: 422}.get(type(e), 400)
    return JSONResponse({"error": e.message}, status_code=status)


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except ValueError:
        raise Invalid("the request body is not JSON") from None
    if not isinstance(body, dict):
        raise Invalid("the request body must be a JSON object")
    return body


def _image_type(data: bytes) -> str:
    return "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"


async def _read_uploads(request: Request, limit_mb: int) -> list[Upload]:
    """The upload body is the files' bytes back to back; X-Nabu-Files names and sizes them.

    Starlette's multipart parser spools files over 1 MB to a temporary file on disk, which
    FR-11.3 and API-2 forbid, so it is not used. The body is read into memory and the size
    limit is enforced while reading (FR-2.7).
    """
    try:
        meta = json.loads(request.headers.get(FILES_HEADER, ""))
    except ValueError:
        raise Invalid("the upload is missing its file list") from None
    if (not isinstance(meta, list) or not 1 <= len(meta) <= MAX_FILES
            or not all(isinstance(m, dict) and isinstance(m.get("name"), str)
                       and isinstance(m.get("size"), int) and m["size"] >= 0 for m in meta)):
        raise Invalid(f"the upload must list 1 to {MAX_FILES} files with names and sizes")
    limit = limit_mb * 1024 * 1024
    expected = sum(m["size"] for m in meta)
    if expected > limit:
        raise TooLarge(f"the upload is larger than the limit of {limit_mb} MB")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > expected:
            raise Invalid("the upload is longer than its file list says")
    if len(body) != expected:
        raise Invalid("the upload is shorter than its file list says")
    uploads, at = [], 0
    for m in meta:
        name = m["name"].replace("\\", "/").rsplit("/", 1)[-1][:255] or "upload"
        uploads.append(Upload(name, bytes(body[at:at + m["size"]])))
        at += m["size"]
    body.clear()
    return uploads


def create_app(port: int, token: str | None = None, on_quit: Callable[[], None] | None = None,
               ui_dist: Path = UI_DIST, documents: DocumentService | None = None,
               doctor_report: Callable[[], dict] | None = None,
               upload_limit_mb: int = 100) -> tuple[Starlette, str]:
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
        if doctor_report is None:
            return JSONResponse({"os": platform.system(), "os_version": platform.release(),
                                 "python": platform.python_version()})
        return JSONResponse(await anyio.to_thread.run_sync(doctor_report))  # ~1 s of probes

    async def quit_(_: Request) -> Response:
        if documents is not None:
            documents.close_all()
        if on_quit:
            on_quit()
        return JSONResponse({"ok": True})

    def service() -> DocumentService:
        if documents is None:
            raise Conflict("reading documents is not available in this window")
        return documents

    def doc_of(request: Request) -> ReviewDocument:
        return service().get(request.path_params["doc_id"])

    def handled(fn: Callable) -> Callable:
        async def wrapper(request: Request) -> Response:
            try:
                return await fn(request)
            except NabuError as e:
                return _error(e)
        return wrapper

    @handled
    async def upload(request: Request) -> Response:
        svc = service()
        if request.method == "GET":  # the open document, so a reloaded window can resume it
            doc = svc.current
            return JSONResponse({"document_id": doc.id if doc else None,
                                 "state": doc.state if doc else None})
        if svc.current is not None:  # refused before the body is read
            raise Conflict("a document is already open; close it first")
        uploads = await _read_uploads(request, upload_limit_mb)
        kinds = [classify(u, upload_limit_mb) for u in uploads]  # named errors now, not later
        check_combination(uploads, kinds)
        doc = svc.start(uploads)
        return JSONResponse({"document_id": doc.id}, status_code=202)

    @handled
    async def events(request: Request) -> Response:
        doc = doc_of(request)

        async def stream() -> AsyncIterator[str]:
            sent = 0
            while True:
                new = await anyio.to_thread.run_sync(doc.events_after, sent, SSE_KEEPALIVE_S)
                if not new:
                    yield ": keep-alive\n\n"
                    continue
                for ev in new:
                    yield f"data: {json.dumps(ev)}\n\n"
                sent += len(new)
                if new[-1]["type"] in ("done", "error", "cancelled"):
                    return

        return StreamingResponse(stream(), media_type="text/event-stream")

    @handled
    async def document(request: Request) -> Response:
        if request.method == "DELETE":
            service().close(request.path_params["doc_id"])
            return JSONResponse({"ok": True})
        return JSONResponse(doc_of(request).to_dict())

    @handled
    async def page(request: Request) -> Response:
        data = doc_of(request).page_image(request.path_params["n"])
        return Response(data, media_type=_image_type(data))

    @handled
    async def field(request: Request) -> Response:
        f = doc_of(request).edit_field(request.path_params["field_id"], await _json(request))
        return JSONResponse(f.to_dict())

    @handled
    async def add_field(request: Request) -> Response:
        f = doc_of(request).add_field(await _json(request))
        return JSONResponse(f.to_dict(), status_code=201)

    @handled
    async def translation(request: Request) -> Response:
        f = doc_of(request).set_translation(request.path_params["term_id"], await _json(request))
        return JSONResponse(f.to_dict())

    @handled
    async def header(request: Request) -> Response:
        return JSONResponse(doc_of(request).set_header(await _json(request)))

    @handled
    async def page_order(request: Request) -> Response:
        order = (await _json(request)).get("order")
        if not isinstance(order, list) or not all(isinstance(n, int) for n in order):
            raise Invalid("order must be a list of page numbers")
        doc = doc_of(request)
        doc.reorder_pages(order)
        return JSONResponse(doc.to_dict())

    @handled
    async def verify(request: Request) -> Response:
        return JSONResponse(doc_of(request).verify())

    @handled
    async def save(request: Request) -> Response:
        doc_of(request).save(await _json(request))
        return JSONResponse({"ok": True})

    @handled
    async def output(request: Request) -> Response:
        name, data = doc_of(request).output()
        return Response(data, media_type="application/json",
                        headers={"content-disposition": f'attachment; filename="{name}"'})

    d = "/api/documents/{doc_id}"
    routes = [
        Route("/", index),
        Route("/api/health", health),
        Route("/api/doctor", doctor),
        Route("/api/quit", quit_, methods=["POST"]),
        Route("/api/documents", upload, methods=["GET", "POST"]),
        Route(d, document, methods=["GET", "DELETE"]),
        Route(d + "/events", events),
        Route(d + "/pages/{n:int}.png", page),
        Route(d + "/pages/order", page_order, methods=["PUT"]),
        Route(d + "/fields", add_field, methods=["POST"]),
        Route(d + "/fields/{field_id}", field, methods=["PATCH"]),
        Route(d + "/translations/{term_id}", translation, methods=["PATCH"]),
        Route(d + "/header", header, methods=["PATCH"]),
        Route(d + "/verify", verify, methods=["POST"]),
        Route(d + "/save", save, methods=["POST"]),
        Route(d + "/output", output),
    ]
    assets = ui_dist / "assets"
    if assets.exists():
        routes.append(Mount("/assets", StaticFiles(directory=assets), name="assets"))

    app = Starlette(routes=routes,
                    middleware=[Middleware(GuardMiddleware, port=port, claim=claim)])
    return app, token
