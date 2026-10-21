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
"""

import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = PROJECT_ROOT / "instance" / "food_waste.sqlite3"
DEFAULT_CAPTURE_DIR = PROJECT_ROOT / "instance" / "captures"

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


def load_settings(overrides=None):
    """Return the settings dict. Tests pass overrides, such as a temporary DATABASE.

    Keys other code reads:
        DATABASE_URL, TESTING, ML_MODEL_SKIP, ML_MODEL_PATH, ML_MODEL,
        FOOD_CLASSIFIER_MODEL, FOOD_CLASSIFIER_MODEL_PATH,
        FOOD_COUNTER, FOOD_COUNTER_MODEL_NAME,
        TIMEZONE, MEAL_SCHEDULE, CAMERA_SOURCES, PHOTOS_PER_CAPTURE, PHOTO_GAP_SECONDS,
        CAPTURE_TEST_MODE, CAPTURE_TEST_SECONDS, CAPTURE_DIR, FRAME_GRABBER (tests), CAPTURE_SCHEDULER_SKIP
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
    }
    overrides = dict(overrides or {})
    # Shortcut for tests and scripts: a plain SQLite file path.
    if "DATABASE" in overrides:
        settings["DATABASE_URL"] = f"sqlite:///{Path(overrides.pop('DATABASE')).as_posix()}"
    settings.update(overrides)

    settings["MEAL_SCHEDULE"] = parse_meal_schedule(settings["MEAL_SCHEDULE"])
    settings["CAMERA_SOURCES"] = parse_camera_sources(settings["CAMERA_SOURCES"])
    for key, low, high in (("PHOTOS_PER_CAPTURE", 1, 10), ("CAPTURE_TEST_SECONDS", 1, 3600)):
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
    settings["CAPTURE_DIR"] = Path(settings["CAPTURE_DIR"])
    return settings
