"""Waste records page: every record, newest first, filtered and split into pages."""

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.connection import get_session
from app.database.queries import count_waste_records, get_user_by_username, list_waste_records
from app.waste_records.common import (
    DEMO_USERNAME,
    FILTER_FIELDS,
    can_edit,
    display_row,
    load_lookups,
    parse_filters,
)
from app.web import render, url_path


logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)
PAGE_SIZE = 50


def _page_number(raw: str) -> int:
    return int(raw) if raw.isdigit() and 0 < int(raw) < 10**6 else 1


@router.get("/records", name="records")
def records(request: Request, db: Session = Depends(get_session)):
    values = {field: request.query_params.get(field, "").strip() for field in FILTER_FIELDS}
    context = {"active_page": "records", "records": [], "values": values, "errors": {},
               "areas": [], "categories": [], "reasons": [], "database_error": False,
               "has_filters": any(values.values()), "total": 0, "pager": None}
    try:
        lookups = load_lookups(db)
        context.update(lookups)
        errors, filters = parse_filters(values, lookups)
        context["errors"] = errors
        if errors:
            return render(request, "records.html", 400, **context)

        actor = get_user_by_username(db, DEMO_USERNAME)
        total = count_waste_records(db, filters)
        pages = max(1, -(-total // PAGE_SIZE))
        page = min(_page_number(request.query_params.get("page", "")), pages)
        rows = list_waste_records(db, filters, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
    except SQLAlchemyError:
        logger.exception("Could not load waste records")
        context["database_error"] = True
        return render(request, "records.html", 503, **context)

    filter_query = {field: value for field, value in values.items() if value}
    context.update(
        total=total,
        records=[{**display_row(row), "can_edit": can_edit(actor, row["user_id"])} for row in rows],
        pager=None if pages == 1 else {
            "page": page, "pages": pages,
            "first": (page - 1) * PAGE_SIZE + 1, "last": min(page * PAGE_SIZE, total),
            "previous": url_path(request.app, "records", **filter_query, page=page - 1) if page > 1 else None,
            "next": url_path(request.app, "records", **filter_query, page=page + 1) if page < pages else None,
        },
    )
    return render(request, "records.html", **context)
