import pytest

from app import create_app
from app.db import get_db, init_db
from app.models import get_user_by_username
from app.seed import seed_demo_data


@pytest.fixture
def app_with_demo(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3")})
    with app.app_context():
        init_db()
        seed_demo_data(get_db())
    return app


def valid_form(app):
    with app.app_context():
        db = get_db()
        return {
            "event_at": "2026-10-01T12:30",
            "area_id": str(db.execute("SELECT id FROM areas WHERE name = 'Buffet'").fetchone()[0]),
            "category_id": str(db.execute("SELECT id FROM categories WHERE name = 'Vegetables'").fetchone()[0]),
            "reason_id": str(db.execute("SELECT id FROM reasons WHERE name = 'Spoilage'").fetchone()[0]),
            "quantity_kg": "2.75",
        }


def test_valid_submission_is_saved_and_success_is_shown(app_with_demo):
    app = app_with_demo
    form = valid_form(app)
    response = app.test_client().post("/records/new", data=form)

    assert response.status_code == 303
    assert "/records/new?created=" in response.headers["Location"]
    success = app.test_client().get(response.headers["Location"])
    assert success.status_code == 200
    assert b"saved successfully" in success.data

    with app.app_context():
        db = get_db()
        row = db.execute("SELECT * FROM waste_records ORDER BY id DESC LIMIT 1").fetchone()
        assert row["event_at"] == "2026-10-01T07:00:00Z"
        assert row["quantity_kg"] == 2.75
        assert row["notes"] == ""
        assert row["user_id"] == get_user_by_username(db, "demo_entry").id
        assert row["area_id"] == int(form["area_id"])


def test_invalid_entries_show_field_errors_and_save_nothing(app_with_demo):
    app = app_with_demo
    client = app.test_client()
    with app.app_context():
        initial_count = get_db().execute("SELECT COUNT(*) FROM waste_records").fetchone()[0]

    missing = client.post("/records/new", data={})
    assert missing.status_code == 400
    assert b"Enter the date and time" in missing.data
    assert b"Select a source area" in missing.data
    assert b"Enter the quantity in kilograms" in missing.data

    bad_form = valid_form(app)
    bad_form.update(event_at="invalid", category_id="9999", quantity_kg="-2")
    invalid = client.post("/records/new", data=bad_form)
    assert invalid.status_code == 400
    assert b"valid local date and time" in invalid.data
    assert b"valid food category" in invalid.data
    assert b"greater than zero" in invalid.data
    assert b'aria-invalid="true"' in invalid.data

    bad_time = valid_form(app)
    bad_time["event_at"] = "2026-10-01"
    assert b"valid local date and time" in client.post("/records/new", data=bad_time).data

    inactive_form = valid_form(app)
    with app.app_context():
        db = get_db()
        db.execute("UPDATE categories SET active = 0 WHERE id = ?", (int(inactive_form["category_id"]),))
        db.commit()
    inactive = client.post("/records/new", data=inactive_form)
    assert inactive.status_code == 400
    assert b"Select a valid food category" in inactive.data

    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM waste_records").fetchone()[0] == initial_count


def test_missing_demo_entry_user_is_reported(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "empty.sqlite3")})
    with app.app_context():
        init_db()
    response = app.test_client().get("/records/new")
    assert response.status_code == 503
    assert b"Initialize and seed the local database first" in response.data
    assert b'type="submit" disabled' in response.data
