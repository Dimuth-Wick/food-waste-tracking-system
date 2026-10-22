"""Shared web plumbing: templates, URL building, error responses, size limit."""

import logging
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context, pass_environment
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=Path(__file__).with_name("templates"))
STATIC_DIR = Path(__file__).with_name("static")
MAX_REQUEST_BYTES = 9 * 1024 * 1024  # an 8 MB photo plus form overhead


def _all_routes(routes):
    """Every route, including those inside included routers."""
    for route in routes:
        if hasattr(route, "original_router"):
            yield from _all_routes(route.original_router.routes)
        else:
            yield route


def url_path(app: FastAPI, name: str, **params) -> str:
    """Relative URL for a named route. Extra keyword arguments become the query string.

    url_path(app, "edit_record", record_id=3, updated=1) -> "/records/3/edit?updated=1"
    url_path(app, "static", filename="styles.css")      -> "/static/styles.css"
    """
    if name == "static" and "filename" in params:
        params["path"] = params.pop("filename")
        # Version by modified time so browsers never keep serving an outdated stylesheet or script.
        try:
            params["v"] = int((STATIC_DIR / params["path"]).stat().st_mtime)
        except OSError:
            pass
    route = next((route for route in _all_routes(app.router.routes) if getattr(route, "name", None) == name), None)
    path_names = set(getattr(route, "param_convertors", {}) or {})
    path = app.url_path_for(name, **{key: value for key, value in params.items() if key in path_names})
    query = {key: value for key, value in params.items() if key not in path_names}
    return f"{path}?{urlencode(query)}" if query else str(path)


@pass_context
def _template_url_for(context, name, **params):
    return url_path(context["request"].app, name, **params)


templates.env.globals["url_for"] = _template_url_for


@pass_environment
def _money(env, value) -> str:
    """12340.6 -> "Rs 12,341": whole rupees, since prices are approximate."""
    return f"{env.globals.get('CURRENCY_SYMBOL', 'Rs')} {round(float(value or 0)):,}"


templates.env.filters["money"] = _money
templates.env.filters["amount"] = lambda value: f"{round(float(value or 0)):,}"


def render(request: Request, template: str, status_code: int = 200, **context):
    context.setdefault("current_user", getattr(request.state, "user", None))
    monitor = getattr(request.app.state, "camera_monitor", None)
    if monitor is not None and "camera_alerts" not in context:
        try:
            context["camera_alerts"] = monitor.offline()
        except Exception:   # a warning must never stop a page from showing
            context["camera_alerts"] = []
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def api_error(message: str, status_code: int, **extra):
    return JSONResponse({"error": message, **extra}, status_code=status_code)


ERROR_TITLES = {
    403: ("You can't change this record", "In this demo, kitchen staff can only edit records they created."),
    404: ("Page not found", "The page or record does not exist. It may have been removed."),
    405: ("Action not allowed", "This page can't be used that way."),
    413: ("Upload too large", "Choose an image smaller than 8 MB."),
    503: ("Service unavailable", "The database is unavailable. Initialize it and try again."),
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, error: StarletteHTTPException):
        if is_api(request):
            return api_error(str(error.detail), error.status_code)
        title, message = ERROR_TITLES.get(error.status_code, ("Something went wrong", str(error.detail)))
        if error.status_code == 503 and error.detail and error.detail != "Service Unavailable":
            message = str(error.detail)
        return render(request, "error.html", error.status_code, title=title, message=message,
                      status=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        if not is_api(request):
            return render(request, "error.html", 404, status=404, title=ERROR_TITLES[404][0],
                          message=ERROR_TITLES[404][1])
        fields = {}
        for problem in error.errors():
            field = str(problem["loc"][-1]) if problem.get("loc") else "body"
            fields[field] = problem["msg"].removeprefix("Value error, ")
        if any(problem.get("type") == "json_invalid" for problem in error.errors()) or "body" in fields:
            return api_error("Request must be JSON with Content-Type: application/json.", 400)
        return api_error("Validation failed.", 400, fields=fields)


class RequestSizeLimit:
    """Reject request bodies over ``max_bytes`` with 413, before the app reads them all."""

    def __init__(self, app, max_bytes: int = MAX_REQUEST_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            return await self._too_large(scope, send)

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLarge:
            if not started:
                await self._too_large(scope, send)

    async def _too_large(self, scope, send):
        response = JSONResponse({"error": "Choose an image smaller than 8 MB."}, status_code=413)
        await response(scope, None, send)


class _BodyTooLarge(Exception):
    pass
