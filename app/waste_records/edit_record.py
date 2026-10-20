"""Edit permitted waste records in the local demo."""

from datetime import datetime
import sqlite3

from flask import abort, current_app, redirect, request, url_for

from app.database.connection import get_db
from app.waste_records.add_record import DEMO_TIMEZONE, FIELD_NAMES, _parse_form, _render_form
from app.database.queries import get_user_by_username, get_waste_record, list_lookup_items, update_waste_record


def can_edit(actor, record_user_id: int) -> bool:
    return bool(
        actor and actor.active
        and (actor.role in {"manager", "admin"} or actor.role == "entry" and actor.id == record_user_id)
    )


def _record_values(record):
    local_time = datetime.fromisoformat(record.event_at.replace("Z", "+00:00")).astimezone(
        DEMO_TIMEZONE
    )
    return {
        "event_at": local_time.strftime("%Y-%m-%dT%H:%M"),
        "area_id": str(record.area_id),
        "category_id": str(record.category_id),
        "reason_id": str(record.reason_id),
        "quantity_kg": f"{record.quantity_kg:g}",
    }


def edit_record(record_id):
    try:
        connection = get_db()
        actor = get_user_by_username(connection, "demo_entry")
        record = get_waste_record(connection, record_id)
        if record is None:
            abort(404)
        if actor is None or not actor.active:
            abort(503, description="Demo entry user is unavailable.")
        if not can_edit(actor, record.user_id):
            abort(403)

        lookups = {}
        for table, selected_id in (
            ("areas", record.area_id),
            ("categories", record.category_id),
            ("reasons", record.reason_id),
        ):
            lookups[table] = [
                item for item in list_lookup_items(connection, table)
                if item.active or item.id == selected_id
            ]
    except sqlite3.Error:
        current_app.logger.exception("Could not load waste record for editing")
        abort(503, description="The database is unavailable. Try again later.")

    values = (
        {name: request.form.get(name, "").strip() for name in FIELD_NAMES}
        if request.method == "POST" else _record_values(record)
    )
    form_context = {
        "areas": lookups["areas"],
        "categories": lookups["categories"],
        "reasons": lookups["reasons"],
        "actor_name": actor.name,
        "values": values,
        "editing": True,
        "record_id": record_id,
    }
    if request.method == "GET":
        return _render_form(
            **form_context,
            saved_record=record if request.args.get("updated") == "1" else None,
        )

    errors, event_at, selected_ids, quantity_kg = _parse_form(values, lookups)
    if errors:
        return _render_form(**form_context, errors=errors, status=400)

    try:
        updated = update_waste_record(
            connection, record_id,
            event_at=event_at,
            area_id=selected_ids["area_id"],
            category_id=selected_ids["category_id"],
            reason_id=selected_ids["reason_id"],
            quantity_kg=quantity_kg,
        )
    except (sqlite3.Error, ValueError):
        current_app.logger.exception("Could not update waste record")
        return _render_form(
            **form_context,
            message="The record could not be updated. Check the details and try again.",
            status=500,
        )
    if updated is None:
        abort(404)
    return redirect(url_for("edit_record", record_id=record_id, updated=1), code=303)
