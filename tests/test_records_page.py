from datetime import datetime, timedelta, timezone

import pytest

from app.database.queries import create_user, create_waste_record
from conftest import add_lookups, client, database, make_app, scalar


@pytest.fixture
def app_with_empty_records(tmp_path):
    app = make_app(tmp_path, "records.sqlite3")
    with database(app) as db:
        add_lookups(db, {"areas": ["Main Kitchen", "Buffet"], "categories": ["Vegetables", "Bakery"],
                         "reasons": ["Spoilage", "Plate Returns"]})
        create_user(db, name="Demo Kitchen Staff", username="demo_entry",
                    password="test password", role="entry")
    return app


RECORD_FORM = {"event_at": "2026-10-01T00:30", "area_id": "1", "category_id": "1",
               "reason_id": "1", "quantity_kg": "1.25"}


def test_newly_created_record_appears_in_list(app_with_empty_records):
    app = app_with_empty_records
    browser = client(app)

    empty = browser.get("/records")
    assert empty.status_code == 200
    assert "No waste records yet" in empty.text

    assert browser.post("/records/new", data=RECORD_FORM).status_code == 303

    page = browser.get("/records")
    assert page.status_code == 200
    for expected in ("FW-001", "01 Oct 2026", "00:30", "Main Kitchen", "Vegetables",
                     "Spoilage", "Demo Kitchen Staff", "1.25 kg"):
        assert expected in page.text
    assert "1 record" in page.text

    with database(app) as db:
        assert scalar(db, "SELECT event_at FROM waste_records WHERE id = 1") == "2026-09-30T19:00:00Z"


def test_basic_filters_and_no_matches(app_with_empty_records):
    browser = client(app_with_empty_records)
    browser.post("/records/new", data=RECORD_FORM)

    matching = browser.get("/records?start_date=2026-10-01&end_date=2026-10-01&area_id=1&category_id=1&reason_id=1")
    assert matching.status_code == 200
    assert "FW-001" in matching.text

    for query in ("start_date=2026-10-02", "area_id=2", "category_id=2", "reason_id=2"):
        no_match = browser.get(f"/records?{query}")
        assert no_match.status_code == 200
        assert "No matching records" in no_match.text
        assert "FW-001" not in no_match.text

    bad_range = browser.get("/records?start_date=2026-10-02&end_date=2026-10-01")
    assert bad_range.status_code == 400
    assert "To date must be on or after From date" in bad_range.text

    bad_category = browser.get("/records?category_id=999")
    assert bad_category.status_code == 400
    assert "Select a valid category" in bad_category.text


def test_long_lists_are_split_into_pages_that_keep_filters(app_with_empty_records):
    app = app_with_empty_records
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    with database(app) as db:
        user_id = scalar(db, "SELECT id FROM users WHERE username = 'demo_entry'")
        for minutes in range(120):
            create_waste_record(db, event_at=start + timedelta(minutes=minutes), area_id=1,
                                category_id=1, reason_id=1, quantity_kg=1, user_id=user_id)
    browser = client(app)

    first = browser.get("/records?area_id=1").text
    assert "Showing 1–50 of 120 records" in first
    assert "Page 1 of 3" in first
    assert "FW-120" in first and "FW-070" not in first
    assert 'href="/records?area_id=1&amp;page=2"' in first

    last = browser.get("/records?area_id=1&page=3").text
    assert "Showing 101–120 of 120 records" in last
    assert "FW-001" in last and "FW-120" not in last
    assert "Older records" not in last

    assert "Page 3 of 3" in browser.get("/records?area_id=1&page=999").text
