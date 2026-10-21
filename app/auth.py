"""Manager sign-in: the login page, sessions, and keeping everyone else out.

Managers and administrators sign in with their username and password. The sign-in is a signed cookie
(Starlette's SessionMiddleware) holding only the user's id, when it ends, and a short fingerprint of the
password, so changing a password or switching a user off signs them out at once.

Everything except the login page and the static files needs a sign-in while REQUIRE_LOGIN is on (the default).
"""

from datetime import datetime, timezone
import hashlib
import logging
import threading
import time
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.database.connection import get_session
from app.database.queries import User, get_user, get_user_by_username
from app.waste_records.common import DEMO_USERNAME
from app.web import api_error, is_api, render, url_path


logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)

SIGN_IN_ROLES = {"manager", "admin"}
ROLE_NAMES = {"manager": "Manager", "admin": "Administrator", "entry": "Kitchen staff"}
PUBLIC_PREFIXES = ("/login", "/static/")
# A hash to check against when the username does not exist, so a wrong username takes as long as a wrong password.
_DUMMY_HASH = generate_password_hash("no such user")


# ---- trying too many wrong passwords ----------------------------------------------------------

class AttemptLimiter:
    """Locks sign-in for a while after too many wrong passwords (kept in memory, per server process).

    Counted per person (address and username) and per address, so neither one account nor one address
    can be tried over and over. A successful sign-in clears the person's count.
    """

    def __init__(self, max_attempts: int, lock_minutes: int):
        self.max_attempts = max_attempts
        self.window = lock_minutes * 60
        self.address_max = max_attempts * 4
        self._failures: dict[tuple, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key, now) -> list[float]:
        recent = [moment for moment in self._failures.get(key, []) if now - moment < self.window]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def seconds_left(self, address: str, username: str, now: float | None = None) -> int:
        """0 if sign-in is allowed, otherwise how many seconds until it is."""
        now = time.monotonic() if now is None else now
        with self._lock:
            waits = []
            for key, limit in (((address, username.lower()), self.max_attempts), ((address,), self.address_max)):
                recent = self._recent(key, now)
                if len(recent) >= limit:
                    waits.append(self.window - (now - recent[-limit]))
            return max(1, int(max(waits))) if waits else 0

    def failed(self, address: str, username: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            for key in ((address, username.lower()), (address,)):
                self._failures.setdefault(key, []).append(now)
            if len(self._failures) > 5000:  # never grow without bound
                for key in list(self._failures):
                    self._recent(key, now)

    def succeeded(self, address: str, username: str) -> None:
        with self._lock:
            self._failures.pop((address, username.lower()), None)


# ---- the sign-in cookie -----------------------------------------------------------------------

def _fingerprint(user: User) -> str:
    """Changes when the password changes, so old sign-ins stop working."""
    return hashlib.sha256(user.password_hash.encode()).hexdigest()[:16]


def sign_in(request: Request, user: User, remember: bool) -> None:
    settings = request.app.state.settings
    seconds = settings["REMEMBER_DAYS"] * 86400 if remember else settings["SESSION_HOURS"] * 3600
    request.session.clear()   # never keep anything from before signing in
    request.session.update({"uid": user.id, "pv": _fingerprint(user), "exp": int(time.time()) + seconds})


def sign_out(request: Request) -> None:
    request.session.clear()


def signed_in_user(request: Request, db: Session) -> User | None:
    """The signed-in manager, or None if nobody is, the sign-in ran out, or the account changed."""
    session = request.session
    user_id, expires = session.get("uid"), session.get("exp")
    if not isinstance(user_id, int) or not isinstance(expires, (int, float)) or expires < time.time():
        return None
    user = get_user(db, user_id)
    if user is None or not user.active or user.role not in SIGN_IN_ROLES or session.get("pv") != _fingerprint(user):
        return None
    return user


def actor_for(request: Request, db: Session) -> User | None:
    """Who is acting: the signed-in manager, or the demo kitchen user when sign-in is turned off."""
    user = getattr(request.state, "user", None)
    if user is not None:
        return user
    if not request.app.state.settings.get("REQUIRE_LOGIN"):
        return get_user_by_username(db, DEMO_USERNAME)
    return None


def safe_next(target: str | None) -> str:
    """Where to go after signing in: a page of this app, never another site."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or parts.path.startswith("/login"):
        return "/"
    return target


# ---- keeping people out ------------------------------------------------------------------------

def _private(response):
    """Pages are not kept by the browser, so Back after signing out does not show them again."""
    response.headers.setdefault("Cache-Control", "no-store")
    return response


async def require_sign_in(request: Request, call_next):
    """Middleware: sets request.state.user, and turns away anyone who is not signed in."""
    request.state.user = None
    settings = request.app.state.settings
    path = request.url.path
    if not settings.get("REQUIRE_LOGIN"):
        return await call_next(request)
    if path.startswith("/static/"):
        return await call_next(request)
    if path == "/login":
        return _private(await call_next(request))

    try:
        with request.app.state.session_factory() as db:
            request.state.user = signed_in_user(request, db)
    except SQLAlchemyError:
        logger.exception("Could not check the sign-in.")
        return api_error("The database is unavailable.", 503) if is_api(request) else render(
            request, "error.html", 503, status=503, title="Service unavailable",
            message="The database is unavailable. Initialize it and try again.")
    if request.state.user is not None:
        return _private(await call_next(request))

    expired = bool(request.session.get("uid"))
    request.session.clear()
    if is_api(request) or path.startswith("/captures/"):
        return api_error("Sign in to continue.", 401)
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    suffix = "&expired=1" if expired else ""
    return RedirectResponse(f"/login?next={quote(target, safe='')}{suffix}", status_code=303)


# ---- the login page ----------------------------------------------------------------------------

def _login_page(request: Request, *, status_code=200, username="", error="", wait=0, notice="", target="/"):
    return render(request, "login.html", status_code, username=username, error=error, wait=wait, notice=notice,
                  next_url=target, remember_days=request.app.state.settings["REMEMBER_DAYS"])


@router.get("/login", name="login")
def login_page(request: Request, next: str = "", signed_out: str = "", expired: str = "", db: Session = Depends(get_session)):
    if request.app.state.settings.get("REQUIRE_LOGIN") and signed_in_user(request, db) is not None:
        return RedirectResponse(safe_next(next), status_code=303)
    notice = ("You've been signed out." if signed_out else
              "Your sign-in ended. Please sign in again." if expired else "")
    return _login_page(request, notice=notice, target=safe_next(next))


@router.post("/login", name="sign_in")
def login_submit(request: Request, username: str = Form(""), password: str = Form(""), remember: str = Form(""),
                 next: str = Form(""), db: Session = Depends(get_session)):
    settings = request.app.state.settings
    target = safe_next(next)
    username = username.strip()[:80]
    address = request.client.host if request.client else "unknown"
    limiter: AttemptLimiter = request.app.state.login_limiter

    if not username or not password or len(password) > 200:
        return _login_page(request, status_code=400, username=username, target=target,
                           error="Enter your username and your password.")
    wait = limiter.seconds_left(address, username)
    if wait:
        minutes = max(1, round(wait / 60))
        return _login_page(request, status_code=429, username=username, target=target, wait=wait,
                           error=f"Too many wrong attempts. Try again in {minutes} {'minute' if minutes == 1 else 'minutes'}.")

    try:
        user = get_user_by_username(db, username)
    except SQLAlchemyError:
        logger.exception("Could not look up the user.")
        return _login_page(request, status_code=503, username=username, target=target,
                           error="The database is unavailable. Try again in a moment.")
    correct = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)
    if not (user and correct and user.active):
        limiter.failed(address, username)
        logger.warning("Failed sign-in for %r from %s", username, address)
        return _login_page(request, status_code=401, username=username, target=target,
                           error="That username and password don't match. Check them and try again.")
    if user.role not in SIGN_IN_ROLES:
        logger.warning("Sign-in refused for %r: role %s", username, user.role)
        return _login_page(request, status_code=403, username=username, target=target,
                           error="This account can't sign in here. Ask your hotel administrator for manager access.")

    limiter.succeeded(address, username)
    sign_in(request, user, remember=bool(remember))
    logger.info("%s signed in (%s)", user.username, user.role)
    return RedirectResponse(target, status_code=303)


@router.post("/logout", name="sign_out")
def logout(request: Request):
    sign_out(request)
    return RedirectResponse(f"{url_path(request.app, 'login')}?signed_out=1", status_code=303)
