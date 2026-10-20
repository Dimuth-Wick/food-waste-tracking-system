from datetime import datetime, timezone

import pytest

from app.database.queries import create_user, create_waste_record, get_waste_record
from app.database.seed import seed_demo_data
from conftest import client, database, make_app, scalar, sql


@pytest.fixture
def app_with_demo(tmp_path):
    app = make_app(tmp_path, "edit.sqlite3")
    with database(app) as db:
        seed_demo_data(db)
    return app


def form_for(app, *, quantity="3.5"):
    with database(app) as db:
        return {
            "event_at": "2026-10-02T15:45",
            "area_id": str(scalar(db, "SELECT id FROM areas WHERE name = 'Buffet'")),
            "category_id": str(scalar(db, "SELECT id FROM categories WHERE name = 'Vegetables'")),
            "reason_id": str(scalar(db, "SELECT id FROM reasons WHERE name = 'Spoilage'")),
            "quantity_kg": quantity,
        }


def test_edit_prefills_and_persists_changes(app_with_demo):
    app = app_with_demo
    browser = client(app)
    assert browser.post("/records/new", data=form_for(app)).status_code == 303
    with database(app) as db:
        record_id = scalar(db, "SELECT MAX(id) FROM waste_records")
        original = get_waste_record(db, record_id)
        sql(db, "UPDATE waste_records SET updated_at = '2020-01-01T00:00:00.000Z' WHERE id = :id", id=record_id)
        db.commit()

    assert f"/records/{record_id}/edit" in browser.get("/").text   # the Edit link is in the table
    edit_page = browser.get(f"/records/{record_id}/edit")
    assert edit_page.status_code == 200
    assert "Edit waste record" in edit_page.text
    assert '<dialog class="record-panel"' in edit_page.text
    assert 'value="2026-10-02T15:45"' in edit_page.text
    assert 'value="3.5"' in edit_page.text

    changed = form_for(app, quantity="4.25")
    changed["event_at"] = "2026-10-03T09:00"
    response = browser.post(f"/records/{record_id}/edit", data=changed)
    assert response.status_code == 303
    assert response.headers["location"] == f"/?updated={record_id}"
    after = browser.get(response.headers["location"]).text
    assert "updated successfully" in after
    assert "4.25 kg" in after
    with database(app) as db:
        saved = get_waste_record(db, record_id)
        assert saved.quantity_kg == 4.25
        assert saved.event_at == "2026-10-03T03:30:00Z"
        assert saved.user_id == original.user_id
        assert saved.created_at == original.created_at
        assert saved.updated_at != "2020-01-01T00:00:00.000Z"


def test_invalid_edit_does_not_change_record(app_with_demo):
    app = app_with_demo
    with database(app) as db:
        record_id = scalar(db, "SELECT id FROM waste_records WHERE user_id = "
                               "(SELECT id FROM users WHERE username = 'demo_entry') LIMIT 1")
        before = get_waste_record(db, record_id)
    invalid = form_for(app, quantity="-1")
    invalid["category_id"] = "99999"
    response = client(app).post(f"/records/{record_id}/edit", data=invalid)
    assert response.status_code == 400
    assert "greater than zero" in response.text
    assert "valid food category" in response.text
    assert '<dialog class="record-panel"' in response.text
    with database(app) as db:
        assert get_waste_record(db, record_id) == before


def test_only_owner_can_edit_in_demo(app_with_demo):
    app = app_with_demo
    with database(app) as db:
        other = create_user(db, name="Other user", username="other", password="test", role="entry")
        record = create_waste_record(
            db, event_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            area_id=scalar(db, "SELECT id FROM areas LIMIT 1"),
            category_id=scalar(db, "SELECT id FROM categories LIMIT 1"),
            reason_id=scalar(db, "SELECT id FROM reasons LIMIT 1"),
            quantity_kg=1, user_id=other.id,
        )
    browser = client(app)
    forbidden = browser.get(f"/records/{record.id}/edit")
    assert forbidden.status_code == 403
    assert "can only edit records they created" in forbidden.text
    assert browser.post(f"/records/{record.id}/edit", data=form_for(app)).status_code == 403
    assert f"/records/{record.id}/edit" not in browser.get("/").text
    with database(app) as db:
        assert get_waste_record(db, record.id) == record
    missing = browser.get("/records/999999/edit")
    assert missing.status_code == 404
    assert "Page not found" in missing.text
