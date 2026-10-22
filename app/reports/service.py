"""Make the report and send it: by schedule, by hand, or as a test. Never raises; says what happened."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from zoneinfo import ZoneInfo

from sqlalchemy.exc import SQLAlchemyError

from app.config import REPORT_DAYS
from app.database.queries import utc_text
from app.reports import store
from app.reports.builder import build_report, plain_text, subject
from app.reports.mailer import MailError, mail_ready, missing_settings, send_each
from app.web import templates


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Outcome:
    ok: bool
    message: str


def zone(settings) -> ZoneInfo:
    return ZoneInfo(settings["TIMEZONE"])


def latest_slot(settings, now: datetime) -> datetime:
    """The most recent time the weekly report was due, at or before ``now``."""
    now = now.astimezone(zone(settings))
    hour, minute = (int(part) for part in settings["REPORT_TIME"].split(":"))
    weekday = REPORT_DAYS.index(settings["REPORT_DAY"])
    slot = now.replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(days=(now.weekday() - weekday) % 7)
    return slot - timedelta(days=7) if slot > now else slot


def render_report(db, app, end: datetime) -> tuple[str, str, str]:
    """(subject, plain text, HTML) of the report for the week ending at ``end``."""
    report = build_report(db, app.state.settings, getattr(app.state, "forecast_model", None), end)
    html = templates.env.get_template("email/weekly.html").render(report=report)
    return subject(report), plain_text(report), html


def send_report(app, *, kind: str, end: datetime | None = None) -> Outcome:
    """Send the weekly report (kind "weekly" for the schedule, "manual" for the button) to everyone on the list."""
    settings = app.state.settings
    end = end or datetime.now(timezone.utc)
    period_end = utc_text(end)
    try:
        with app.state.session_factory() as db:
            recipients = [row.email for row in store.list_recipients(db)]
            if not mail_ready(settings):
                return Outcome(False, "Email is not set up: set " + " and ".join(missing_settings(settings)) + " first.")
            if not recipients:
                return Outcome(False, "Add at least one email address first.")
            try:
                title, text, html = render_report(db, app, end)
                reached = send_each(settings, recipients, title, text, html)
            except MailError as error:
                store.log_attempt(db, kind=kind, period_end=period_end, ok=False, error=str(error))
                return Outcome(False, str(error))
            store.log_attempt(db, kind=kind, period_end=period_end, ok=True, sent_to=len(reached))
            return Outcome(True, f"The report was sent to {len(reached)} address{'' if len(reached) == 1 else 'es'}.")
    except SQLAlchemyError:
        logger.exception("The weekly report could not be sent: database error.")
        return Outcome(False, "The database is unavailable. Try again.")
    except Exception:
        logger.exception("The weekly report could not be made.")
        return Outcome(False, "The report could not be made. Check the server log.")


def send_test(app) -> Outcome:
    """A short message that shows email works, to everyone on the list."""
    settings = app.state.settings
    try:
        with app.state.session_factory() as db:
            recipients = [row.email for row in store.list_recipients(db)]
            if not mail_ready(settings):
                return Outcome(False, "Email is not set up: set " + " and ".join(missing_settings(settings)) + " first.")
            if not recipients:
                return Outcome(False, "Add at least one email address first.")
            try:
                reached = send_each(settings, recipients, "Wastewise test email",
                                    "This is a test from Wastewise. The weekly report will arrive at this address "
                                    f"every {settings['REPORT_DAY'].capitalize()} at {settings['REPORT_TIME']}.")
            except MailError as error:
                store.log_attempt(db, kind="test", period_end=utc_text(datetime.now(timezone.utc)), ok=False, error=str(error))
                return Outcome(False, str(error))
            store.log_attempt(db, kind="test", period_end=utc_text(datetime.now(timezone.utc)), ok=True, sent_to=len(reached))
            return Outcome(True, f"A test email was sent to {len(reached)} address{'' if len(reached) == 1 else 'es'}.")
    except SQLAlchemyError:
        logger.exception("The test email could not be sent: database error.")
        return Outcome(False, "The database is unavailable. Try again.")


def send_if_due(app, now: datetime | None = None) -> Outcome | None:
    """Send the report for the latest due time unless it was already sent, is switched off, or is from before
    the report was turned on. Used by the weekly job and, after a restart, to send one that was missed."""
    settings = app.state.settings
    now = now or datetime.now(timezone.utc)
    slot = latest_slot(settings, now)
    try:
        with app.state.session_factory() as db:
            if not store.is_enabled(db) or not store.list_recipients(db) or not mail_ready(settings):
                return None
            if utc_text(slot) < store.enabled_since(db)[:19] + "Z" or store.already_sent(db, utc_text(slot)):
                return None
    except SQLAlchemyError:
        logger.exception("Could not check whether the weekly report is due.")
        return None
    return send_report(app, kind="weekly", end=slot)
