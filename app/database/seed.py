"""Synthetic data for local development, never real hotel records."""

from datetime import datetime, timedelta, timezone
import secrets

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database.queries import create_user, create_waste_record
from app.database.tables import LOOKUP_TABLES, UserRow, WasteRecordRow


LOOKUP_NAMES = {
    "areas": ["Main Kitchen", "Buffet", "Banquet"],
    "reasons": ["Preparation Trimmings", "Spoilage", "Plate Returns", "Overproduction", "Ran out (shortage)"],
}
DEMO_USERS = [
    ("demo_entry", "Demo Kitchen Staff", "entry"),
    ("demo_manager", "Demo Supervisor", "manager"),
    ("demo_admin", "Demo Administrator", "admin"),
]
SAMPLES = [
    (1, "Main Kitchen", "Preparation Trimmings", 2.4, "Synthetic preparation waste"),
    (2, "Buffet", "Overproduction", 5.1, "Synthetic buffet surplus"),
    (3, "Banquet", "Plate Returns", 1.2, "Synthetic plate returns"),
]


def seed_demo_data(db: Session) -> dict[str, str]:
    """Add demo lookups, users and three records. Returns one-time passwords."""
    if db.scalar(select(func.count(UserRow.id))) or db.scalar(select(func.count(WasteRecordRow.id))):
        raise ValueError("Demo seed requires a database without users or waste records")

    ids = {}
    for table, names in LOOKUP_NAMES.items():
        model = LOOKUP_TABLES[table]
        existing = {row.name: row.id for row in db.scalars(select(model))}
        for name in names:
            if name not in existing:
                row = model(name=name, active=1)
                db.add(row)
                db.flush()
                existing[name] = row.id
        ids[table] = existing
    db.commit()

    credentials = {}
    users = {}
    for username, name, role in DEMO_USERS:
        credentials[username] = secrets.token_urlsafe(12)
        users[username] = create_user(db, name=name, username=username,
                                      password=credentials[username], role=role)

    now = datetime.now(timezone.utc)
    for days_ago, area, reason, quantity, notes in SAMPLES:
        create_waste_record(
            db, event_at=(now - timedelta(days=days_ago)).replace(microsecond=0),
            area_id=ids["areas"][area],
            reason_id=ids["reasons"][reason], quantity_kg=quantity,
            user_id=users["demo_entry"].id, notes=notes,
        )
    return credentials

