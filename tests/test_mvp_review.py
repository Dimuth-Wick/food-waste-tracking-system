"""Exercise the current MVP flow with a persistent, isolated SQLite database."""

from datetime import datetime

from app import create_app
from app.db import get_db, init_db
from app.entry import DEMO_TIMEZONE
from app.models import create_user, get_waste_record


def _review_app(database_path):
    return create_app({"TESTING": True, "DATABASE": str(database_path)})


def _prepare_database(app):
    with app.app_context():
        init_db()
        db = get_db()
        for table, name in (
            ("areas", "Buffet"),
            ("categories", "Vegetables"),
            ("reasons", "Spoilage"),
        ):
            db.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))
        db.commit()
        create_user(db, name="Demo Kitchen Staff", username="demo_entry",
                    password="temporary test password", role="entry")


def _form(quantity="2.5"):
    return {
        "event_at": "2026-10-02T12:30",
        "area_id": "1",
        "category_id": "1",
        "reason_id": "1",
        "quantity_kg": quantity,
    }


def test_complete_record_flow_persists_after_reopening_app(tmp_path, monkeypatch):
    monkeypatch.setattr("app.dashboard._now_local",
                        lambda: datetime(2026, 10, 2, 15, tzinfo=DEMO_TIMEZONE))
    database_path = tmp_path / "review.sqlite3"
    app = _review_app(database_path)
    _prepare_database(app)
    client = app.test_client()

    assert client.get("/").status_code == 200
    assert b"Add waste record" in client.get("/").data
    assert client.get("/records/new").status_code == 200

    saved = client.post("/records/new", data=_form())
    assert saved.status_code == 303
    assert b"saved successfully" in client.get(saved.headers["Location"]).data
    listing = client.get("/records")
    assert b"FW-001" in listing.data
    assert b"2.5 kg" in listing.data
    assert b"/records/1/edit" in listing.data
    dashboard = client.get("/").get_data(as_text=True)
    assert "2.50" in dashboard
    assert "Buffet: 2.50 kilograms" in dashboard

    edit_form = client.get("/records/1/edit")
    assert edit_form.status_code == 200
    assert b'value="2.5"' in edit_form.data
    changed = _form("4")
    updated = client.post("/records/1/edit", data=changed)
    assert updated.status_code == 303
    assert b"updated successfully" in client.get(updated.headers["Location"]).data
    assert b"4 kg" in client.get("/records").data
    assert "4.00" in client.get("/").get_data(as_text=True)

    invalid = client.post("/records/1/edit", data=_form("0"))
    assert invalid.status_code == 400
    assert b"greater than zero" in invalid.data
    assert b"4 kg" in client.get("/records").data
    assert client.post("/records/new", data={}).status_code == 400

    reopened = _review_app(database_path).test_client()
    assert b"FW-001" in reopened.get("/records").data
    assert "4.00" in reopened.get("/").get_data(as_text=True)
    with app.app_context():
        record = get_waste_record(get_db(), 1)
        assert record.quantity_kg == 4
        assert record.event_at == "2026-10-02T07:00:00Z"


def test_oversized_identifiers_return_validation_errors(tmp_path):
    app = _review_app(tmp_path / "ids.sqlite3")
    _prepare_database(app)
    client = app.test_client()
    too_long = "9" * 5000

    bad_form = _form()
    bad_form["area_id"] = too_long
    response = client.post("/records/new", data=bad_form)
    assert response.status_code == 400
    assert b"Select a valid source area" in response.data

    filtered = client.get("/records?category_id=" + too_long)
    assert filtered.status_code == 400
    assert b"Select a valid category" in filtered.data

    dashboard = client.get("/?reason_id=" + too_long)
    assert dashboard.status_code == 400
    assert b"Select a valid reason" in dashboard.data

    assert client.get("/records/new?created=" + too_long).status_code == 200
    assert client.get("/records/99999999999999999999/edit").status_code == 404


def test_uninitialized_database_shows_service_error_instead_of_crashing(tmp_path):
    app = _review_app(tmp_path / "not_initialized.sqlite3")
    client = app.test_client()
    for path in ("/", "/records", "/records/new", "/records/1/edit"):
        response = client.get(path)
        assert response.status_code == 503
        assert b"Traceback" not in response.data
