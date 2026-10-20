"""Synthetic data for local development, never real hotel records."""

from datetime import datetime, timedelta, timezone
import secrets
import sqlite3

from werkzeug.security import generate_password_hash


def seed_demo_data(db: sqlite3.Connection) -> dict[str, str]:
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] or db.execute(
        "SELECT COUNT(*) FROM waste_records"
    ).fetchone()[0]:
        raise ValueError("Demo seed requires a database without users or waste records")

    values = {
        "areas": ["Main Kitchen", "Buffet", "Banquet"],
        "categories": ["Vegetables", "Prepared Food", "Bakery", "Meat & Seafood"],
        "reasons": ["Preparation Trimmings", "Spoilage", "Plate Returns", "Overproduction"],
    }
    credentials = {}
    with db:
        for table, names in values.items():
            for name in names:
                db.execute(f"INSERT OR IGNORE INTO {table} (name) VALUES (?)", (name,))

        for username, name, role in [
            ("demo_entry", "Demo Kitchen Staff", "entry"),
            ("demo_manager", "Demo Supervisor", "manager"),
            ("demo_admin", "Demo Administrator", "admin"),
        ]:
            password = secrets.token_urlsafe(12)
            credentials[username] = password
            db.execute(
                "INSERT INTO users (name, username, password_hash, role) VALUES (?, ?, ?, ?)",
                (name, username, generate_password_hash(password), role),
            )

        user_id = db.execute("SELECT id FROM users WHERE username = 'demo_entry'").fetchone()[0]
        now = datetime.now(timezone.utc)
        samples = [
            (1, "Main Kitchen", "Vegetables", "Preparation Trimmings", 2.4, "Synthetic preparation waste"),
            (2, "Buffet", "Prepared Food", "Overproduction", 5.1, "Synthetic buffet surplus"),
            (3, "Banquet", "Bakery", "Plate Returns", 1.2, "Synthetic plate returns"),
        ]
        for days_ago, area, category, reason, quantity, notes in samples:
            event_at = (now - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
            db.execute(
                """INSERT INTO waste_records
                   (event_at, area_id, category_id, reason_id, quantity_kg, user_id, notes)
                   VALUES (
                       ?,
                       (SELECT id FROM areas WHERE name = ?),
                       (SELECT id FROM categories WHERE name = ?),
                       (SELECT id FROM reasons WHERE name = ?),
                       ?, ?, ?
                   )""",
                (event_at, area, category, reason, quantity, user_id, notes),
            )
    return credentials
