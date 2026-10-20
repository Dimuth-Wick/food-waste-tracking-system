"""Reading and writing waste data. Views call these functions, never SQL directly.

Results are returned as small frozen dataclasses or plain dicts, so callers do
not depend on SQLAlchemy objects.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app.database.tables import (
    LOOKUP_TABLES,
    AreaRow,
    CategoryRow,
    ReasonRow,
    UserRow,
    WasteRecordRow,
)


ROLES = {"entry", "manager", "admin"}
# Records describe the whole waste of a service, not one food type. The database column for a
# category stays (older databases require it), so every record points at this one placeholder.
WHOLE_WASTE_CATEGORY = "Whole waste"
# A record with this reason means food ran out (kilograms we were short), not food thrown away.
# It is kept out of the waste totals and shown below zero on the daily chart.
SHORTAGE_REASON = "Ran out (shortage)"
MAX_ID = 2**63 - 1


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


@dataclass(frozen=True)
class RecordFilters:
    """Filters shared by the overview's totals and record table. None means "any"."""
    start_at_utc: str | None = None
    end_before_utc: str | None = None
    area_id: int | None = None
    reason_id: int | None = None


def utc_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _commit(db: Session) -> None:
    """Commit, or undo the pending change so the session stays usable."""
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---- Users -----------------------------------------------------------------

def _user(row: UserRow) -> User:
    return User(row.id, row.name, row.username, row.password_hash, row.role, bool(row.active))


def create_user(db: Session, *, name: str, username: str, password: str, role: str) -> User:
    if role not in ROLES:
        raise ValueError("Invalid user role")
    if not name.strip() or not username.strip() or not password:
        raise ValueError("Name, username, and password are required")
    row = UserRow(name=name.strip(), username=username.strip(),
                  password_hash=generate_password_hash(password), role=role, active=1)
    db.add(row)
    _commit(db)
    return _user(row)


def get_user(db: Session, user_id: int) -> User | None:
    row = db.get(UserRow, user_id)
    return _user(row) if row else None


def get_user_by_username(db: Session, username: str) -> User | None:
    row = db.scalar(select(UserRow).where(UserRow.username == username))
    return _user(row) if row else None


# ---- Lookup lists (areas, categories, reasons) -------------------------------

def list_lookup_items(db: Session, table: str) -> list[LookupItem]:
    if table not in LOOKUP_TABLES:
        raise ValueError("Invalid lookup table")
    model = LOOKUP_TABLES[table]
    rows = db.scalars(select(model).order_by(model.name))
    return [LookupItem(row.id, row.name, bool(row.active)) for row in rows]


# ---- Waste records -----------------------------------------------------------

def _record(row: WasteRecordRow) -> WasteRecord:
    return WasteRecord(row.id, row.event_at, row.area_id, row.category_id, row.reason_id,
                       row.quantity_kg, row.user_id, row.notes, row.created_at, row.updated_at)


def _checked_quantity(quantity_kg) -> float:
    try:
        quantity = float(quantity_kg)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Quantity must be a positive number of kilograms") from exc
    if not isfinite(quantity) or quantity <= 0:
        raise ValueError("Quantity must be a positive finite number of kilograms")
    return quantity


def _checked_time(event_at: datetime) -> str:
    if event_at.tzinfo is None or event_at.utcoffset() is None:
        raise ValueError("Event time must include a time zone")
    return utc_text(event_at)


def whole_waste_category_id(db: Session) -> int:
    """The id of the single "Whole waste" category, created the first time it is needed."""
    found = db.scalar(select(CategoryRow.id).where(CategoryRow.name == WHOLE_WASTE_CATEGORY))
    if found is not None:
        return found
    row = CategoryRow(name=WHOLE_WASTE_CATEGORY, active=1)
    db.add(row)
    _commit(db)
    return row.id


def create_waste_record(db: Session, *, event_at: datetime, area_id: int, reason_id: int,
                        quantity_kg: float, user_id: int, category_id: int | None = None,
                        notes: str = "") -> WasteRecord:
    if category_id is None:
        category_id = whole_waste_category_id(db)
    now = _now_text()
    row = WasteRecordRow(
        event_at=_checked_time(event_at), area_id=area_id, category_id=category_id,
        reason_id=reason_id, quantity_kg=_checked_quantity(quantity_kg), user_id=user_id,
        notes=notes.strip(), created_at=now, updated_at=now,
    )
    db.add(row)
    _commit(db)
    return _record(row)


