from datetime import date, datetime

import pytest

from app import create_app
from app.database.connection import get_db, init_db
from app.waste_records.add_record import DEMO_TIMEZONE
from app.database.queries import create_user, create_waste_record


@pytest.fixture
def dashboard_app(tmp_path, monkeypatch):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "dashboard.sqlite3")})
    monkeypatch.setattr("app.waste_records.dashboard._now_local", lambda: datetime(2026, 10, 2, 12, tzinfo=DEMO_TIMEZONE))
    with app.app_context():
        init_db()
        db = get_db()
        for table, names in (
            ("areas", ["Kitchen", "Buffet"]),
            ("categories", ["Vegetables", "Bakery"]),
            ("reasons", ["Spoilage", "Overproduction"]),
        ):
            for name in names:
                db.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))
        db.commit()
        user = create_user(db, name="Staff", username="staff", password="test", role="entry")
        ids = {
            table: {row["name"]: row["id"] for row in db.execute(f"SELECT id, name FROM {table}")}
            for table in ("areas", "categories", "reasons")
        }
    return app, user.id, ids


def add_record(app, user_id, ids, when, kg, area="Kitchen", category="Vegetables", reason="Spoilage"):
    with app.app_context():
        return create_waste_record(
            get_db(), event_at=datetime.fromisoformat(when).replace(tzinfo=DEMO_TIMEZONE),
            area_id=ids["areas"][area], category_id=ids["categories"][category],
            reason_id=ids["reasons"][reason], quantity_kg=kg, user_id=user_id,
        )


def test_dashboard_uses_stored_rows_and_local_calendar_boundaries(dashboard_app):
    app, user_id, ids = dashboard_app
    client = app.test_client()
    empty = client.get("/")
    assert empty.status_code == 200
    assert b"No waste records yet" in empty.data
    assert b"0.00" in empty.data

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

    html = client.get("/").get_data(as_text=True)
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
    first = add_record(app, user_id, ids, "2026-10-01T00:00", 4,
                       "Buffet", "Bakery", "Overproduction")
    add_record(app, user_id, ids, "2026-10-02T00:00", 5,
               "Buffet", "Vegetables", "Spoilage")
    client = app.test_client()
    query = (f"start_date=2026-10-01&end_date=2026-10-01&area_id={ids['areas']['Buffet']}"
             f"&category_id={ids['categories']['Bakery']}&reason_id={ids['reasons']['Overproduction']}")
    page = client.get(f"/?{query}")
    assert page.status_code == 200
    assert "4.00" in page.get_data(as_text=True)
    assert "1 record matching filters" in page.get_data(as_text=True)
    assert f"FW-{first.id:03d}".encode() in client.get(f"/records?{query}").data

    with app.app_context():
        db = get_db()
        db.execute("UPDATE waste_records SET quantity_kg = 8 WHERE id = ?", (first.id,))
        db.commit()
    updated = client.get(f"/?{query}").get_data(as_text=True)
    assert "8.00" in updated
    assert "4.00" not in updated

    invalid = client.get("/?start_date=2026-10-03&end_date=2026-10-01")
    assert invalid.status_code == 400
    assert b"To date must be on or after From date" in invalid.data
    assert b"Waste summary" not in invalid.data

    no_match = client.get("/?start_date=2026-11-01")
    assert no_match.status_code == 200
    assert b"No records match these filters" in no_match.data
