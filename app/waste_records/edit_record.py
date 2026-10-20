"""Edit waste record page. In the demo, staff may edit only their own records."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.connection import get_session
from app.database.queries import get_user_by_username, get_waste_record, list_lookup_items, update_waste_record
from app.waste_records.add_record import RecordForm, parse_form, render_form
from app.waste_records.common import DEMO_USERNAME, LOOKUPS, can_edit, local_time
from app.web import url_path


logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)


def _record_values(record):
    return {
        "event_at": local_time(record.event_at).strftime("%Y-%m-%dT%H:%M"),
        "area_id": str(record.area_id),
        "category_id": str(record.category_id),
        "reason_id": str(record.reason_id),
        "quantity_kg": f"{record.quantity_kg:g}",
    }


def _load(db: Session, record_id: int):
    """Return (actor, record, lookups) or raise the right HTTP error."""
    try:
        actor = get_user_by_username(db, DEMO_USERNAME)
        record = get_waste_record(db, record_id)
        if record is None:
            raise HTTPException(404)
        if actor is None or not actor.active:
            raise HTTPException(503, "Demo entry user is unavailable.")
        if not can_edit(actor, record.user_id):
            raise HTTPException(403)
        # Keep a retired area, category or reason selectable if this record uses it.
        selected = {"areas": record.area_id, "categories": record.category_id,
                    "reasons": record.reason_id}
        lookups = {
            table: [item for item in list_lookup_items(db, table)
                    if item.active or item.id == selected[table]]
            for table in LOOKUPS
        }
    except SQLAlchemyError:
        logger.exception("Could not load waste record for editing")
        raise HTTPException(503, "The database is unavailable. Try again later.") from None
    return actor, record, lookups


def _context(actor, lookups, values, record_id):
    return {**lookups, "actor_name": actor.name, "values": values, "editing": True,
            "record_id": record_id}


@router.get("/records/{record_id}/edit", name="edit_record")
def edit_record_page(request: Request, record_id: int, updated: str = "",
                     db: Session = Depends(get_session)):
    actor, record, lookups = _load(db, record_id)
    return render_form(request, **_context(actor, lookups, _record_values(record), record_id),
                       saved_record=record if updated == "1" else None)


@router.post("/records/{record_id}/edit", name="save_edited_record")
def save_edited_record(request: Request, record_id: int, form: RecordForm = Depends(),
                       db: Session = Depends(get_session)):
    actor, _, lookups = _load(db, record_id)
    context = _context(actor, lookups, form.values, record_id)

    errors, event_at, selected_ids, quantity_kg = parse_form(form.values, lookups)
    if errors:
        return render_form(request, **context, errors=errors, status_code=400)
    try:
        updated = update_waste_record(db, record_id, event_at=event_at,
                                      quantity_kg=quantity_kg, **selected_ids)
    except (SQLAlchemyError, ValueError):
        logger.exception("Could not update waste record")
        return render_form(request, **context, status_code=500,
                           message="The record could not be updated. Check the details and try again.")
    if updated is None:
        raise HTTPException(404)
    return RedirectResponse(url_path(request.app, "edit_record", record_id=record_id, updated=1),
                            status_code=303)