def get_waste_record(db: Session, record_id: int) -> WasteRecord | None:
    if not 0 < record_id <= MAX_ID:
        return None
    row = db.get(WasteRecordRow, record_id)
    return _record(row) if row else None


def update_waste_record(db: Session, record_id: int, *, event_at: datetime, area_id: int,
                        reason_id: int, quantity_kg: float) -> WasteRecord | None:
    event_text = _checked_time(event_at)
    quantity = _checked_quantity(quantity_kg)
    row = db.get(WasteRecordRow, record_id) if 0 < record_id <= MAX_ID else None
    if row is None:
        return None
    row.event_at, row.area_id = event_text, area_id
    row.reason_id, row.quantity_kg, row.updated_at = reason_id, quantity, _now_text()
    _commit(db)
    return _record(row)


def _where(statement, filters: RecordFilters):
    record = WasteRecordRow
    if filters.start_at_utc is not None:
        statement = statement.where(record.event_at >= filters.start_at_utc)
    if filters.end_before_utc is not None:
        statement = statement.where(record.event_at < filters.end_before_utc)
    for column, value in ((record.area_id, filters.area_id),
                          (record.reason_id, filters.reason_id)):
        if value is not None:
            statement = statement.where(column == value)
    return statement


def list_waste_records(db: Session, filters: RecordFilters = RecordFilters(), *,
                       limit: int | None = None, offset: int = 0) -> list[dict]:
    """Records newest first, with lookup and user names, one page at a time."""
    statement = _where(
        select(WasteRecordRow.id, WasteRecordRow.event_at, WasteRecordRow.quantity_kg,
               WasteRecordRow.user_id, AreaRow.name.label("area"),
               ReasonRow.name.label("reason"),
               UserRow.name.label("recorded_by"))
        .join(AreaRow, AreaRow.id == WasteRecordRow.area_id)
        .join(ReasonRow, ReasonRow.id == WasteRecordRow.reason_id)
        .join(UserRow, UserRow.id == WasteRecordRow.user_id),
        filters,
    ).order_by(WasteRecordRow.event_at.desc(), WasteRecordRow.id.desc()).offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    return [dict(row._mapping) for row in db.execute(statement)]


def count_waste_records(db: Session, filters: RecordFilters = RecordFilters()) -> int:
    return db.scalar(_where(select(func.count(WasteRecordRow.id)), filters)) or 0


def _waste_only(statement):
    """Leave out shortage records, which are not waste."""
    shortage = select(ReasonRow.id).where(ReasonRow.name == SHORTAGE_REASON)
    return statement.where(WasteRecordRow.reason_id.not_in(shortage))


def total_waste_kg(db: Session, filters: RecordFilters = RecordFilters()) -> float:
    """Kilograms thrown away (shortages excluded), added up by the database rather than in Python."""
    return float(db.scalar(_waste_only(_where(
        select(func.coalesce(func.sum(WasteRecordRow.quantity_kg), 0.0)), filters))) or 0.0)


def list_daily_amounts(db: Session, filters: RecordFilters = RecordFilters()) -> list[tuple[str, float, bool]]:
    """(event_at, kg, is_shortage) for every matching record, for the daily chart."""
    statement = _where(
        select(WasteRecordRow.event_at, WasteRecordRow.quantity_kg, ReasonRow.name)
        .join(ReasonRow, ReasonRow.id == WasteRecordRow.reason_id), filters)
    return [(at, float(kg), name == SHORTAGE_REASON) for at, kg, name in db.execute(statement)]


def waste_by(db: Session, table: str, filters: RecordFilters = RecordFilters()) -> list[tuple[str, float]]:
    """(name, total kg) per area or reason, largest first."""
    model = LOOKUP_TABLES[table]
    column = {"areas": WasteRecordRow.area_id, "reasons": WasteRecordRow.reason_id}[table]
    total = func.sum(WasteRecordRow.quantity_kg).label("total")
    statement = _waste_only(_where(select(model.name, total).join(model, model.id == column), filters))
    rows = db.execute(statement.group_by(model.name).order_by(total.desc(), model.name))
    return [(name, float(kg)) for name, kg in rows]


def list_record_notes(db: Session, *, limit: int) -> list[tuple[str, str]]:
    """(event_at, notes) for the newest records that carry notes, oldest first."""
    rows = db.execute(
        select(WasteRecordRow.event_at, WasteRecordRow.notes)
        .where(WasteRecordRow.notes != "")
        .order_by(WasteRecordRow.event_at.desc(), WasteRecordRow.id.desc())
        .limit(limit)
    ).all()
    return [(event_at, notes) for event_at, notes in reversed(rows)]
