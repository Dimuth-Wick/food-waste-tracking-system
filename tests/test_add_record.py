import pytest

from app.database.queries import get_user_by_username
from app.database.seed import seed_demo_data
from conftest import client, database, make_app, scalar, sql


@pytest.fixture
def app_with_demo(tmp_path):
    app = make_app(tmp_path)
    with database(app) as db:
        seed_demo_data(db)
    return app


def valid_form(app):
    with database(app) as db:
        return {
            "event_at": "2026-10-01T12:30",
            "area_id": str(scalar(db, "SELECT id FROM areas WHERE name = 'Buffet'")),
            "category_id": str(scalar(db, "SELECT id FROM categories WHERE name = 'Vegetables'")),
            "reason_id": str(scalar(db, "SELECT id FROM reasons WHERE name = 'Spoilage'")),
            "quantity_kg": "2.75",
        }


def test_valid_submission_is_saved_and_success_is_shown(app_with_demo):
    app = app_with_demo
    form = valid_form(app)
    response = client(app).post("/records/new", data=form)

    assert response.status_code == 303
    assert "/records/new?created=" in response.headers["location"]
    success = client(app).get(response.headers["location"])
    assert success.status_code == 200
    assert "saved successfully" in success.text

    with database(app) as db:
        row = sql(db, "SELECT * FROM waste_records ORDER BY id DESC LIMIT 1").mappings().one()
        assert row["event_at"] == "2026-10-01T07:00:00Z"
        assert row["quantity_kg"] == 2.75
        assert row["notes"] == ""
        assert row["user_id"] == get_user_by_username(db, "demo_entry").id
        assert row["area_id"] == int(form["area_id"])


def test_invalid_entries_show_field_errors_and_save_nothing(app_with_demo):
    app = app_with_demo
    browser = client(app)
    with database(app) as db:
        initial_count = scalar(db, "SELECT COUNT(*) FROM waste_records")

    missing = browser.post("/records/new", data={})
    assert missing.status_code == 400
    assert "Enter the date and time" in missing.text
    assert "Select a source area" in missing.text
    assert "Enter the quantity in kilograms" in missing.text

    bad_form = valid_form(app)
    bad_form.update(event_at="invalid", category_id="9999", quantity_kg="-2")
    invalid = browser.post("/records/new", data=bad_form)
    assert invalid.status_code == 400
    assert "valid local date and time" in invalid.text
    assert "valid food category" in invalid.text
    assert "greater than zero" in invalid.text
    assert 'aria-invalid="true"' in invalid.text

    bad_time = valid_form(app)
    bad_time["event_at"] = "2026-10-01"
    assert "valid local date and time" in browser.post("/records/new", data=bad_time).text

    inactive_form = valid_form(app)
    with database(app) as db:
        sql(db, "UPDATE categories SET active = 0 WHERE id = :id", id=int(inactive_form["category_id"]))
        db.commit()
    inactive = browser.post("/records/new", data=inactive_form)
    assert inactive.status_code == 400
    assert "Select a valid food category" in inactive.text

    with database(app) as db:
        assert scalar(db, "SELECT COUNT(*) FROM waste_records") == initial_count


def test_missing_demo_entry_user_is_reported(tmp_path):
    app = make_app(tmp_path, "empty.sqlite3")
    response = client(app).get("/records/new")
    assert response.status_code == 503
    assert "Initialize and seed the local database first" in response.text
    assert 'type="submit" disabled' in response.text
