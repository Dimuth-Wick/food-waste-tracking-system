"""App settings, read from environment variables with local-demo defaults.

DATABASE_URL       SQLAlchemy URL. Defaults to the SQLite file in instance/.
                   For PostgreSQL: postgresql+psycopg://user:password@host/dbname
ML_MODEL_SKIP      Set to 1 to start without loading the forecast model.

Camera capture (see README, "Automatic camera capture"):
TIMEZONE           Time zone for the meal schedule. Default Asia/Colombo.
MEAL_SCHEDULE      When start and end photos are taken, as
                   "breakfast=06:00/10:00;lunch=12:00/14:30;dinner=19:00/22:00".
CAMERA_SOURCES     The buffet cameras, one per station, as
                   "Station 1=http://192.168.1.20:8080/video;Station 2=rtsp://user:pass@host/stream".
                   Use a number such as "Station 1=0" for a webcam plugged into this computer.
                   Camera addresses and passwords belong here, in the environment, never in code.
PHOTOS_PER_CAPTURE Photos per capture when there is a single camera (default 4).
CAPTURE_TEST_MODE  Set to 1 to ignore the meal times and capture every 15 seconds.
CAPTURE_TEST_SECONDS Seconds between captures in test mode (default 15).
CAPTURE_DIR        Where photos are saved. Default instance/captures.

Camera offline alerts (see README, "Camera offline alerts"):
CAMERA_CHECK_MINUTES  How often each camera is checked between meals. Default 5.
CAMERA_OFFLINE_AFTER  Failed checks in a row before a camera counts as offline. Default 3.
CAMERA_ALERTS         Set to 0 to turn the alert emails off (the warning on screen stays). Default on.

Waste value (see README, "Waste value"):
CURRENCY_CODE      Currency of the prices. Default LKR (Sri Lankan rupees).
CURRENCY_SYMBOL    Shown before amounts. Default "Rs".

Weekly email report (see README, "Weekly email report"):
ADMIN_EMAIL        The address reports are sent from (the system's admin email).
SMTP_HOST          The mail server, for example smtp.gmail.com. Reports are off until this and ADMIN_EMAIL are set.
SMTP_PORT          Default 587.
SMTP_USER          Login name. Default: ADMIN_EMAIL.
SMTP_PASSWORD      Login password (for Gmail, an app password). Keep it in the environment, never in code.
SMTP_SECURITY      starttls (default), ssl or none.
REPORT_DAY         Day the report is sent: mon..sun. Default sun.
REPORT_TIME        Time it is sent, HH:MM in TIMEZONE. Default 18:00.
PUBLIC_URL         Address of this app, for the link in the email. Default http://localhost:5000.

Sign-in (see README, "Signing in"):
REQUIRE_LOGIN      Managers and administrators must sign in. Default on; set to 0 to turn it off.
SECRET_KEY         Signs the sign-in cookie. Default: a random key created once in instance/secret_key.
SESSION_HOURS      How long a normal sign-in lasts. Default 8.
REMEMBER_DAYS      How long "Keep me signed in" lasts. Default 30.
LOGIN_MAX_ATTEMPTS Wrong passwords allowed before a short lock. Default 5.
LOGIN_LOCK_MINUTES How long that lock lasts. Default 15.
"""

import os
import re
import secrets
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = PROJECT_ROOT / "instance" / "food_waste.sqlite3"
DEFAULT_CAPTURE_DIR = PROJECT_ROOT / "instance" / "captures"
SECRET_KEY_FILE = PROJECT_ROOT / "instance" / "secret_key"

DEFAULT_TIMEZONE = "Asia/Colombo"
# Lunch and dinner are placeholders until the kitchen confirms its real times.
DEFAULT_MEAL_SCHEDULE = {
    "breakfast": {"start": "06:00", "end": "10:00"},
    "lunch": {"start": "12:00", "end": "14:30"},
    "dinner": {"start": "19:00", "end": "22:00"},
}
DEFAULT_PHOTOS_PER_CAPTURE = 4
DEFAULT_PHOTO_GAP_SECONDS = 2.0
DEFAULT_TEST_SECONDS = 15

REPORT_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_TIME = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}")


