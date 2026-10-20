"""Waste overview: filters, totals, breakdowns and every record, on one page.

The add and edit forms (add_record.py, edit_record.py) open as a side panel
over this page, so they render it through ``render_overview``.
"""

from dataclasses import replace
from datetime import date, datetime, timedelta
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.connection import get_session
from app.database.queries import (
    RecordFilters,
    count_waste_records,
    get_user_by_username,
    get_waste_record,
    list_daily_amounts,
    list_waste_records,
    total_waste_kg,
    waste_by,
)
from app.waste_records.common import (
    DEMO_TIMEZONE,
    DEMO_USERNAME,
    FILTER_FIELDS,
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
INITIAL_ROWS = 5   # records shown before "See more"
MORE_ROWS = 20     # extra records each "See more" adds


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
    largest = max((kg for _, kg in rows), default=0) or 1
    return [{"name": name, "quantity_kg": kg, "percent": kg / largest * 100} for name, kg in rows]


def build_summary(db: Session, filters: RecordFilters, today: date) -> dict:
    """Totals for the filtered records, using Sri Lanka calendar dates."""
    return {
        "total_kg": total_waste_kg(db, filters),
        "today_kg": total_waste_kg(db, _within(filters, today, today)),
        "week_kg": total_waste_kg(db, _within(filters, today - timedelta(days=today.weekday()), today)),
        "month_kg": total_waste_kg(db, _within(filters, today.replace(day=1), today)),
        "area_breakdown": _breakdown(waste_by(db, "areas", filters)),
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
    days = {first + timedelta(days=i): {"waste": 0.0, "short": 0.0} for i in range(DAILY_DAYS)}
    for event_at, kg, is_short in list_daily_amounts(db, window):
        day = local_time(event_at).date()
        if day in days:
            days[day]["short" if is_short else "waste"] += kg
    return [{"date": day.isoformat(), "waste": round(v["waste"], 2), "short": round(v["short"], 2)}
            for day, v in days.items()]


def view_state(request: Request) -> dict[str, str]:
    """The filters and number of rows shown in the address, so links and forms can keep them."""
    return {key: request.query_params[key].strip() for key in (*FILTER_FIELDS, "show")
            if request.query_params.get(key, "").strip()}


def _rows_shown(raw: str) -> int:
    return int(raw) if raw.isdigit() and INITIAL_ROWS < int(raw) < 10**5 else INITIAL_ROWS


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
    filters_only = {key: value for key, value in state.items() if key != "show"}
    values = {field: state.get(field, "") for field in FILTER_FIELDS}
    context = {
        "active_page": "dashboard", "values": values, "has_filters": bool(filters_only),
        "errors": {}, "database_error": False, "areas": [], "reasons": [],
        "summary": None, "daily": None, "records": [], "more": None, "notice": None, "panel": panel,
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
        total = summary["record_count"]
        shown = _rows_shown(state.get("show", ""))
        actor = get_user_by_username(db, DEMO_USERNAME)
        context["records"] = [
            {**display_row(row), "can_edit": can_edit(actor, row["user_id"]),
             "edit_url": url_path(request.app, "edit_record", record_id=row["id"], **state)}
            for row in list_waste_records(db, filters, limit=shown, offset=0)
        ]
        if total > INITIAL_ROWS:
            context["more"] = {
                "shown": min(shown, total), "remaining": max(0, total - shown),
                "next_batch": min(MORE_ROWS, max(0, total - shown)),
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
    return render_overview(request, db)


@router.get("/records", name="records")
def old_records_address(request: Request):
    """The records list is now part of the overview; keep old links working."""
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(url_path(request.app, "dashboard") + query, status_code=308)
