"""Add waste record page: the entry form and saving a new record."""

from datetime import datetime
from math import isfinite
import logging
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.connection import get_session
from app.database.queries import create_waste_record, get_user_by_username, get_waste_record
from app.waste_records.common import DEMO_TIMEZONE, DEMO_USERNAME, load_lookups, parse_id
from app.web import render, url_path


logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)
FIELD_NAMES = ("event_at", "area_id", "category_id", "reason_id", "quantity_kg")


class RecordForm:
    """The five form fields, as submitted text. Validation happens in parse_form."""

    def __init__(self, event_at: str = Form(""), area_id: str = Form(""),
                 category_id: str = Form(""), reason_id: str = Form(""),
                 quantity_kg: str = Form("")):
        self.values = {name: value.strip() for name, value in zip(
            FIELD_NAMES, (event_at, area_id, category_id, reason_id, quantity_kg))}


def render_form(request: Request, *, areas, categories, reasons, actor_name, values=None,
                errors=None, message=None, saved_record=None, status_code=200,
                editing=False, record_id=None):
    return render(
        request, "new_record.html", status_code,
        active_page="records" if editing else "new_record",
        areas=areas, categories=categories, reasons=reasons, actor_name=actor_name,
        values=values or {}, errors=errors or {}, message=message,
        saved_record=saved_record, editing=editing, record_id=record_id,
    )


def parse_form(values, lookups):
    """Check the submitted fields. Returns (errors, event_at, selected ids, quantity)."""
    errors = {}

    raw_time = values["event_at"]
    event_at = None
    if not raw_time:
        errors["event_at"] = "Enter the date and time of the waste event."
    else:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", raw_time):
                raise ValueError("Expected date and time")
            moment = datetime.fromisoformat(raw_time)
            if moment.tzinfo is not None:
                raise ValueError("Expected local time")
            event_at = moment.replace(tzinfo=DEMO_TIMEZONE)
        except ValueError:
            errors["event_at"] = "Enter a valid local date and time."

    selected_ids = {}
    for field, label, items in (("area_id", "source area", lookups["areas"]),
                                ("category_id", "food category", lookups["categories"]),
                                ("reason_id", "reason for waste", lookups["reasons"])):
        raw_id = values[field]
        if not raw_id:
            errors[field] = f"Select a {label}."
        elif (parsed := parse_id(raw_id)) not in {item.id for item in items}:
            errors[field] = f"Select a valid {label}."
        else:
            selected_ids[field] = parsed

    raw_quantity = values["quantity_kg"]
    quantity_kg = None
    if not raw_quantity:
        errors["quantity_kg"] = "Enter the quantity in kilograms."
    else:
        try:
            quantity_kg = float(raw_quantity)
            if not isfinite(quantity_kg) or quantity_kg <= 0:
                raise ValueError("Nonpositive or nonfinite quantity")
        except (ValueError, OverflowError):
            errors["quantity_kg"] = "Enter a number greater than zero in kilograms."
            quantity_kg = None

    return errors, event_at, selected_ids, quantity_kg


def _load(request: Request, db: Session, values):
    """Load the form's choices and demo user.

    Returns ((lookups, actor, form context), None), or (None, error page).
    """
    try:
        lookups = load_lookups(db, active_only=True)
        actor = get_user_by_username(db, DEMO_USERNAME)
    except SQLAlchemyError:
        logger.exception("Could not load the waste entry form")
        return None, render_form(
            request, areas=[], categories=[], reasons=[], actor_name=None,
            message="The database is unavailable. Initialize it and try again.", status_code=503,
        )
    context = {**lookups, "actor_name": actor.name if actor else None, "values": values}
    if actor is None or not actor.active or actor.role != "entry" or not all(lookups.values()):
        return None, render_form(
            request, **context, status_code=503,
            message="Demo entry data is missing. Initialize and seed the local database first.",
        )
    return (lookups, actor, context), None


@router.get("/records/new", name="new_record")
def new_record_page(request: Request, created: str = "", db: Session = Depends(get_session)):
    loaded, error_page = _load(request, db, {name: "" for name in FIELD_NAMES})
    if error_page:
        return error_page
    _, _, context = loaded
    saved_record = None
    if (created_id := parse_id(created)) is not None:
        try:
            saved_record = get_waste_record(db, created_id)
        except SQLAlchemyError:
            logger.exception("Could not read saved waste record")
    return render_form(request, **context, saved_record=saved_record)


@router.post("/records/new", name="save_new_record")
def save_new_record(request: Request, form: RecordForm = Depends(),
                    db: Session = Depends(get_session)):
    loaded, error_page = _load(request, db, form.values)
    if error_page:
        return error_page
    lookups, actor, context = loaded

    errors, event_at, selected_ids, quantity_kg = parse_form(form.values, lookups)
    if errors:
        return render_form(request, **context, errors=errors, status_code=400)
    try:
        record = create_waste_record(db, event_at=event_at, quantity_kg=quantity_kg,
                                     user_id=actor.id, **selected_ids)
    except (SQLAlchemyError, ValueError):
        logger.exception("Could not save waste record")
        return render_form(request, **context, status_code=500,
                           message="The record could not be saved. Check the details and try again.")
    return RedirectResponse(url_path(request.app, "new_record", created=record.id), status_code=303)
