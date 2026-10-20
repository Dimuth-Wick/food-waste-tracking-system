"""Database-backed descriptive dashboard for recorded food waste."""

from collections import defaultdict
from datetime import date, datetime, timedelta
import sqlite3

from flask import current_app, render_template, request

from app.database.connection import get_db
from app.waste_records.add_record import DEMO_TIMEZONE
from app.database.queries import list_lookup_items, list_waste_records
from app.waste_records.record_list import FILTER_FIELDS, _parse_filters, _utc_boundary


def _now_local():
    return datetime.now(DEMO_TIMEZONE)


def _breakdown(rows, field):
    totals = defaultdict(float)
    for row in rows:
        totals[row[field]] += row["quantity_kg"]
    largest = max(totals.values(), default=0)
    return [
        {"name": name, "quantity_kg": quantity, "percent": quantity / largest * 100}
        for name, quantity in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    ]


def build_summary(rows, today: date):
    """Summarize already filtered rows using Sri Lanka calendar dates."""
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    local_rows = []
    for row in rows:
        event = datetime.fromisoformat(row["event_at"].replace("Z", "+00:00")).astimezone(
            DEMO_TIMEZONE
        )
        local_rows.append({**row, "local_date": event.date(), "date": event.strftime("%d %b %Y"),
                           "time": event.strftime("%H:%M")})

    return {
        "total_kg": sum(row["quantity_kg"] for row in local_rows),
        "today_kg": sum(row["quantity_kg"] for row in local_rows if row["local_date"] == today),
        "week_kg": sum(row["quantity_kg"] for row in local_rows
                       if week_start <= row["local_date"] <= today),
        "month_kg": sum(row["quantity_kg"] for row in local_rows
                        if month_start <= row["local_date"] <= today),
        "area_breakdown": _breakdown(local_rows, "area"),
        "category_breakdown": _breakdown(local_rows, "category"),
        "reason_breakdown": _breakdown(local_rows, "reason"),
        "recent_records": local_rows[:5],
        "record_count": len(local_rows),
    }


def dashboard():
    values = {field: request.args.get(field, "").strip() for field in FILTER_FIELDS}
    context = {
        "active_page": "dashboard", "values": values,
        "has_filters": any(values.values()), "errors": {}, "database_error": False,
        "areas": [], "categories": [], "reasons": [], "summary": None,
    }
    try:
        connection = get_db()
        lookups = {
            table: list_lookup_items(connection, table)
            for table in ("areas", "categories", "reasons")
        }
        context.update(lookups)
        errors, parsed = _parse_filters(values, lookups)
        context["errors"] = errors
        if errors:
            return render_template("dashboard.html", **context), 400

        rows = list_waste_records(
            connection,
            start_at_utc=_utc_boundary(parsed["start_date"]) if "start_date" in parsed else None,
            end_before_utc=_utc_boundary(parsed["end_date"] + timedelta(days=1))
            if "end_date" in parsed and parsed["end_date"] < date.max else None,
            area_id=parsed.get("area_id"),
            category_id=parsed.get("category_id"),
            reason_id=parsed.get("reason_id"),
        )
        context["summary"] = build_summary(rows, _now_local().date())
    except sqlite3.Error:
        current_app.logger.exception("Could not load dashboard data")
        context["database_error"] = True
        return render_template("dashboard.html", **context), 503
    return render_template("dashboard.html", **context)
