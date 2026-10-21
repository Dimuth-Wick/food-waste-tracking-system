"""Exercise the current MVP flow with a persistent, isolated SQLite database."""

from datetime import datetime

from app.database.queries import create_user, get_waste_record
from app.waste_records.common import DEMO_TIMEZONE
from conftest import add_lookups, client, database, make_app


def _prepare_database(app):
    with database(app) as db:
        add_lookups(db, {"areas": ["Buffet"], "categories": ["Vegetables"], "reasons": ["Spoilage"]})
        create_user(db, name="Demo Kitchen Staff", username="demo_entry",
                    password="temporary test password", role="entry")


def _form(quantity="2.5"):
    return {"event_at": "2026-10-02T12:30", "area_id": "1", "category_id": "1",
            "reason_id": "1", "quantity_kg": quantity}


def test_complete_record_flow_persists_after_reopening_app(tmp_path, monkeypatch):
    monkeypatch.setattr("app.waste_records.overview._now_local",
                        lambda: datetime(2026, 10, 2, 15, tzinfo=DEMO_TIMEZONE))
    app = make_app(tmp_path, "review.sqlite3")
    _prepare_database(app)
    browser = client(app)

    assert browser.get("/").status_code == 200
    assert "Add waste record" in browser.get("/").text
    assert browser.get("/records/new").status_code == 200
    assert browser.get("/records").status_code == 308   # old address redirects to the overview

    saved = browser.post("/records/new", data=_form())
    assert saved.status_code == 303
    assert "saved successfully" in browser.get(saved.headers["location"]).text
    overview = browser.get("/").text
    assert "02 Oct 2026" in overview                       # one row for the day
    day = browser.get("/days/2026-10-02").text
    assert "FW-001" in day and "2.5 kg" in day and "/records/1/edit" in day
    assert "2.50" in overview
    assert "Buffet: 2.50 kilograms" in overview

    edit_form = browser.get("/records/1/edit")
    assert edit_form.status_code == 200
    assert 'value="2.5"' in edit_form.text
    updated = browser.post("/records/1/edit", data=_form("4"))
    assert updated.status_code == 303
    assert "updated successfully" in browser.get(updated.headers["location"]).text
    assert "4 kg" in browser.get("/days/2026-10-02").text
    assert "4.00" in browser.get("/").text

    invalid = browser.post("/records/1/edit", data=_form("0"))
    assert invalid.status_code == 400
    assert "greater than zero" in invalid.text
    assert "4 kg" in browser.get("/days/2026-10-02").text
    assert browser.post("/records/new", data={}).status_code == 400

    reopened = client(make_app(tmp_path, "review.sqlite3", initialize=False))
    assert "FW-001" in reopened.get("/days/2026-10-02").text
    assert "4.00" in reopened.get("/").text
    with database(app) as db:
        record = get_waste_record(db, 1)
        assert record.quantity_kg == 4
        assert record.event_at == "2026-10-02T07:00:00Z"


def test_oversized_identifiers_return_validation_errors(tmp_path):
    app = make_app(tmp_path, "ids.sqlite3")
    _prepare_database(app)
    browser = client(app)
    too_long = "9" * 5000

    bad_form = _form()
    bad_form["area_id"] = too_long
    response = browser.post("/records/new", data=bad_form)
    assert response.status_code == 400
    assert "Select a valid source area" in response.text

    filtered = browser.get("/?area_id=" + too_long)
    assert filtered.status_code == 400
    assert "Select a valid area" in filtered.text

    overview = browser.get("/?reason_id=" + too_long)
    assert overview.status_code == 400
    assert "Select a valid reason" in overview.text

    assert browser.get("/records/new?created=" + too_long).status_code == 200
    assert browser.get("/records/99999999999999999999/edit").status_code == 404


def test_uninitialized_database_shows_service_error_instead_of_crashing(tmp_path):
    browser = client(make_app(tmp_path, "not_initialized.sqlite3", initialize=False))
    for path in ("/", "/records/new", "/records/1/edit"):
        response = browser.get(path)
        assert response.status_code == 503
        assert "Traceback" not in response.text
