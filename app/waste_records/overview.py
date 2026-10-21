"""Waste overview: filters, totals, breakdowns and every record, on one page.

The add and edit forms (add_record.py, edit_record.py) open as a side panel
over this page, so they render it through ``render_overview``.
"""

from dataclasses import replace
from datetime import date, datetime, timedelta
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import actor_for
from app.database.connection import get_session
from app.database.queries import (
    RecordFilters,
    count_waste_records,
    get_waste_record,
    list_daily_amounts,
    list_waste_records,
    total_waste_kg,
    total_waste_value,
    waste_by,
)
from app.waste_records.common import (
    DEMO_TIMEZONE,
    FILTER_FIELDS,
    MEALS,
    HEAVY_KG,
    MODERATE_KG,
    can_edit,
    display_row,
    load_lookups,
    local_time,
    parse_filters,
    parse_id,
    utc_boundary,
)
from app.web import render, url_path


logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)
INITIAL_ROWS = 5   # days shown before "See more"
MORE_ROWS = 20     # extra days each "See more" adds


def _now_local():
    return datetime.now(DEMO_TIMEZONE)


def _within(filters: RecordFilters, start: date, end: date) -> RecordFilters:
    """Narrow the filters to Sri Lanka dates start..end inclusive."""
    start_utc, end_utc = utc_boundary(start), utc_boundary(end + timedelta(days=1))
    return replace(
        filters,
        start_at_utc=max(filter(None, (filters.start_at_utc, start_utc))),
        end_before_utc=min(filter(None, (filters.end_before_utc, end_utc))),
    )


def _breakdown(rows):
    """Bars by value: the most costly first, the longest bar 100%."""
    largest = max((value for _, _, value in rows), default=0) or 1
    return [{"name": name, "quantity_kg": kg, "value": value, "percent": value / largest * 100} for name, kg, value in rows]


def build_summary(db: Session, filters: RecordFilters, today: date) -> dict:
    """Totals for the filtered records, using Sri Lanka calendar dates."""
    return {
        "total_kg": total_waste_kg(db, filters),
        "today_kg": total_waste_kg(db, _within(filters, today, today)),
        "week_kg": total_waste_kg(db, _within(filters, today - timedelta(days=today.weekday()), today)),
        "month_kg": total_waste_kg(db, _within(filters, today.replace(day=1), today)),
        "total_value": total_waste_value(db, filters),
        "today_value": total_waste_value(db, _within(filters, today, today)),
        "week_value": total_waste_value(db, _within(filters, today - timedelta(days=today.weekday()), today)),
        "month_value": total_waste_value(db, _within(filters, today.replace(day=1), today)),
        "area_breakdown": _breakdown(waste_by(db, "areas", filters)),
        "food_breakdown": _breakdown(waste_by(db, "categories", filters)),
        "reason_breakdown": _breakdown(waste_by(db, "reasons", filters)),
        "record_count": count_waste_records(db, filters),
    }


DAILY_DAYS = 30


def build_daily(db: Session, filters: RecordFilters, today: date) -> list[dict]:
    """Waste and shortage per Sri Lanka calendar day for the last 30 days, oldest first.

    Follows the area and reason filters, but not the date filters: it is always the last 30 days.
    """
    first = today - timedelta(days=DAILY_DAYS - 1)
    window = _within(replace(filters, start_at_utc=None, end_before_utc=None), first, today)
    days = {first + timedelta(days=i): {"waste": 0.0, "short": 0.0, "waste_value": 0.0, "short_value": 0.0}
            for i in range(DAILY_DAYS)}
    for event_at, kg, value, is_short in list_daily_amounts(db, window):
        day = local_time(event_at).date()
        if day in days:
            days[day]["short" if is_short else "waste"] += kg
            days[day]["short_value" if is_short else "waste_value"] += value
    return [{"date": day.isoformat(), "waste": round(v["waste"], 2), "short": round(v["short"], 2),
             "waste_value": round(v["waste_value"]), "short_value": round(v["short_value"])}
            for day, v in days.items()]


