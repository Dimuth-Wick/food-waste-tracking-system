"""Reading and writing waste data. Views call these functions, never SQL directly.

Results are returned as small frozen dataclasses or plain dicts, so callers do
not depend on SQLAlchemy objects.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app.database.prices import FALLBACK_PRICE, LEGACY_PLACEHOLDER, MIXED_FOOD, create_price_table
from app.database.tables import (
    LOOKUP_TABLES,
    AreaRow,
    CategoryRow,
    FoodPriceRow,
    MealCheckRow,
    ReasonRow,
    UserRow,
    WasteRecordRow,
)


ROLES = {"entry", "manager", "admin"}
# A record's food is its category. Waste that is not one known food is "Mixed food".
WHOLE_WASTE_CATEGORY = MIXED_FOOD
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
    category_id: int | None = None
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


def set_user_password(db: Session, user_id: int, password: str) -> bool:
    """Give a user a new password. Anyone signed in with the old one is signed out. False if there is no such user."""
    if len(password) < 8:
        raise ValueError("The password must have at least 8 characters.")
    row = db.get(UserRow, user_id)
    if row is None:
        return False
    row.password_hash = generate_password_hash(password)
    _commit(db)
    return True


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
    found = db.scalar(select(CategoryRow.id).where(CategoryRow.name.in_([WHOLE_WASTE_CATEGORY, LEGACY_PLACEHOLDER])))
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
                        reason_id: int, quantity_kg: float, category_id: int | None = None) -> WasteRecord | None:
    event_text = _checked_time(event_at)
    quantity = _checked_quantity(quantity_kg)
    row = db.get(WasteRecordRow, record_id) if 0 < record_id <= MAX_ID else None
    if row is None:
        return None
    row.event_at, row.area_id = event_text, area_id
    if category_id is not None:
        row.category_id = category_id
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
                          (record.category_id, filters.category_id),
                          (record.reason_id, filters.reason_id)):
        if value is not None:
            statement = statement.where(column == value)
    return statement


_PRICE_TABLES: set[int] = set()


def _ensure_price_table(db: Session) -> None:
    """The price table exists (empty if nothing has set prices yet), so value queries never fail."""
    key = id(db.get_bind())
    if key not in _PRICE_TABLES:
        create_price_table(db.get_bind())
        _PRICE_TABLES.add(key)


def _value():
    """SQL for what a record's waste is worth: kilograms x the price of its food, or of Mixed food if it has none."""
    mixed = (select(FoodPriceRow.price_per_kg).join(CategoryRow, CategoryRow.id == FoodPriceRow.category_id)
             .where(CategoryRow.name == MIXED_FOOD).scalar_subquery())
    return WasteRecordRow.quantity_kg * func.coalesce(FoodPriceRow.price_per_kg, mixed, FALLBACK_PRICE)


def _priced(statement):
    return statement.outerjoin(FoodPriceRow, FoodPriceRow.category_id == WasteRecordRow.category_id)


