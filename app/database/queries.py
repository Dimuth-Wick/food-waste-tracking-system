"""Small data access layer for the MVP's SQLite entities."""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
import sqlite3

from werkzeug.security import generate_password_hash


ROLES = {"entry", "manager", "admin"}


@dataclass(frozen=True)
class User:
    id: int
    name: str
    username: str
    password_hash: str
    role: str
    active: bool


@dataclass(frozen=True)
class LookupItem:
    id: int
    name: str
    active: bool


@dataclass(frozen=True)
class WasteRecord:
    id: int
    event_at: str
    area_id: int
    category_id: int
    reason_id: int
    quantity_kg: float
    user_id: int
    notes: str
    created_at: str
    updated_at: str


def create_user(db: sqlite3.Connection, *, name: str, username: str, password: str, role: str) -> User:
    if role not in ROLES:
        raise ValueError("Invalid user role")
    if not name.strip() or not username.strip() or not password:
        raise ValueError("Name, username, and password are required")
    with db:
        cursor = db.execute(
            "INSERT INTO users (name, username, password_hash, role) VALUES (?, ?, ?, ?)",
            (name.strip(), username.strip(), generate_password_hash(password), role),
        )
    return get_user(db, cursor.lastrowid)


def get_user(db: sqlite3.Connection, user_id: int) -> User | None:
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user_from_row(row) if row else None


def get_user_by_username(db: sqlite3.Connection, username: str) -> User | None:
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _user_from_row(row) if row else None


def _user_from_row(row: sqlite3.Row) -> User:
    data = dict(row)
    data["active"] = bool(data["active"])
    return User(**data)


def create_waste_record(
    db: sqlite3.Connection,
    *,
    event_at: datetime,
    area_id: int,
    category_id: int,
    reason_id: int,
    quantity_kg: float,
    user_id: int,
    notes: str = "",
) -> WasteRecord:
    if event_at.tzinfo is None or event_at.utcoffset() is None:
        raise ValueError("Event time must include a time zone")
    try:
        quantity = float(quantity_kg)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Quantity must be a positive number of kilograms") from exc
    if not isfinite(quantity) or quantity <= 0:
        raise ValueError("Quantity must be a positive finite number of kilograms")

    event_utc = event_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db:
        cursor = db.execute(
            """INSERT INTO waste_records
               (event_at, area_id, category_id, reason_id, quantity_kg, user_id, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event_utc, area_id, category_id, reason_id, quantity, user_id, notes.strip()),
        )
    return get_waste_record(db, cursor.lastrowid)


def get_waste_record(db: sqlite3.Connection, record_id: int) -> WasteRecord | None:
    if not 0 < record_id <= 2**63 - 1:
        return None
    row = db.execute("SELECT * FROM waste_records WHERE id = ?", (record_id,)).fetchone()
    return WasteRecord(**dict(row)) if row else None


def update_waste_record(
    db: sqlite3.Connection,
    record_id: int,
    *,
    event_at: datetime,
    area_id: int,
    category_id: int,
    reason_id: int,
    quantity_kg: float,
) -> WasteRecord | None:
    if event_at.tzinfo is None or event_at.utcoffset() is None:
        raise ValueError("Event time must include a time zone")
    try:
        quantity = float(quantity_kg)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Quantity must be a positive number of kilograms") from exc
    if not isfinite(quantity) or quantity <= 0:
        raise ValueError("Quantity must be a positive finite number of kilograms")

    event_utc = event_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with db:
        cursor = db.execute(
            """UPDATE waste_records
               SET event_at = ?, area_id = ?, category_id = ?, reason_id = ?,
                   quantity_kg = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE id = ?""",
            (event_utc, area_id, category_id, reason_id, quantity, record_id),
        )
    return get_waste_record(db, record_id) if cursor.rowcount else None


def list_lookup_items(db: sqlite3.Connection, table: str) -> list[LookupItem]:
    if table not in {"areas", "categories", "reasons"}:
        raise ValueError("Invalid lookup table")
    rows = db.execute(f"SELECT id, name, active FROM {table} ORDER BY name").fetchall()
    return [LookupItem(row["id"], row["name"], bool(row["active"])) for row in rows]


def list_waste_records(
    db: sqlite3.Connection,
    *,
    start_at_utc: str | None = None,
    end_before_utc: str | None = None,
    area_id: int | None = None,
    category_id: int | None = None,
    reason_id: int | None = None,
) -> list[dict]:
    conditions = []
    parameters = []
    for column, value, operator in (
        ("event_at", start_at_utc, ">="),
        ("event_at", end_before_utc, "<"),
        ("area_id", area_id, "="),
        ("category_id", category_id, "="),
        ("reason_id", reason_id, "="),
    ):
        if value is not None:
            conditions.append(f"w.{column} {operator} ?")
            parameters.append(value)

    where_clause = " AND ".join(conditions) if conditions else "1 = 1"
    rows = db.execute(
        f"""SELECT w.id, w.event_at, w.quantity_kg, w.user_id,
                   a.name AS area, c.name AS category, r.name AS reason,
                   u.name AS recorded_by
            FROM waste_records AS w
            JOIN areas AS a ON a.id = w.area_id
            JOIN categories AS c ON c.id = w.category_id
            JOIN reasons AS r ON r.id = w.reason_id
            JOIN users AS u ON u.id = w.user_id
            WHERE {where_clause}
            ORDER BY w.event_at DESC, w.id DESC""",
        parameters,
    ).fetchall()
    return [dict(row) for row in rows]
