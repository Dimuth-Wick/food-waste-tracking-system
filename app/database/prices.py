"""Approximate prices for food, so waste can be shown as money.

Each food is a row of the ``categories`` table (the "Food" of a waste record) with a price per kilogram in
``food_prices``. The prices below are ROUGH starting figures in Sri Lankan rupees per kilogram of prepared
food, based on typical ingredient costs. They are estimates to be edited on the Food prices page, not quotes.
"""

from datetime import datetime, timezone
import json
import logging

from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.tables import CategoryRow, FoodPriceRow, WasteRecordRow


logger = logging.getLogger(__name__)

MIXED_FOOD = "Mixed food"          # waste that is not one known food; its price is the fallback for any unpriced food
LEGACY_PLACEHOLDER = "Whole waste"  # the earlier name of the same category
FALLBACK_PRICE = 600.0             # used only if even the Mixed food price is missing

DEFAULT_PRICES = {
    # menu dishes the forecast knows
    "Bread": 400, "Chicken curry": 1000, "Dessert pudding": 800, "Dhal curry": 350, "Egg curry": 650,
    "Fish curry": 1300, "Fried rice": 600, "Fruit platter": 700, "Milk rice": 350, "Noodles": 550,
    "Pancakes": 450, "Pasta": 650, "Pol roti": 300, "Salad": 450, "Steamed rice": 250,
    "String hoppers": 350, "Vegetable curry": 400,
    # foods the buffet cameras count, priced per piece type
    "Bread roll": 500, "Egg": 650, "Donut": 1400, "Cupcake": 1500, "Apple": 700,
    # broad groups, for when the exact dish is not known
    "Vegetables": 350, "Prepared Food": 700, "Bakery": 900, "Meat & Seafood": 1200,
    MIXED_FOOD: 600,
}


def create_price_table(bind) -> None:
    """Create the price table, or add the per-piece columns to one made before they existed."""
    FoodPriceRow.__table__.create(bind, checkfirst=True)
    have = {column["name"] for column in inspect(bind).get_columns(FoodPriceRow.__tablename__)}
    with bind.begin() as conn:
        for name in ("price_per_piece", "piece_kg"):
            if name not in have:
                conn.execute(text(f"ALTER TABLE {FoodPriceRow.__tablename__} ADD COLUMN {name} FLOAT"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _by_name(db: Session) -> dict[str, CategoryRow]:
    return {row.name.lower(): row for row in db.scalars(select(CategoryRow))}


def category_named(db: Session, name: str, *, create: bool = True) -> CategoryRow | None:
    """The food with this name (any capitals), adding it when it does not exist yet."""
    name = " ".join(name.split())
    row = db.scalar(select(CategoryRow).where(func.lower(CategoryRow.name) == name.lower()))
    if row is None and create and name:
        row = CategoryRow(name=name, active=1)
        db.add(row)
        db.flush()
    return row


def ensure_price_data(db: Session) -> bool:
    """Set up foods and prices once: the price table, the default foods and prices, and the foods of older
    records. Safe to run again: it only adds what is missing and never changes a price someone has set.

    Returns False if the database is not initialized yet.
    """
    bind = db.get_bind()
    try:
        if not inspect(bind).has_table(CategoryRow.__tablename__) or not inspect(bind).has_table(WasteRecordRow.__tablename__):
            return False
        create_price_table(bind)

        # the placeholder food is now called Mixed food
        names = _by_name(db)
        if LEGACY_PLACEHOLDER.lower() in names and MIXED_FOOD.lower() not in names:
            names[LEGACY_PLACEHOLDER.lower()].name = MIXED_FOOD

        priced = set(db.scalars(select(FoodPriceRow.category_id)))
        for name, price in DEFAULT_PRICES.items():
            row = category_named(db, name)
            if row.id not in priced:
                db.add(FoodPriceRow(category_id=row.id, price_per_kg=float(price), updated_at=_now()))
        db.flush()
        _sort_older_records(db)
        db.commit()
        return True
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not set up the food prices.")
        return False


def _sort_older_records(db: Session) -> None:
    """Give older "mixed food" records the food their notes name (demo history and photo counts)."""
    mixed = category_named(db, MIXED_FOOD)
    foods = _by_name(db)
    for record in db.scalars(select(WasteRecordRow).where(WasteRecordRow.category_id == mixed.id, WasteRecordRow.notes != "")):
        try:
            notes = json.loads(record.notes)
        except ValueError:
            continue
        if not isinstance(notes, dict):
            continue
        for key in ("label", "food_item", "item"):
            name = " ".join(str(notes.get(key) or "").split())
            if name:
                row = foods.get(name.lower())
                if row is None:
                    row = category_named(db, name.capitalize() if name.islower() else name)
                    foods[name.lower()] = row
                record.category_id = row.id
                break


def ensure_once(app, db: Session) -> None:
    """Run ensure_price_data the first time it is needed in this app."""
    if not getattr(app.state, "prices_ready", False):
        app.state.prices_ready = ensure_price_data(db)


def price_map(db: Session) -> dict:
    """{"prices": {food id: price per kg}, "mixed": the Mixed food price} for showing a cost before saving."""
    try:
        rows = db.execute(select(FoodPriceRow.category_id, FoodPriceRow.price_per_kg)).all()
        prices = {category_id: float(price) for category_id, price in rows}
        mixed = category_named(db, MIXED_FOOD, create=False)
    except SQLAlchemyError:   # not initialized yet: the form still opens, without a cost preview
        db.rollback()
        return {"prices": {}, "mixed": FALLBACK_PRICE}
    return {"prices": prices, "mixed": prices.get(mixed.id, FALLBACK_PRICE) if mixed else FALLBACK_PRICE}


def food_for_camera(db: Session, label: str, dish: str | None) -> CategoryRow:
    """The food a camera count belongs to: one named like the count ("egg"), else its menu dish, else a new one."""
    return (category_named(db, label, create=False)
            or (category_named(db, dish, create=False) if dish else None)
            or category_named(db, label.capitalize()))
