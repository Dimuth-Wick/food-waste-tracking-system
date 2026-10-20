"""Dashboard: waste totals and breakdowns, added up by the database."""

from dataclasses import replace
from datetime import date, datetime, timedelta
import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.connection import get_session
from app.database.queries import (
    RecordFilters,
    count_waste_records,
    list_waste_records,
    total_waste_kg,
    waste_by,
)
from app.waste_records.common import (
    DEMO_TIMEZONE,
    FILTER_FIELDS,
    display_row,
    load_lookups,
    parse_filters,
    utc_boundary,
)
from app.web import render


logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)


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
        "category_breakdown": _breakdown(waste_by(db, "categories", filters)),
        "reason_breakdown": _breakdown(waste_by(db, "reasons", filters)),
        "recent_records": [display_row(row) for row in list_waste_records(db, filters, limit=5)],
        "record_count": count_waste_records(db, filters),
    }


@router.get("/", name="dashboard")
def dashboard(request: Request, db: Session = Depends(get_session)):
    values = {field: request.query_params.get(field, "").strip() for field in FILTER_FIELDS}
    context = {
        "active_page": "dashboard", "values": values, "has_filters": any(values.values()),
        "errors": {}, "database_error": False, "areas": [], "categories": [], "reasons": [],
        "summary": None,
    }
    try:
        lookups = load_lookups(db)
        context.update(lookups)
        errors, filters = parse_filters(values, lookups)
        context["errors"] = errors
        if errors:
            return render(request, "dashboard.html", 400, **context)
        context["summary"] = build_summary(db, filters, _now_local().date())
    except SQLAlchemyError:
        logger.exception("Could not load dashboard data")
        context["database_error"] = True
        return render(request, "dashboard.html", 503, **context)
    return render(request, "dashboard.html", **context)