def view_state(request: Request) -> dict[str, str]:
    """The filters and number of rows shown in the address, so links and forms can keep them."""
    return {key: request.query_params[key].strip() for key in (*FILTER_FIELDS, "show", "day")
            if request.query_params.get(key, "").strip()}


def _rows_shown(raw: str) -> int:
    return int(raw) if raw.isdigit() and INITIAL_ROWS < int(raw) < 10**5 else INITIAL_ROWS


def _open_day(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else None
    except ValueError:
        return None


def group_by_day(records: list[dict]) -> list[dict]:
    """One entry per Sri Lanka calendar day, newest first, with waste and shortage totals."""
    days = {}
    for record in records:
        day = days.setdefault(record["day"], {"day": record["day"], "date": record["date"], "waste_kg": 0.0,
                                              "short_kg": 0.0, "waste_value": 0.0, "short_value": 0.0, "records": []})
        short = record["band"] == "short"
        day["short_kg" if short else "waste_kg"] += record["quantity_kg"]
        day["short_value" if short else "waste_value"] += record["value"]
        day["records"].append(record)
    for day in days.values():
        day["records"].sort(key=lambda record: (record["time"], record["id"]))
        day["meals"] = [{"name": meal, "records": [r for r in day["records"] if r["meal"] == meal]}
                        for meal in MEALS]
        for meal in day["meals"]:
            meal["waste_kg"] = sum(r["quantity_kg"] for r in meal["records"] if r["band"] != "short")
            meal["short_kg"] = sum(r["quantity_kg"] for r in meal["records"] if r["band"] == "short")
            meal["waste_value"] = sum(r["value"] for r in meal["records"] if r["band"] != "short")
            meal["short_value"] = sum(r["value"] for r in meal["records"] if r["band"] == "short")
    return sorted(days.values(), key=lambda day: day["day"], reverse=True)


def _notice(db: Session, request: Request):
    """A success message after saving, from ?created=ID or ?updated=ID."""
    for key, verb in (("created", "saved"), ("updated", "updated")):
        record_id = parse_id(request.query_params.get(key, ""))
        if record_id is not None and (record := get_waste_record(db, record_id)):
            return {"verb": verb, "record": record}
    return None


def render_overview(request: Request, db: Session, *, panel=None, status_code=200):
    """Render the overview page, optionally with the add or edit panel open."""
    state = view_state(request)
    filters_only = {key: value for key, value in state.items() if key not in ("show", "day")}
    values = {field: state.get(field, "") for field in FILTER_FIELDS}
    context = {
        "active_page": "dashboard", "values": values, "has_filters": bool(filters_only),
        "errors": {}, "database_error": False, "areas": [], "categories": [], "reasons": [],
        "summary": None, "daily": None, "days": [], "more": None, "notice": None, "panel": panel,
        "moderate_kg": MODERATE_KG, "heavy_kg": HEAVY_KG,
        "add_url": url_path(request.app, "new_record", **state),
        "clear_filters_url": url_path(request.app, "dashboard"),
    }
    try:
        lookups = load_lookups(db)
        context.update(lookups)
        errors, filters = parse_filters(values, lookups)
        context["errors"] = errors
        if errors:
            return render(request, "overview.html", 400 if status_code == 200 else status_code, **context)

        context["summary"] = summary = build_summary(db, filters, _now_local().date())
        context["daily"] = build_daily(db, filters, _now_local().date())
        actor = actor_for(request, db)
        records = [
            {**display_row(row), "can_edit": can_edit(actor, row["user_id"]),
             "edit_url": url_path(request.app, "edit_record", record_id=row["id"], **state)}
            for row in list_waste_records(db, filters)
        ]
        days = group_by_day(records)
        for day in days:
            day["url"] = url_path(request.app, "day_details", day=day["day"], **filters_only)
        shown = _rows_shown(state.get("show", ""))
        context["days"] = days[:shown]
        if len(days) > INITIAL_ROWS:
            context["more"] = {
                "shown": min(shown, len(days)), "total": len(days), "remaining": max(0, len(days) - shown),
                "next_batch": min(MORE_ROWS, max(0, len(days) - shown)),
                "more_url": url_path(request.app, "dashboard", **filters_only, show=shown + MORE_ROWS) + "#records",
                "fewer_url": url_path(request.app, "dashboard", **filters_only) + "#records",
            }
        context["notice"] = None if panel else _notice(db, request)
    except SQLAlchemyError:
        logger.exception("Could not load the waste overview")
        context["database_error"] = True
        return render(request, "overview.html", 503, **context)
    return render(request, "overview.html", status_code, **context)


@router.get("/", name="dashboard")
def overview(request: Request, db: Session = Depends(get_session)):
    # Days used to open in a side panel at /?day=...; they have their own page now.
    if (opened := _open_day(request.query_params.get("day", ""))) is not None:
        rest = {key: value for key, value in request.query_params.items() if key not in ("day", "show")}
        return RedirectResponse(url_path(request.app, "day_details", day=opened.isoformat(), **rest), status_code=308)
    return render_overview(request, db)


def day_page_url(request: Request, day: str, **extra) -> str:
    """The day's own page, keeping the overview's filters."""
    filters_only = {key: value for key, value in view_state(request).items() if key not in ("show", "day")}
    return url_path(request.app, "day_details", day=day, **filters_only, **extra)


@router.get("/days/{day}", name="day_details")
def day_details(request: Request, day: str, db: Session = Depends(get_session)):
    """Every record for one Sri Lanka calendar day, grouped by meal, on its own page."""
    opened = _open_day(day)
    if opened is None:
        raise HTTPException(404)
    state = view_state(request)
    filters_only = {key: value for key, value in state.items() if key not in ("show", "day")}
    values = {field: state.get(field, "") for field in FILTER_FIELDS}
    try:
        lookups = load_lookups(db)
        errors, filters = parse_filters(values, lookups)
        if errors:
            raise HTTPException(400, " ".join(errors.values()))
        actor = actor_for(request, db)
        records = [
            {**display_row(row), "can_edit": can_edit(actor, row["user_id"]),
             "edit_url": url_path(request.app, "edit_record", record_id=row["id"], **filters_only, day=opened.isoformat())}
            for row in list_waste_records(db, filters)
        ]
        notice = _notice(db, request)
    except SQLAlchemyError:
        logger.exception("Could not load the day's records")
        raise HTTPException(503, "The database is unavailable. Try again later.") from None

    days = group_by_day(records)
    index = next((i for i, item in enumerate(days) if item["day"] == opened.isoformat()), None)
    current = days[index] if index is not None else {
        "day": opened.isoformat(), "date": opened.strftime("%d %b %Y"), "waste_kg": 0.0, "short_kg": 0.0,
        "waste_value": 0.0, "short_value": 0.0, "records": [],
        "meals": [{"name": meal, "records": [], "waste_kg": 0.0, "short_kg": 0.0, "waste_value": 0.0, "short_value": 0.0}
                  for meal in MEALS]}
    if index is None:
        later = [item for item in days if item["day"] > opened.isoformat()]
        earlier = [item for item in days if item["day"] < opened.isoformat()]
        newer, older = (later[-1] if later else None), (earlier[0] if earlier else None)
    else:
        newer = days[index - 1] if index > 0 else None
        older = days[index + 1] if index + 1 < len(days) else None
    link = lambda item: url_path(request.app, "day_details", day=item["day"], **filters_only) if item else None
    busiest = max(current["meals"], key=lambda meal: meal["waste_value"])
    return render(
        request, "day.html", active_page="dashboard", day=current, notice=notice,
        has_filters=bool(filters_only), busiest=busiest if busiest["waste_value"] else None,
        newer_url=link(newer), older_url=link(older),
        newer_date=newer["date"] if newer else None, older_date=older["date"] if older else None,
        back_url=url_path(request.app, "dashboard", **filters_only) + "#records",
        all_url=url_path(request.app, "day_details", day=opened.isoformat()),
        add_url=url_path(request.app, "new_record", **filters_only, day=opened.isoformat()),
    )


@router.get("/records", name="records")
def old_records_address(request: Request):
    """The records list is now part of the overview; keep old links working."""
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url_path(request.app, "dashboard") + query, status_code=308)
