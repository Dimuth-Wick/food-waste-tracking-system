"""Display saved waste records with the plan's basic filters."""

from datetime import date, datetime, time, timedelta, timezone
import re
import sqlite3

from flask import current_app, render_template, request

from app.database.connection import get_db
from app.waste_records.add_record import DEMO_TIMEZONE, _parse_id
from app.waste_records.edit_record import can_edit
from app.database.queries import get_user_by_username, list_lookup_items, list_waste_records


FILTER_FIELDS = ("start_date", "end_date", "area_id", "category_id", "reason_id")


def _utc_boundary(local_date: date) -> str:
    return datetime.combine(local_date, time.min, tzinfo=DEMO_TIMEZONE).astimezone(
        timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_filters(values, lookups):
    errors = {}
    parsed = {}

    for field, label in (("start_date", "From date"), ("end_date", "To date")):
        raw = values[field]
        if raw:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                    raise ValueError("Invalid date format")
                parsed[field] = date.fromisoformat(raw)
            except ValueError:
                errors[field] = f"{label} must be a valid date."

    if "start_date" in parsed and "end_date" in parsed:
        if parsed["start_date"] > parsed["end_date"]:
            errors["end_date"] = "To date must be on or after From date."

    for field, label, table in (
        ("area_id", "area", "areas"),
        ("category_id", "category", "categories"),
        ("reason_id", "reason", "reasons"),
    ):
        raw = values[field]
        if raw:
            if (parsed_id := _parse_id(raw)) not in {item.id for item in lookups[table]}:
                errors[field] = f"Select a valid {label}."
            else:
                parsed[field] = parsed_id

    return errors, parsed


def records():
    values = {field: request.args.get(field, "").strip() for field in FILTER_FIELDS}
    try:
        connection = get_db()
        lookups = {
            table: list_lookup_items(connection, table)
            for table in ("areas", "categories", "reasons")
        }
        actor = get_user_by_username(connection, "demo_entry")
    except sqlite3.Error:
        current_app.logger.exception("Could not load waste records")
        return render_template(
            "records.html", active_page="records", records=[], areas=[], categories=[],
            reasons=[], values=values, errors={}, database_error=True,
        ), 503

    errors, parsed = _parse_filters(values, lookups)
    records_for_display = []
    if not errors:
        try:
            rows = list_waste_records(
                connection,
                start_at_utc=_utc_boundary(parsed["start_date"]) if "start_date" in parsed else None,
                end_before_utc=_utc_boundary(parsed["end_date"] + timedelta(days=1))
                if "end_date" in parsed and parsed["end_date"] < date.max else None,
                area_id=parsed.get("area_id"),
                category_id=parsed.get("category_id"),
                reason_id=parsed.get("reason_id"),
            )
        except sqlite3.Error:
            current_app.logger.exception("Could not query waste records")
            return render_template(
                "records.html", active_page="records", records=[],
                areas=lookups["areas"], categories=lookups["categories"],
                reasons=lookups["reasons"], values=values, errors={}, database_error=True,
            ), 503

        for row in rows:
            local_time = datetime.fromisoformat(row["event_at"].replace("Z", "+00:00")).astimezone(
                DEMO_TIMEZONE
            )
            records_for_display.append({
                **row,
                "date": local_time.strftime("%d %b %Y"),
                "time": local_time.strftime("%H:%M"),
                "can_edit": can_edit(actor, row["user_id"]),
            })

    return render_template(
        "records.html",
        active_page="records",
        records=records_for_display,
        areas=lookups["areas"],
        categories=lookups["categories"],
        reasons=lookups["reasons"],
        values=values,
        errors=errors,
        database_error=False,
        has_filters=any(values.values()),
    ), 400 if errors else 200
