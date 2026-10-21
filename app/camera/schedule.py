"""Run captures by themselves at the start and end of each meal (APScheduler).

Exactly one scheduler runs: it starts in the FastAPI lifespan, never in tests, and a file lock keeps a
second server process (for example uvicorn with several workers) from starting another.
"""

from datetime import datetime
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from app.camera.capture import KINDS, CameraUnavailable, CaptureBusy, CaptureService


logger = logging.getLogger(__name__)
MISFIRE_GRACE_SECONDS = 300  # a capture that is up to 5 minutes late still happens; later ones are skipped


def run_event(service: CaptureService, meal: str, kind: str) -> None:
    """The job APScheduler runs. It never raises, so the scheduler is never stopped by a bad capture."""
    try:
        service.capture_event(meal, kind)
    except CaptureBusy:
        logger.warning("Skipped the %s %s capture: another capture was still running.", meal, kind)
    except CameraUnavailable as error:
        logger.error("Could not capture %s %s: %s", meal, kind, error)
    except Exception:
        logger.exception("The %s %s capture failed.", meal, kind)


def meal_at(schedule: dict, moment: datetime) -> str:
    """The meal that started most recently before this time of day (the last meal before the first start)."""
    clock = moment.strftime("%H:%M")
    ordered = sorted(schedule, key=lambda meal: schedule[meal]["start"])
    started = [meal for meal in ordered if schedule[meal]["start"] <= clock]
    return started[-1] if started else ordered[-1]


class TestModeTicker:
    """In test mode every tick captures for the meal the clock says it is, alternating start and end photos."""

    __test__ = False  # not a pytest test class

    def __init__(self, service: CaptureService):
        self.service = service
        self.next_kind = 0

    def __call__(self) -> None:
        kind = KINDS[self.next_kind % 2]
        self.next_kind += 1
        run_event(self.service, meal_at(self.service.schedule, self.service.now()), kind)


def build_scheduler(settings, service: CaptureService):
    """A scheduler with every job added but not started."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    zone = ZoneInfo(settings["TIMEZONE"])
    scheduler = BackgroundScheduler(
        timezone=zone,
        job_defaults={"misfire_grace_time": MISFIRE_GRACE_SECONDS, "coalesce": True, "max_instances": 1},
    )
    if settings["CAPTURE_TEST_MODE"]:
        scheduler.add_job(TestModeTicker(service), IntervalTrigger(seconds=settings["CAPTURE_TEST_SECONDS"], timezone=zone),
                          id="test-mode", name="Test mode capture", replace_existing=True)
        return scheduler
    for meal, times in settings["MEAL_SCHEDULE"].items():
        for kind in KINDS:
            hour, minute = (int(part) for part in times[kind].split(":"))
            scheduler.add_job(run_event, CronTrigger(hour=hour, minute=minute, timezone=zone), args=[service, meal, kind],
                              id=f"{meal}-{kind}", name=f"{meal.capitalize()} {kind} photos", replace_existing=True)
    return scheduler


class SingleInstanceLock:
    """An operating-system file lock: held while this process runs, freed automatically if it dies."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._file = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+")
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._file = handle
        return True

    def release(self) -> None:
        if self._file is None:
            return
        try:
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._file.close()
            self._file = None


def start_scheduler(app):
    """Start the one scheduler for this app, or return None (and say why) if it should not run."""
    settings = app.state.settings
    service = app.state.capture_service
    if settings.get("TESTING") or settings.get("CAPTURE_SCHEDULER_SKIP"):
        return None
    if not service.cameras:
        logger.info("Camera capture is off: no cameras are set up (CAMERA_SOURCES).")
        return None
    lock = SingleInstanceLock(Path(settings["CAPTURE_DIR"]) / ".scheduler.lock")
    if not lock.acquire():
        logger.warning("Camera capture is already running in another process; not starting a second scheduler.")
        return None
    try:
        scheduler = build_scheduler(settings, service)
        scheduler.start()
    except Exception:
        lock.release()
        logger.exception("The capture scheduler could not start.")
        return None
    app.state.capture_lock = lock
    app.state.capture_scheduler = scheduler
    for job in scheduler.get_jobs():
        logger.info("Scheduled %s: next at %s", job.name, job.next_run_time)
    return scheduler


def stop_scheduler(app) -> None:
    scheduler = getattr(app.state, "capture_scheduler", None)
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        app.state.capture_scheduler = None
    lock = getattr(app.state, "capture_lock", None)
    if lock is not None:
        lock.release()
        app.state.capture_lock = None
