from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash

from app.database.connection import init_db
from app.database.queries import (
    create_user,
    create_waste_record,
    get_user_by_username,
    get_waste_record,
    list_lookup_items,
)
from app.database.seed import seed_demo_data
from conftest import add_lookups, database, make_app, scalar


@pytest.fixture
def db(tmp_path):
    with database(make_app(tmp_path)) as session:
        yield session


def test_record_round_trip_and_constraints(db):
    add_lookups(db, {"areas": ["Kitchen"], "categories": ["Vegetables"], "reasons": ["Spoilage"]})

    user = create_user(db, name="Kitchen Staff", username="staff", password="test secret", role="entry")
    assert get_user_by_username(db, "staff") == user
    assert user.password_hash != "test secret"
    assert check_password_hash(user.password_hash, "test secret")

    local_time = datetime(2026, 10, 1, 12, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    record = create_waste_record(
        db, event_at=local_time, area_id=1, category_id=1, reason_id=1,
        quantity_kg=2.5, user_id=user.id, notes="  Prep waste  ",
    )
    assert get_waste_record(db, record.id) == record
    assert record.event_at == "2026-10-01T07:00:00Z"
    assert record.notes == "Prep waste"
    assert record.created_at and record.updated_at

    with pytest.raises(ValueError, match="positive"):
        create_waste_record(db, event_at=local_time, area_id=1, category_id=1, reason_id=1,
                            quantity_kg=0, user_id=user.id)
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        create_waste_record(db, event_at=local_time, area_id=999, category_id=1, reason_id=1,
                            quantity_kg=1, user_id=user.id)
    assert scalar(db, "SELECT COUNT(*) FROM waste_records") == 1


def test_seeded_data_can_be_retrieved(db):
    credentials = seed_demo_data(db)
    assert set(credentials) == {"demo_entry", "demo_manager", "demo_admin"}
    assert get_user_by_username(db, "demo_manager").role == "manager"
    assert len(list_lookup_items(db, "areas")) == 3
    assert scalar(db, "SELECT COUNT(*) FROM waste_records") == 3
    assert scalar(db, "SELECT SUM(quantity_kg) FROM waste_records") == pytest.approx(8.7)
    with pytest.raises(ValueError, match="without users"):
        seed_demo_data(db)


def test_init_db_is_safe_to_run_twice_and_keeps_data(tmp_path):
    app = make_app(tmp_path)
    with database(app) as db:
        seed_demo_data(db)
    init_db(app.state.engine)
    with database(app) as db:
        assert scalar(db, "SELECT COUNT(*) FROM waste_records") == 3