def parse_meal_schedule(value) -> dict[str, dict[str, str]]:
    """Accept a dict, or "breakfast=06:00/10:00;lunch=12:00/14:30". Raises ValueError if it is wrong."""
    if isinstance(value, str):
        value = value.strip()
        parsed = {}
        for part in filter(None, (piece.strip() for piece in value.replace("\n", ";").split(";"))):
            meal, separator, times = part.partition("=")
            start, slash, end = times.partition("/")
            if not (separator and slash):
                raise ValueError(f'MEAL_SCHEDULE entry "{part}" must look like breakfast=06:00/10:00.')
            parsed[meal.strip().lower()] = {"start": start.strip(), "end": end.strip()}
        value = parsed
    if not value:
        raise ValueError("MEAL_SCHEDULE must list at least one meal.")
    schedule = {}
    for meal, times in value.items():
        meal = str(meal).strip().lower()
        if not re.fullmatch(r"[a-z]{3,20}", meal):
            raise ValueError(f'MEAL_SCHEDULE meal name "{meal}" must be letters only.')
        start, end = str(times.get("start", "")), str(times.get("end", ""))
        if not (_TIME.fullmatch(start) and _TIME.fullmatch(end)):
            raise ValueError(f"MEAL_SCHEDULE times for {meal} must be HH:MM, such as 06:00/10:00.")
        if start >= end:
            raise ValueError(f"MEAL_SCHEDULE: {meal} must end after it starts.")
        schedule[meal] = {"start": start, "end": end}
    return schedule


def parse_camera_sources(value) -> list[dict[str, str]]:
    """Accept a list of {"name", "url"}, or "Station 1=http://...;Station 2=rtsp://...".

    Raises ValueError if it is wrong. The address is kept out of every error message.
    """
    if isinstance(value, str):
        value = [{"name": name.strip(), "url": url.strip()}
                 for name, separator, url in (part.partition("=") for part in
                                              value.replace("\n", ";").split(";") if part.strip())
                 if separator]
    cameras, seen = [], set()
    for entry in value or []:
        name, url = str(entry.get("name", "")).strip(), str(entry.get("url", "")).strip()
        if not _NAME.fullmatch(name):
            raise ValueError("CAMERA_SOURCES: each camera needs a name (letters, numbers, spaces) before the = sign.")
        if name.lower() in seen:
            raise ValueError(f'CAMERA_SOURCES: the name "{name}" is used twice.')
        if not (url.isdigit() or re.match(r"(https?|rtsp)://\S+$", url)):
            raise ValueError(f'CAMERA_SOURCES: the address for "{name}" must start with http://, https:// or '
                             "rtsp://, or be a webcam number such as 0.")
        seen.add(name.lower())
        cameras.append({"name": name, "url": url})
    return cameras


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _default_on(name: str) -> bool:
    """A flag that is on unless the environment says 0, false, no or off."""
    return os.environ.get(name, "").strip().lower() not in {"0", "false", "no", "off"}


