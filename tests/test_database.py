from datetime import datetime, timedelta, timezone
import sqlite3

import pytest
from werkzeug.security import check_password_hash

from app import create_app
from app.db import get_db, init_db
from app.models import (
    create_user,
    create_waste_record,
    get_user_by_username,
    get_waste_record,
    list_lookup_items,
)
from app.seed import seed_demo_data


@pytest.fixture
def database(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3")})
    with app.app_context():
        init_db()
        yield get_db()


def test_record_round_trip_and_constraints(database):
    db = database
    for table, name in [
        ("areas", "Kitchen"),
        ("categories", "Vegetables"),
        ("reasons", "Spoilage"),
    ]:
        db.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))
    db.commit()

    user = create_user(db, name="Kitchen Staff", username="staff", password="test secret", role="entry")
    assert get_user_by_username(db, "staff") == user
    assert user.password_hash != "test secret"
    assert check_password_hash(user.password_hash, "test secret")

    local_time = datetime(2026, 10, 1, 12, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    record = create_waste_record(
        db,
        event_at=local_time,
        area_id=1,
        category_id=1,
        reason_id=1,
        quantity_kg=2.5,
        user_id=user.id,
        notes="  Prep waste  ",
    )
    assert get_waste_record(db, record.id) == record
    assert record.event_at == "2026-10-01T07:00:00Z"
    assert record.notes == "Prep waste"
    assert record.created_at and record.updated_at

    with pytest.raises(ValueError, match="positive"):
        create_waste_record(
            db, event_at=local_time, area_id=1, category_id=1, reason_id=1,
            quantity_kg=0, user_id=user.id,
        )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        create_waste_record(
            db, event_at=local_time, area_id=999, category_id=1, reason_id=1,
            quantity_kg=1, user_id=user.id,
        )
    assert db.execute("SELECT COUNT(*) FROM waste_records").fetchone()[0] == 1


def test_seeded_data_can_be_retrieved(database):
    db = database
    credentials = seed_demo_data(db)
    assert set(credentials) == {"demo_entry", "demo_manager", "demo_admin"}
    assert get_user_by_username(db, "demo_manager").role == "manager"
    assert len(list_lookup_items(db, "areas")) == 3
    assert db.execute("SELECT COUNT(*) FROM waste_records").fetchone()[0] == 3
    assert db.execute("SELECT SUM(quantity_kg) FROM waste_records").fetchone()[0] == pytest.approx(8.7)
    with pytest.raises(ValueError, match="without users"):
        seed_demo_data(db)
