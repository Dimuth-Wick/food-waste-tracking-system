"""Helpers shared by the dashboard, records list and record forms."""

from datetime import date, datetime, time, timedelta, timezone
import re

from sqlalchemy.orm import Session

from app.database.queries import MAX_ID, SHORTAGE_REASON, RecordFilters, list_lookup_items


# The demo hotel is in Sri Lanka; dates on screen use Sri Lanka local time.
DEMO_TIMEZONE = timezone(timedelta(hours=5, minutes=30))
DEMO_USERNAME = "demo_entry"
LOOKUPS = ("areas", "reasons")
FILTER_FIELDS = ("start_date", "end_date", "area_id", "reason_id")


def parse_id(raw: str) -> int | None:
    """Accept only positive decimal IDs that fit a 64-bit database integer."""
    if not re.fullmatch(r"[0-9]{1,19}", raw):
        return None
    value = int(raw)
    return value if 0 < value <= MAX_ID else None


def load_lookups(db: Session, *, active_only: bool = False) -> dict[str, list]:
    return {
        table: [item for item in list_lookup_items(db, table) if item.active or not active_only]
        for table in LOOKUPS
    }


def local_time(event_at_utc: str) -> datetime:
    return datetime.fromisoformat(event_at_utc.replace("Z", "+00:00")).astimezone(DEMO_TIMEZONE)


def utc_boundary(local_date: date) -> str:
    """UTC text for midnight at the start of a Sri Lanka calendar day."""
    return datetime.combine(local_date, time.min, tzinfo=DEMO_TIMEZONE).astimezone(
        timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%SZ")


def can_edit(actor, record_user_id: int) -> bool:
    return bool(
        actor and actor.active
        and (actor.role in {"manager", "admin"} or actor.role == "entry" and actor.id == record_user_id)
    )


def parse_filters(values: dict[str, str], lookups) -> tuple[dict[str, str], RecordFilters]:
    """Check the filter form. Returns (errors by field, filters for the database)."""
    errors = {}
    dates = {}
    for field, label in (("start_date", "From date"), ("end_date", "To date")):
        raw = values[field]
        if raw:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                    raise ValueError("Invalid date format")
                dates[field] = date.fromisoformat(raw)
            except ValueError:
                errors[field] = f"{label} must be a valid date."
    if "start_date" in dates and "end_date" in dates and dates["start_date"] > dates["end_date"]:
        errors["end_date"] = "To date must be on or after From date."

    ids = {}
    for field, label, table in (("area_id", "area", "areas"), ("reason_id", "reason", "reasons")):
        raw = values[field]
        if raw:
            if (parsed := parse_id(raw)) not in {item.id for item in lookups[table]}:
                errors[field] = f"Select a valid {label}."
            else:
                ids[field] = parsed

    end = dates.get("end_date")
    return errors, RecordFilters(
        start_at_utc=utc_boundary(dates["start_date"]) if "start_date" in dates else None,
        end_before_utc=utc_boundary(end + timedelta(days=1)) if end and end < date.max else None,
        **ids,
    )


# Weight bands used to colour the records table: green, amber, red.
MODERATE_KG = 2
HEAVY_KG = 5


def weight_band(quantity_kg: float, reason: str | None = None) -> str:
    """"light", "moderate" or "heavy" so heavy waste stands out; "short" when food ran out."""
    if reason == SHORTAGE_REASON:
        return "short"
    return "heavy" if quantity_kg >= HEAVY_KG else "moderate" if quantity_kg >= MODERATE_KG else "light"


def display_row(row: dict) -> dict:
    """Add Sri Lanka date and time strings to a record row for templates."""
    moment = local_time(row["event_at"])
    return {**row, "date": moment.strftime("%d %b %Y"), "time": moment.strftime("%H:%M"),
            "band": weight_band(row["quantity_kg"], row.get("reason"))}
