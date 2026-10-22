"""Send the report by itself every week (APScheduler). One scheduler per machine, guarded by a file lock."""

from datetime import datetime, timedelta
import logging
from pathlib import Path

from app.camera.schedule import SingleInstanceLock
from app.reports.mailer import mail_ready
from app.reports.service import send_if_due, zone


logger = logging.getLogger(__name__)
MISFIRE_GRACE_SECONDS = 3600
CATCH_UP_DELAY_SECONDS = 20


def run_weekly(app) -> None:
    """The job APScheduler runs. It never raises, so the scheduler keeps going."""
    try:
        outcome = send_if_due(app)
        if outcome is not None:
            logger.info("Weekly report: %s", outcome.message)
    except Exception:
        logger.exception("The weekly report job failed.")


def build_scheduler(app):
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger

    settings = app.state.settings
    tz = zone(settings)
    hour, minute = (int(part) for part in settings["REPORT_TIME"].split(":"))
    scheduler = BackgroundScheduler(timezone=tz, job_defaults={"misfire_grace_time": MISFIRE_GRACE_SECONDS,
                                                                "coalesce": True, "max_instances": 1})
    scheduler.add_job(run_weekly, CronTrigger(day_of_week=settings["REPORT_DAY"], hour=hour, minute=minute, timezone=tz),
                      args=[app], id="weekly-report", name="Weekly email report", replace_existing=True)
    # After a restart, send the report that was due while the app was off (once; send_if_due checks the log).
    scheduler.add_job(run_weekly, DateTrigger(run_date=datetime.now(tz) + timedelta(seconds=CATCH_UP_DELAY_SECONDS), timezone=tz),
                      args=[app], id="weekly-report-catch-up", name="Weekly report catch-up", replace_existing=True)
    return scheduler


def start_report_scheduler(app):
    """Start the weekly job, or return None (and say why) if it should not run."""
    settings = app.state.settings
    if settings.get("TESTING") or settings.get("REPORT_SCHEDULER_SKIP"):
        return None
    if not mail_ready(settings):
        logger.info("The weekly report is off: set ADMIN_EMAIL and SMTP_HOST to send it.")
        return None
    lock = SingleInstanceLock(Path(settings["CAPTURE_DIR"]) / ".report.lock")
    if not lock.acquire():
        logger.warning("The weekly report is already scheduled by another process.")
        return None
    try:
        scheduler = build_scheduler(app)
        scheduler.start()
    except Exception:
        lock.release()
        logger.exception("The report scheduler could not start.")
        return None
    app.state.report_lock = lock
    app.state.report_scheduler = scheduler
    logger.info("Weekly report scheduled: next at %s", scheduler.get_job("weekly-report").next_run_time)
    return scheduler


def stop_report_scheduler(app) -> None:
    scheduler = getattr(app.state, "report_scheduler", None)
    if scheduler is not None:
        scheduler.shutdown(wait=False)
        app.state.report_scheduler = None
    lock = getattr(app.state, "report_lock", None)
    if lock is not None:
        lock.release()
        app.state.report_lock = None
