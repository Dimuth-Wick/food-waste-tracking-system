"""Add waste record: a side panel over the waste overview.

/records/new opens the overview with the panel showing, so kitchen staff can
bookmark it. Saving returns to the overview with the new record highlighted.
"""

from datetime import datetime
from math import isfinite
import logging
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.connection import get_session
from app.database.queries import create_waste_record, get_user_by_username
from app.waste_records.common import DEMO_TIMEZONE, DEMO_USERNAME, load_lookups, parse_id
from app.waste_records.overview import render_overview, view_state
from app.web import url_path


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


def render_panel(request: Request, db: Session, *, lookups, actor_name, values=None,
                 errors=None, message=None, status_code=200, record_id=None):
    """The overview with the add panel (or, given record_id, the edit panel) open."""
    panel = {
        "editing": record_id is not None, "record_id": record_id,
        "areas": lookups.get("areas", []), "categories": lookups.get("categories", []),
        "reasons": lookups.get("reasons", []), "actor_name": actor_name,
        "values": values or {}, "errors": errors or {}, "message": message,
        "close_url": url_path(request.app, "dashboard", **view_state(request)),
    }
    return render_overview(request, db, panel=panel, status_code=status_code)


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

    Returns ((lookups, actor), None), or (None, the overview with an error in the panel).
    """
    try:
        lookups = load_lookups(db, active_only=True)
        actor = get_user_by_username(db, DEMO_USERNAME)
    except SQLAlchemyError:
        logger.exception("Could not load the waste entry form")
        return None, render_panel(request, db, lookups={}, actor_name=None, values=values,
                                  status_code=503,
                                  message="The database is unavailable. Initialize it and try again.")
    if actor is None or not actor.active or actor.role != "entry" or not all(lookups.values()):
        return None, render_panel(
            request, db, lookups=lookups, actor_name=actor.name if actor else None,
            values=values, status_code=503,
            message="Demo entry data is missing. Initialize and seed the local database first.",
        )
    return (lookups, actor), None


@router.get("/records/new", name="new_record")
def new_record_panel(request: Request, db: Session = Depends(get_session)):
    loaded, error_page = _load(request, db, {})
    if error_page:
        return error_page
    lookups, actor = loaded
    return render_panel(request, db, lookups=lookups, actor_name=actor.name)


@router.post("/records/new", name="save_new_record")
def save_new_record(request: Request, form: RecordForm = Depends(),
                    db: Session = Depends(get_session)):
    loaded, error_page = _load(request, db, form.values)
    if error_page:
        return error_page
    lookups, actor = loaded

    errors, event_at, selected_ids, quantity_kg = parse_form(form.values, lookups)
    if errors:
        return render_panel(request, db, lookups=lookups, actor_name=actor.name,
                            values=form.values, errors=errors, status_code=400)
    try:
        record = create_waste_record(db, event_at=event_at, quantity_kg=quantity_kg,
                                     user_id=actor.id, **selected_ids)
    except (SQLAlchemyError, ValueError):
        logger.exception("Could not save waste record")
        return render_panel(request, db, lookups=lookups, actor_name=actor.name,
                            values=form.values, status_code=500,
                            message="The record could not be saved. Check the details and try again.")
    state = {key: value for key, value in view_state(request).items() if key != "show"}
    return RedirectResponse(url_path(request.app, "dashboard", **state, created=record.id), status_code=303)
