import pytest

from app import create_app
from app.database.connection import get_db, init_db
from app.database.queries import create_user, create_waste_record, get_waste_record
from app.database.seed import seed_demo_data
from datetime import datetime, timezone


@pytest.fixture
def app_with_demo(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "edit.sqlite3")})
    with app.app_context():
        init_db()
        seed_demo_data(get_db())
    return app


def form_for(app, *, quantity="3.5"):
    with app.app_context():
        db = get_db()
        return {
            "event_at": "2026-10-02T15:45",
            "area_id": str(db.execute("SELECT id FROM areas WHERE name = 'Buffet'").fetchone()[0]),
            "category_id": str(db.execute("SELECT id FROM categories WHERE name = 'Vegetables'").fetchone()[0]),
            "reason_id": str(db.execute("SELECT id FROM reasons WHERE name = 'Spoilage'").fetchone()[0]),
            "quantity_kg": quantity,
        }


def test_edit_prefills_and_persists_changes(app_with_demo):
    app = app_with_demo
    client = app.test_client()
    created = client.post("/records/new", data=form_for(app))
    assert created.status_code == 303
    with app.app_context():
        db = get_db()
        record_id = db.execute("SELECT MAX(id) FROM waste_records").fetchone()[0]
        original = get_waste_record(db, record_id)
        db.execute("UPDATE waste_records SET updated_at = '2020-01-01T00:00:00.000Z' WHERE id = ?", (record_id,))
        db.commit()

    listing = client.get("/records")
    assert f"/records/{record_id}/edit".encode() in listing.data
    edit_page = client.get(f"/records/{record_id}/edit")
    assert edit_page.status_code == 200
    assert b'Edit waste record' in edit_page.data
    assert b'value="2026-10-02T15:45"' in edit_page.data
    assert b'value="3.5"' in edit_page.data

    changed = form_for(app, quantity="4.25")
    changed["event_at"] = "2026-10-03T09:00"
    response = client.post(f"/records/{record_id}/edit", data=changed)
    assert response.status_code == 303
    assert b"updated successfully" in client.get(response.headers["Location"]).data
    with app.app_context():
        saved = get_waste_record(get_db(), record_id)
        assert saved.quantity_kg == 4.25
        assert saved.event_at == "2026-10-03T03:30:00Z"
        assert saved.user_id == original.user_id
        assert saved.created_at == original.created_at
        assert saved.updated_at != "2020-01-01T00:00:00.000Z"
    assert b"4.25 kg" in client.get("/records").data


def test_invalid_edit_does_not_change_record(app_with_demo):
    app = app_with_demo
    with app.app_context():
        db = get_db()
        record_id = db.execute("SELECT id FROM waste_records WHERE user_id = (SELECT id FROM users WHERE username = 'demo_entry') LIMIT 1").fetchone()[0]
        before = get_waste_record(db, record_id)
    invalid = form_for(app, quantity="-1")
    invalid["category_id"] = "99999"
    response = app.test_client().post(f"/records/{record_id}/edit", data=invalid)
    assert response.status_code == 400
    assert b"greater than zero" in response.data
    assert b"valid food category" in response.data
    with app.app_context():
        assert get_waste_record(get_db(), record_id) == before


def test_only_owner_can_edit_in_demo(app_with_demo):
    app = app_with_demo
    with app.app_context():
        db = get_db()
        other = create_user(db, name="Other user", username="other", password="test", role="entry")
        area_id = db.execute("SELECT id FROM areas LIMIT 1").fetchone()[0]
        category_id = db.execute("SELECT id FROM categories LIMIT 1").fetchone()[0]
        reason_id = db.execute("SELECT id FROM reasons LIMIT 1").fetchone()[0]
        record = create_waste_record(
            db, event_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
            area_id=area_id, category_id=category_id, reason_id=reason_id,
            quantity_kg=1, user_id=other.id,
        )
    client = app.test_client()
    assert client.get(f"/records/{record.id}/edit").status_code == 403
    assert client.post(f"/records/{record.id}/edit", data=form_for(app)).status_code == 403
    assert f"/records/{record.id}/edit".encode() not in client.get("/records").data
    with app.app_context():
        assert get_waste_record(get_db(), record.id) == record
    assert client.get("/records/999999/edit").status_code == 404
