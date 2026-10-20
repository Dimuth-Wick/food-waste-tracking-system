from datetime import datetime

import pytest

from app.database.queries import create_user, create_waste_record
from app.waste_records.common import DEMO_TIMEZONE
from conftest import add_lookups, client, database, make_app, sql


@pytest.fixture
def dashboard_app(tmp_path, monkeypatch):
    app = make_app(tmp_path, "dashboard.sqlite3")
    monkeypatch.setattr("app.waste_records.dashboard._now_local",
                        lambda: datetime(2026, 10, 2, 12, tzinfo=DEMO_TIMEZONE))
    with database(app) as db:
        add_lookups(db, {"areas": ["Kitchen", "Buffet"], "categories": ["Vegetables", "Bakery"],
                         "reasons": ["Spoilage", "Overproduction"]})
        user = create_user(db, name="Staff", username="staff", password="test", role="entry")
        ids = {
            table: {row.name: row.id for row in sql(db, f"SELECT id, name FROM {table}")}
            for table in ("areas", "categories", "reasons")
        }
    return app, user.id, ids


def add_record(app, user_id, ids, when, kg, area="Kitchen", category="Vegetables", reason="Spoilage"):
    with database(app) as db:
        return create_waste_record(
            db, event_at=datetime.fromisoformat(when).replace(tzinfo=DEMO_TIMEZONE),
            area_id=ids["areas"][area], category_id=ids["categories"][category],
            reason_id=ids["reasons"][reason], quantity_kg=kg, user_id=user_id,
        )


def test_dashboard_uses_stored_rows_and_local_calendar_boundaries(dashboard_app):
    app, user_id, ids = dashboard_app
    browser = client(app)
    empty = browser.get("/")
    assert empty.status_code == 200
    assert "No waste records yet" in empty.text
    assert "0.00" in empty.text

    entries = [
        ("2026-09-27T23:59", 1, "Kitchen", "Vegetables", "Spoilage"),
        ("2026-09-28T00:00", 2, "Kitchen", "Vegetables", "Spoilage"),
        ("2026-09-30T23:59", 3, "Buffet", "Bakery", "Overproduction"),
        ("2026-10-01T00:00", 4, "Buffet", "Bakery", "Overproduction"),
        ("2026-10-02T00:00", 5, "Buffet", "Vegetables", "Spoilage"),
        ("2026-10-02T23:59", 6, "Kitchen", "Bakery", "Overproduction"),
        ("2026-10-03T00:00", 7, "Kitchen", "Vegetables", "Spoilage"),
    ]
    for when, kg, area, category, reason in entries:
        add_record(app, user_id, ids, when, kg, area, category, reason)

    html = browser.get("/").text
    for label, value in (("Total recorded", "28.00"), ("Today", "11.00"),
                         ("This week", "20.00"), ("This month", "15.00")):
        assert label in html
        assert value in html
    assert "7 records" in html
    assert "Kitchen: 16.00 kilograms" in html
    assert "Buffet: 12.00 kilograms" in html
    assert "Bakery: 13.00 kilograms" in html
    assert "Spoilage: 15.00 kilograms" in html
    assert "03 Oct 2026" in html
    assert "27 Sep 2026" not in html  # recent activity is capped at five records
    assert "sample data" not in html.lower()


def test_dashboard_filters_match_records_page_and_refresh_after_edit(dashboard_app):
    app, user_id, ids = dashboard_app
    first = add_record(app, user_id, ids, "2026-10-01T00:00", 4, "Buffet", "Bakery", "Overproduction")
    add_record(app, user_id, ids, "2026-10-02T00:00", 5, "Buffet", "Vegetables", "Spoilage")
    browser = client(app)
    query = (f"start_date=2026-10-01&end_date=2026-10-01&area_id={ids['areas']['Buffet']}"
             f"&category_id={ids['categories']['Bakery']}&reason_id={ids['reasons']['Overproduction']}")
    page = browser.get(f"/?{query}")
    assert page.status_code == 200
    assert "4.00" in page.text
    assert "1 record matching filters" in page.text
    assert f"FW-{first.id:03d}" in browser.get(f"/records?{query}").text

    with database(app) as db:
        sql(db, "UPDATE waste_records SET quantity_kg = 8 WHERE id = :id", id=first.id)
        db.commit()
    updated = browser.get(f"/?{query}").text
    assert "8.00" in updated
    assert "4.00" not in updated

    invalid = browser.get("/?start_date=2026-10-03&end_date=2026-10-01")
    assert invalid.status_code == 400
    assert "To date must be on or after From date" in invalid.text
    assert "Waste summary" not in invalid.text

    no_match = browser.get("/?start_date=2026-11-01")
    assert no_match.status_code == 200
    assert "No records match these filters" in no_match.text
