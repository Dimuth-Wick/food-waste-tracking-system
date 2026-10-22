"""The Weekly report page: who gets the email, a preview, and buttons to test and send it now."""

from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.connection import get_session
from app.reports import store
from app.reports.mailer import mail_ready, missing_settings
from app.reports.service import latest_slot, render_report, send_report, send_test, zone
from app.waste_records.common import parse_id
from app.web import render, url_path


logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)
DAY_NAMES = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday",
             "sat": "Saturday", "sun": "Sunday"}


def _page(request: Request, db: Session, *, status_code=200, error="", entered="", notice=None, field_error=False):
    settings = request.app.state.settings
    last = store.last_attempt(db)
    return render(
        request, "report_settings.html", status_code, active_page="reports",
        recipients=store.list_recipients(db), enabled=store.is_enabled(db), ready=mail_ready(settings),
        missing=missing_settings(settings), sender=settings["ADMIN_EMAIL"], day=DAY_NAMES[settings["REPORT_DAY"]],
        time=settings["REPORT_TIME"], zone_name=settings["TIMEZONE"], last=last, error=error, entered=entered,
        notice=notice, field_error=field_error, max_recipients=store.MAX_RECIPIENTS)


def _unavailable(request: Request):
    return render(request, "error.html", 503, status=503, title="Service unavailable",
                  message="The database is unavailable. Initialize it and try again.")


def _back(request: Request, notice: str = ""):
    return RedirectResponse(url_path(request.app, "report_settings") + (f"?notice={notice}" if notice else ""), status_code=303)


NOTICES = {"added": "Address added.", "removed": "Address removed.", "on": "The weekly report is on.",
           "off": "The weekly report is off."}


@router.get("/reports", name="report_settings")
def report_settings(request: Request, notice: str = "", result: str = "", db: Session = Depends(get_session)):
    try:
        return _page(request, db, notice=NOTICES.get(notice) or None)
    except SQLAlchemyError:
        logger.exception("Could not load the report settings")
        return _unavailable(request)


@router.post("/reports/recipients", name="add_report_recipient")
def add_recipient(request: Request, email: str = Form(""), db: Session = Depends(get_session)):
    try:
        problem = store.add_recipient(db, email)
        if problem:
            return _page(request, db, status_code=400, error=problem, entered=email, field_error=True)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not add a report recipient")
        return _unavailable(request)
    return _back(request, "added")


@router.post("/reports/recipients/{recipient_id}/remove", name="remove_report_recipient")
def remove_recipient(request: Request, recipient_id: str, db: Session = Depends(get_session)):
    number = parse_id(recipient_id)
    try:
        if number is not None:
            store.remove_recipient(db, number)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not remove a report recipient")
        return _unavailable(request)
    return _back(request, "removed")


@router.post("/reports/switch", name="switch_report")
def switch(request: Request, on: str = Form(""), db: Session = Depends(get_session)):
    try:
        store.set_enabled(db, on == "1")
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not change the weekly report switch")
        return _unavailable(request)
    return _back(request, "on" if on == "1" else "off")


def _done(request: Request, db: Session, outcome):
    return _page(request, db, status_code=200 if outcome.ok else 502, notice=outcome.message if outcome.ok else None,
                 error="" if outcome.ok else outcome.message)


@router.post("/reports/test", name="send_test_report")
def test_email(request: Request, db: Session = Depends(get_session)):
    outcome = send_test(request.app)
    try:
        return _done(request, db, outcome)
    except SQLAlchemyError:
        return _unavailable(request)


@router.post("/reports/send-now", name="send_report_now")
def send_now(request: Request, db: Session = Depends(get_session)):
    outcome = send_report(request.app, kind="manual")
    try:
        return _done(request, db, outcome)
    except SQLAlchemyError:
        return _unavailable(request)


@router.get("/reports/preview", name="report_preview")
def preview(request: Request, db: Session = Depends(get_session)):
    """The report as it would be emailed right now."""
    try:
        _, _, html = render_report(db, request.app, datetime.now(timezone.utc))
    except SQLAlchemyError:
        logger.exception("Could not build the report preview")
        return _unavailable(request)
    return HTMLResponse(html)