def _secret_key(testing: bool) -> str:
    """The key that signs the sign-in cookie: from SECRET_KEY, else created once and kept in instance/."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    if testing:
        return "test-secret-key-not-for-real-use"
    try:
        if SECRET_KEY_FILE.is_file() and SECRET_KEY_FILE.read_text(encoding="utf-8").strip():
            return SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
        SECRET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        SECRET_KEY_FILE.write_text(key, encoding="utf-8")
        return key
    except OSError:  # a read-only folder: a key for this run only, so people sign in again after a restart
        return secrets.token_urlsafe(48)


def load_settings(overrides=None):
    """Return the settings dict. Tests pass overrides, such as a temporary DATABASE.

    Keys other code reads:
        DATABASE_URL, TESTING, ML_MODEL_SKIP, ML_MODEL_PATH, ML_MODEL,
        FOOD_CLASSIFIER_MODEL, FOOD_CLASSIFIER_MODEL_PATH,
        FOOD_COUNTER, FOOD_COUNTER_MODEL_NAME,
        TIMEZONE, MEAL_SCHEDULE, CAMERA_SOURCES, PHOTOS_PER_CAPTURE, PHOTO_GAP_SECONDS,
        CAPTURE_TEST_MODE, CAPTURE_TEST_SECONDS, CAPTURE_DIR, FRAME_GRABBER (tests), CAPTURE_SCHEDULER_SKIP,
        ADMIN_EMAIL, SMTP_*, REPORT_DAY, REPORT_TIME, PUBLIC_URL, REPORT_SCHEDULER_SKIP
    """
    settings = {
        "DATABASE_URL": os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE.as_posix()}"),
        "TESTING": False,
        "ML_MODEL_SKIP": os.environ.get("ML_MODEL_SKIP") == "1",
        "TIMEZONE": os.environ.get("TIMEZONE", DEFAULT_TIMEZONE),
        "MEAL_SCHEDULE": os.environ.get("MEAL_SCHEDULE") or DEFAULT_MEAL_SCHEDULE,
        "CAMERA_SOURCES": os.environ.get("CAMERA_SOURCES", ""),
        "PHOTOS_PER_CAPTURE": os.environ.get("PHOTOS_PER_CAPTURE", DEFAULT_PHOTOS_PER_CAPTURE),
        "PHOTO_GAP_SECONDS": os.environ.get("PHOTO_GAP_SECONDS", DEFAULT_PHOTO_GAP_SECONDS),
        "CAPTURE_TEST_MODE": _flag("CAPTURE_TEST_MODE"),
        "CAPTURE_TEST_SECONDS": os.environ.get("CAPTURE_TEST_SECONDS", DEFAULT_TEST_SECONDS),
        "CAPTURE_DIR": os.environ.get("CAPTURE_DIR", str(DEFAULT_CAPTURE_DIR)),
        "CURRENCY_CODE": os.environ.get("CURRENCY_CODE", "LKR"),
        "CURRENCY_SYMBOL": os.environ.get("CURRENCY_SYMBOL", "Rs"),
        "CAMERA_CHECK_MINUTES": os.environ.get("CAMERA_CHECK_MINUTES", 5),
        "CAMERA_OFFLINE_AFTER": os.environ.get("CAMERA_OFFLINE_AFTER", 3),
        "CAMERA_ALERTS": _default_on("CAMERA_ALERTS"),
        "ADMIN_EMAIL": os.environ.get("ADMIN_EMAIL", "").strip(),
        "SMTP_HOST": os.environ.get("SMTP_HOST", "").strip(),
        "SMTP_PORT": os.environ.get("SMTP_PORT", 587),
        "SMTP_USER": os.environ.get("SMTP_USER", "").strip(),
        "SMTP_PASSWORD": os.environ.get("SMTP_PASSWORD", ""),
        "SMTP_SECURITY": os.environ.get("SMTP_SECURITY", "starttls").strip().lower(),
        "REPORT_DAY": os.environ.get("REPORT_DAY", "sun").strip().lower(),
        "REPORT_TIME": os.environ.get("REPORT_TIME", "18:00").strip(),
        "PUBLIC_URL": os.environ.get("PUBLIC_URL", "http://localhost:5000").strip().rstrip("/"),
        "REQUIRE_LOGIN": _default_on("REQUIRE_LOGIN"),
        "SESSION_HOURS": os.environ.get("SESSION_HOURS", 8),
        "REMEMBER_DAYS": os.environ.get("REMEMBER_DAYS", 30),
        "LOGIN_MAX_ATTEMPTS": os.environ.get("LOGIN_MAX_ATTEMPTS", 5),
        "LOGIN_LOCK_MINUTES": os.environ.get("LOGIN_LOCK_MINUTES", 15),
    }
    overrides = dict(overrides or {})
    # Shortcut for tests and scripts: a plain SQLite file path.
    if "DATABASE" in overrides:
        settings["DATABASE_URL"] = f"sqlite:///{Path(overrides.pop('DATABASE')).as_posix()}"
    settings.update(overrides)

    settings["MEAL_SCHEDULE"] = parse_meal_schedule(settings["MEAL_SCHEDULE"])
    settings["CAMERA_SOURCES"] = parse_camera_sources(settings["CAMERA_SOURCES"])
    if not settings.get("SECRET_KEY"):
        settings["SECRET_KEY"] = _secret_key(bool(settings.get("TESTING")))
    for key, low, high in (("PHOTOS_PER_CAPTURE", 1, 10), ("CAPTURE_TEST_SECONDS", 1, 3600),
                           ("SESSION_HOURS", 1, 24 * 14), ("REMEMBER_DAYS", 1, 365),
                           ("LOGIN_MAX_ATTEMPTS", 1, 100), ("LOGIN_LOCK_MINUTES", 1, 1440)):
        try:
            settings[key] = int(settings[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a whole number.") from None
        if not low <= settings[key] <= high:
            raise ValueError(f"{key} must be between {low} and {high}.")
    try:
        settings["PHOTO_GAP_SECONDS"] = float(settings["PHOTO_GAP_SECONDS"])
    except (TypeError, ValueError):
        raise ValueError("PHOTO_GAP_SECONDS must be a number.") from None
    for key, low, high in (("SMTP_PORT", 1, 65535), ("CAMERA_CHECK_MINUTES", 1, 60), ("CAMERA_OFFLINE_AFTER", 1, 10)):
        try:
            settings[key] = int(settings[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a whole number.") from None
        if not low <= settings[key] <= high:
            raise ValueError(f"{key} must be between {low} and {high}.")
    if settings["SMTP_SECURITY"] not in {"starttls", "ssl", "none"}:
        raise ValueError("SMTP_SECURITY must be starttls, ssl or none.")
    if settings["REPORT_DAY"][:3] not in REPORT_DAYS:
        raise ValueError("REPORT_DAY must be a day of the week, such as sun.")
    settings["REPORT_DAY"] = settings["REPORT_DAY"][:3]
    if not _TIME.fullmatch(settings["REPORT_TIME"]):
        raise ValueError("REPORT_TIME must be HH:MM, such as 18:00.")
    settings["SMTP_USER"] = settings["SMTP_USER"] or settings["ADMIN_EMAIL"]
    settings["CAPTURE_DIR"] = Path(settings["CAPTURE_DIR"])
    return settings
