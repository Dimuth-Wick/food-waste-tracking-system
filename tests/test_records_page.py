import pytest

from app import create_app
from app.database.connection import get_db, init_db
from app.database.queries import create_user


@pytest.fixture
def app_with_empty_records(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "records.sqlite3")})
    with app.app_context():
        init_db()
        db = get_db()
        for table, names in (
            ("areas", ["Main Kitchen", "Buffet"]),
            ("categories", ["Vegetables", "Bakery"]),
            ("reasons", ["Spoilage", "Plate Returns"]),
        ):
            for name in names:
                db.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))
        db.commit()
        create_user(
            db, name="Demo Kitchen Staff", username="demo_entry",
            password="test password", role="entry",
        )
    return app


def test_newly_created_record_appears_in_list(app_with_empty_records):
    app = app_with_empty_records
    client = app.test_client()

    empty = client.get("/records")
    assert empty.status_code == 200
    assert b"No waste records yet" in empty.data

    created = client.post("/records/new", data={
        "event_at": "2026-10-01T00:30",
        "area_id": "1",
        "category_id": "1",
        "reason_id": "1",
        "quantity_kg": "1.25",
    })
    assert created.status_code == 303

    page = client.get("/records")
    assert page.status_code == 200
    for expected in (
        b"FW-001", b"01 Oct 2026", b"00:30", b"Main Kitchen",
        b"Vegetables", b"Spoilage", b"Demo Kitchen Staff", b"1.25 kg",
    ):
        assert expected in page.data
    assert b"1 record" in page.data

    with app.app_context():
        row = get_db().execute("SELECT event_at FROM waste_records WHERE id = 1").fetchone()
        assert row["event_at"] == "2026-09-30T19:00:00Z"


def test_basic_filters_and_no_matches(app_with_empty_records):
    app = app_with_empty_records
    client = app.test_client()
    client.post("/records/new", data={
        "event_at": "2026-10-01T00:30", "area_id": "1", "category_id": "1",
        "reason_id": "1", "quantity_kg": "1.25",
    })

    matching = client.get("/records?start_date=2026-10-01&end_date=2026-10-01&area_id=1&category_id=1&reason_id=1")
    assert matching.status_code == 200
    assert b"FW-001" in matching.data

    for query in ("start_date=2026-10-02", "area_id=2", "category_id=2", "reason_id=2"):
        no_match = client.get(f"/records?{query}")
        assert no_match.status_code == 200
        assert b"No matching records" in no_match.data
        assert b"FW-001" not in no_match.data

    bad_range = client.get("/records?start_date=2026-10-02&end_date=2026-10-01")
    assert bad_range.status_code == 400
    assert b"To date must be on or after From date" in bad_range.data

    bad_category = client.get("/records?category_id=999")
    assert bad_category.status_code == 400
    assert b"Select a valid category" in bad_category.data