def list_waste_records(db: Session, filters: RecordFilters = RecordFilters(), *,
                       limit: int | None = None, offset: int = 0) -> list[dict]:
    """Records newest first, with food, lookup and user names and approximate value."""
    _ensure_price_table(db)
    statement = _where(
        _priced(select(WasteRecordRow.id, WasteRecordRow.event_at, WasteRecordRow.quantity_kg,
                       WasteRecordRow.user_id, WasteRecordRow.notes, WasteRecordRow.category_id,
                       AreaRow.name.label("area"), CategoryRow.name.label("food"), ReasonRow.name.label("reason"),
                       UserRow.name.label("recorded_by"), _value().label("value"))
                .select_from(WasteRecordRow)
                .join(AreaRow, AreaRow.id == WasteRecordRow.area_id)
                .join(CategoryRow, CategoryRow.id == WasteRecordRow.category_id)
                .join(ReasonRow, ReasonRow.id == WasteRecordRow.reason_id)
                .join(UserRow, UserRow.id == WasteRecordRow.user_id)),
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


def total_waste_value(db: Session, filters: RecordFilters = RecordFilters()) -> float:
    """What the food thrown away is worth, approximately (shortages excluded)."""
    _ensure_price_table(db)
    return float(db.scalar(_waste_only(_where(
        _priced(select(func.coalesce(func.sum(_value()), 0.0)).select_from(WasteRecordRow)), filters))) or 0.0)


def list_daily_amounts(db: Session, filters: RecordFilters = RecordFilters()) -> list[tuple[str, float, float, bool]]:
    """(event_at, kg, value, is_shortage) for every matching record, for the daily chart."""
    _ensure_price_table(db)
    statement = _where(
        _priced(select(WasteRecordRow.event_at, WasteRecordRow.quantity_kg, _value(), ReasonRow.name)
                .select_from(WasteRecordRow)
                .join(ReasonRow, ReasonRow.id == WasteRecordRow.reason_id)), filters)
    return [(at, float(kg), float(value), name == SHORTAGE_REASON) for at, kg, value, name in db.execute(statement)]


def waste_by(db: Session, table: str, filters: RecordFilters = RecordFilters()) -> list[tuple[str, float, float]]:
    """(name, kg, value) per area, food or reason, most valuable first."""
    _ensure_price_table(db)
    model = LOOKUP_TABLES[table]
    column = {"areas": WasteRecordRow.area_id, "categories": WasteRecordRow.category_id,
              "reasons": WasteRecordRow.reason_id}[table]
    kg = func.sum(WasteRecordRow.quantity_kg).label("kg")
    value = func.sum(_value()).label("value")
    statement = _waste_only(_where(
        _priced(select(model.name, kg, value).select_from(WasteRecordRow).join(model, model.id == column)), filters))
    rows = db.execute(statement.group_by(model.name).order_by(value.desc(), model.name))
    return [(name, float(weight), float(worth)) for name, weight, worth in rows]


def list_record_notes(db: Session, *, limit: int) -> list[tuple[str, str]]:
    """(event_at, notes) for the newest records that carry notes, oldest first."""
    rows = db.execute(
        select(WasteRecordRow.event_at, WasteRecordRow.notes)
        .where(WasteRecordRow.notes != "")
        .order_by(WasteRecordRow.event_at.desc(), WasteRecordRow.id.desc())
        .limit(limit)
    ).all()
    return [(event_at, notes) for event_at, notes in reversed(rows)]


# ---- Meal checks (buffet photos counted at the start and end of a meal) --------

@dataclass(frozen=True)
class MealCheck:
    id: int
    event_at: str
    meal_type: str
    food_item: str
    count_label: str
    start_count: int
    end_count: int
    short_count: int
    kg_per_piece: float
    guest_count: int
    area_id: int
    waste_record_id: int | None
    shortage_record_id: int | None
    user_id: int
    created_at: str

    @property
    def eaten_kg(self) -> float:
        return (self.start_count - self.end_count) * self.kg_per_piece


def ensure_meal_check_table(db: Session) -> None:
    """Create the meal_checks table in databases made before it existed."""
    MealCheckRow.__table__.create(db.get_bind(), checkfirst=True)


def reason_id_named(db: Session, name: str) -> int:
    """The id of the reason with this name, adding it if it is missing."""
    found = db.scalar(select(ReasonRow.id).where(ReasonRow.name == name))
    if found is not None:
        return found
    row = ReasonRow(name=name, active=1)
    db.add(row)
    _commit(db)
    return row.id


def create_meal_check(db: Session, *, event_at: datetime, meal_type: str, food_item: str,
                      count_label: str, start_count: int, end_count: int, short_count: int,
                      kg_per_piece: float, guest_count: int, area_id: int, reason_id: int,
                      user_id: int, category_id: int | None = None) -> tuple[MealCheck, WasteRecord | None, WasteRecord | None]:
    """Save a meal check, plus a waste record for the leftovers and one for any shortage.

    The waste records hold only a reference to the meal check in their notes, so the forecast
    reads what was eaten from the meal check once rather than twice.
    """
    ensure_meal_check_table(db)
    leftovers = shortage = None
    if end_count > 0:
        leftovers = create_waste_record(
            db, event_at=event_at, area_id=area_id, reason_id=reason_id,
            quantity_kg=end_count * kg_per_piece, user_id=user_id, category_id=category_id,
            notes=json.dumps({"source": "photo count", "item": food_item, "label": count_label, "meal": meal_type,
                              "start": start_count, "end": end_count}))
    if short_count > 0:
        shortage = create_waste_record(
            db, event_at=event_at, area_id=area_id, reason_id=reason_id_named(db, SHORTAGE_REASON),
            quantity_kg=short_count * kg_per_piece, user_id=user_id, category_id=category_id,
            notes=json.dumps({"source": "photo count", "item": food_item, "label": count_label, "meal": meal_type,
                              "short": short_count}))
    row = MealCheckRow(
        event_at=_checked_time(event_at), meal_type=meal_type, food_item=food_item,
        count_label=count_label, start_count=start_count, end_count=end_count,
        short_count=short_count, kg_per_piece=kg_per_piece, guest_count=guest_count,
        area_id=area_id, user_id=user_id, created_at=_now_text(),
        waste_record_id=leftovers.id if leftovers else None,
        shortage_record_id=shortage.id if shortage else None,
    )
    db.add(row)
    _commit(db)
    return _meal_check(row), leftovers, shortage


def _meal_check(row: MealCheckRow) -> MealCheck:
    return MealCheck(row.id, row.event_at, row.meal_type, row.food_item, row.count_label,
                     row.start_count, row.end_count, row.short_count, row.kg_per_piece,
                     row.guest_count, row.area_id, row.waste_record_id, row.shortage_record_id,
                     row.user_id, row.created_at)


def list_meal_checks(db: Session, *, limit: int) -> list[MealCheck]:
    """The newest meal checks, oldest first. Empty if the table does not exist yet."""
    if not inspect(db.get_bind()).has_table(MealCheckRow.__tablename__):
        return []
    rows = db.scalars(select(MealCheckRow).order_by(MealCheckRow.event_at.desc(),
                                                    MealCheckRow.id.desc()).limit(limit)).all()
    return [_meal_check(row) for row in reversed(rows)]


def latest_piece_weights(db: Session) -> dict[str, float]:
    """The most recent weight per piece used for each food item, so staff set it only once."""
    return {check.food_item: check.kg_per_piece for check in list_meal_checks(db, limit=500)}
