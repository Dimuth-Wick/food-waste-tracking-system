"""Create a food waste record through the local demo form."""

from datetime import datetime, timedelta, timezone
from math import isfinite
import re
import sqlite3

from flask import current_app, redirect, render_template, request, url_for

from app.database.connection import get_db
from app.database.queries import (
    create_waste_record,
    get_user_by_username,
    get_waste_record,
    list_lookup_items,
)


DEMO_TIMEZONE = timezone(timedelta(hours=5, minutes=30))
FIELD_NAMES = ("event_at", "area_id", "category_id", "reason_id", "quantity_kg")


def _parse_id(raw: str) -> int | None:
    """Accept only SQLite-sized positive decimal IDs from forms and query strings."""
    if not re.fullmatch(r"[0-9]{1,19}", raw):
        return None
    value = int(raw)
    return value if 0 < value <= 2**63 - 1 else None


def _render_form(*, areas, categories, reasons, actor_name, values=None, errors=None,
                 message=None, saved_record=None, status=200, editing=False, record_id=None):
    return render_template(
        "new_record.html",
        active_page="records" if editing else "new_record",
        areas=areas,
        categories=categories,
        reasons=reasons,
        actor_name=actor_name,
        values=values or {},
        errors=errors or {},
        message=message,
        saved_record=saved_record,
        editing=editing,
        record_id=record_id,
    ), status


def _parse_form(values, lookups):
    errors = {}

    raw_time = values["event_at"]
    if not raw_time:
        errors["event_at"] = "Enter the date and time of the waste event."
        event_at = None
    else:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", raw_time):
                raise ValueError("Expected date and time")
            local_time = datetime.fromisoformat(raw_time)
            if local_time.tzinfo is not None:
                raise ValueError("Expected local time")
            event_at = local_time.replace(tzinfo=DEMO_TIMEZONE)
        except ValueError:
            errors["event_at"] = "Enter a valid local date and time."
            event_at = None

    selected_ids = {}
    for field, label, items in (
        ("area_id", "source area", lookups["areas"]),
        ("category_id", "food category", lookups["categories"]),
        ("reason_id", "reason for waste", lookups["reasons"]),
    ):
        raw_id = values[field]
        if not raw_id:
            errors[field] = f"Select a {label}."
        elif (parsed_id := _parse_id(raw_id)) not in {item.id for item in items}:
            errors[field] = f"Select a valid {label}."
        else:
            selected_ids[field] = parsed_id

    raw_quantity = values["quantity_kg"]
    if not raw_quantity:
        errors["quantity_kg"] = "Enter the quantity in kilograms."
        quantity_kg = None
    else:
        try:
            quantity_kg = float(raw_quantity)
            if not isfinite(quantity_kg) or quantity_kg <= 0:
                raise ValueError("Nonpositive or nonfinite quantity")
        except (ValueError, OverflowError):
            errors["quantity_kg"] = "Enter a number greater than zero in kilograms."
            quantity_kg = None

    return errors, event_at, selected_ids, quantity_kg


def new_record():
    values = {name: request.form.get(name, "").strip() for name in FIELD_NAMES}
    try:
        connection = get_db()
        lookups = {
            table: [item for item in list_lookup_items(connection, table) if item.active]
            for table in ("areas", "categories", "reasons")
        }
        actor = get_user_by_username(connection, "demo_entry")
    except sqlite3.Error:
        current_app.logger.exception("Could not load the waste entry form")
        return _render_form(
            areas=[], categories=[], reasons=[], actor_name=None,
            message="The database is unavailable. Initialize it and try again.", status=503,
        )

    form_context = {
        "areas": lookups["areas"],
        "categories": lookups["categories"],
        "reasons": lookups["reasons"],
        "actor_name": actor.name if actor else None,
        "values": values,
    }
    if actor is None or not actor.active or actor.role != "entry" or any(
        not items for items in lookups.values()
    ):
        return _render_form(
            **form_context,
            message="Demo entry data is missing. Initialize and seed the local database first.",
            status=503,
        )

    if request.method == "GET":
        raw_created = request.args.get("created", "")
        saved_record = None
        created_id = _parse_id(raw_created)
        if created_id is not None:
            try:
                saved_record = get_waste_record(connection, created_id)
            except sqlite3.Error:
                current_app.logger.exception("Could not read saved waste record")
        return _render_form(**form_context, saved_record=saved_record)

    errors, event_at, selected_ids, quantity_kg = _parse_form(values, lookups)
    if errors:
        return _render_form(**form_context, errors=errors, status=400)

    try:
        record = create_waste_record(
            connection,
            event_at=event_at,
            area_id=selected_ids["area_id"],
            category_id=selected_ids["category_id"],
            reason_id=selected_ids["reason_id"],
            quantity_kg=quantity_kg,
            user_id=actor.id,
        )
    except (sqlite3.Error, ValueError):
        current_app.logger.exception("Could not save waste record")
        return _render_form(
            **form_context,
            message="The record could not be saved. Check the details and try again.",
            status=500,
        )

    return redirect(url_for("new_record", created=record.id), code=303)
