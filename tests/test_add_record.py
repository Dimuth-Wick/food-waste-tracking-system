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
            "reason_id": str(scalar(db, "SELECT id FROM reasons WHERE name = 'Spoilage'")),
            "quantity_kg": "2.75",
        }


def test_add_panel_opens_over_the_overview(app_with_demo):
    page = client(app_with_demo).get("/records/new")
    assert page.status_code == 200
    html = page.text
    assert "<h1>Waste overview</h1>" in html           # the page behind the panel
    assert '<dialog class="record-panel"' in html
    assert "Add waste record" in html
    assert "Demo Kitchen Staff" in html
    assert "Total recorded" in html                    # totals are still visible behind it
    assert 'href="/"' in html                          # Cancel goes back to the overview


def test_valid_submission_is_saved_and_returns_to_overview(app_with_demo):
    app = app_with_demo
    form = valid_form(app)
    response = client(app).post("/records/new", data=form)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/?created=")
    page = client(app).get(response.headers["location"])
    assert page.status_code == 200
    assert "saved successfully" in page.text
    assert 'class="is-new"' in page.text               # the new row is highlighted
    assert "<dialog" not in page.text                  # the panel is closed again

    with database(app) as db:
        row = sql(db, "SELECT * FROM waste_records ORDER BY id DESC LIMIT 1").mappings().one()
        assert row["event_at"] == "2026-10-01T07:00:00Z"
        assert row["quantity_kg"] == 2.75
        assert row["notes"] == ""
        assert row["user_id"] == get_user_by_username(db, "demo_entry").id
        assert row["area_id"] == int(form["area_id"])


def test_saving_keeps_the_filters_the_user_was_looking_at(app_with_demo):
    app = app_with_demo
    saved = client(app).post("/records/new?area_id=1&show=25", data=valid_form(app))
    assert saved.status_code == 303
    assert saved.headers["location"].startswith("/?area_id=1&created=")
    assert "show=" not in saved.headers["location"]    # the new record is at the top of the list
    panel = client(app).get("/records/new?area_id=1&show=25").text
    assert 'href="/?area_id=1&amp;show=25"' in panel    # Cancel returns to the same view


def test_invalid_entries_show_field_errors_in_the_panel_and_save_nothing(app_with_demo):
    app = app_with_demo
    browser = client(app)
    with database(app) as db:
        initial_count = scalar(db, "SELECT COUNT(*) FROM waste_records")

    missing = browser.post("/records/new", data={})
    assert missing.status_code == 400
    assert '<dialog class="record-panel"' in missing.text   # the panel stays open
    assert "Enter the date and time" in missing.text
    assert "Select a source area" in missing.text
    assert "Enter the quantity in kilograms" in missing.text

    bad_form = valid_form(app)
    bad_form.update(event_at="invalid", reason_id="9999", quantity_kg="-2")
    invalid = browser.post("/records/new", data=bad_form)
    assert invalid.status_code == 400
    assert "valid local date and time" in invalid.text
    assert "valid reason for waste" in invalid.text
    assert "greater than zero" in invalid.text
    assert 'aria-invalid="true"' in invalid.text
    assert 'value="-2"' in invalid.text                      # what was typed is kept

    bad_time = valid_form(app)
    bad_time["event_at"] = "2026-10-01"
    assert "valid local date and time" in browser.post("/records/new", data=bad_time).text

    inactive_form = valid_form(app)
    with database(app) as db:
        sql(db, "UPDATE reasons SET active = 0 WHERE id = :id", id=int(inactive_form["reason_id"]))
        db.commit()
    inactive = browser.post("/records/new", data=inactive_form)
    assert inactive.status_code == 400
    assert "Select a valid reason for waste" in inactive.text

    with database(app) as db:
        assert scalar(db, "SELECT COUNT(*) FROM waste_records") == initial_count


def test_missing_demo_entry_user_is_reported(tmp_path):
    app = make_app(tmp_path, "empty.sqlite3")
    response = client(app).get("/records/new")
    assert response.status_code == 503
    assert "Initialize and seed the local database first" in response.text
    assert 'type="submit" disabled' in response.text
