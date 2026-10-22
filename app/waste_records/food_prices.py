"""Food prices: the approximate price of each food, per kilogram or per piece, which turns waste into money.

Every food is a row of the categories table; its price lives in food_prices. A food with no price is valued
at the "Mixed food" price. A food priced per piece also has the weight of one piece, so its price per kilogram
can be worked out. Changing a price changes the value of every record of that food, past and future.
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.connection import get_session
from app.database.prices import FALLBACK_PRICE, MIXED_FOOD, category_named, _now
from app.database.tables import CategoryRow, FoodPriceRow, WasteRecordRow
from app.web import render, url_path


logger = logging.getLogger(__name__)
router = APIRouter(include_in_schema=False)

MAX_PRICE = 1_000_000
NAME_MAX = 60
MAX_GRAMS = 100_000


def _rows(db: Session) -> list[dict]:
    """Every food in use: its name, price (or None), and how many records are of that food."""
    prices = {row.category_id: row for row in db.scalars(select(FoodPriceRow))}
    used = dict(db.execute(select(WasteRecordRow.category_id, func.count(WasteRecordRow.id))
                           .group_by(WasteRecordRow.category_id)).all())
    foods = db.scalars(select(CategoryRow).where(CategoryRow.active == 1)).all()
    rows = [{"id": food.id, "name": food.name, "records": used.get(food.id, 0), "mixed": food.name == MIXED_FOOD,
             **_shown(prices.get(food.id))} for food in foods]
    return sorted(rows, key=lambda row: (row["mixed"], row["name"].lower()))


def _shown(price: FoodPriceRow | None) -> dict:
    """What the page shows for a food's price: the figure typed, its unit, a piece's weight in grams and the rate per kg."""
    if price is None:
        return {"price": None, "per_kg": None, "unit": "kg", "grams": None}
    if price.price_per_piece:
        return {"price": price.price_per_piece, "per_kg": price.price_per_kg, "unit": "piece", "grams": price.piece_kg * 1000}
    return {"price": price.price_per_kg, "per_kg": price.price_per_kg, "unit": "kg", "grams": None}


def _parse_grams(raw: str) -> float | None:
    try:
        value = float(raw.replace(",", "").strip())
    except ValueError:
        return None
    return value if 0 < value <= MAX_GRAMS and value == value else None


def _parse_price(raw: str) -> float | None:
    try:
        value = float(raw.replace(",", "").strip())
    except ValueError:
        return None
    return value if 0 < value <= MAX_PRICE and value == value else None


def _page(request: Request, db: Session, *, status_code=200, errors=None, entered=None, new=None, saved=False):
    rows = _rows(db)
    mixed = next((row["price"] for row in rows if row["mixed"]), None) or FALLBACK_PRICE
    return render(request, "food_prices.html", status_code, active_page="food_prices", rows=rows,
                  errors=errors or {}, entered=entered or {}, new=new or {}, saved=saved, mixed_price=mixed)


@router.get("/food-prices", name="food_prices")
def food_prices_page(request: Request, saved: str = "", db: Session = Depends(get_session)):
    try:
        return _page(request, db, saved=bool(saved))
    except SQLAlchemyError:
        logger.exception("Could not load the food prices")
        return render(request, "error.html", 503, status=503, title="Service unavailable",
                      message="The database is unavailable. Initialize it and try again.")


def _read(form, suffix: str) -> tuple[dict | None, str]:
    """The price typed for one food: ({"unit", "price", "grams"}, "") or (None, the problem). Blank is (None, "")."""
    raw = str(form.get(f"price_{suffix}", "")).strip()
    if not raw:
        return None, ""
    price = _parse_price(raw)
    if price is None:
        return None, f"Enter a price above 0 and up to {MAX_PRICE:,}."
    if form.get(f"unit_{suffix}") != "piece":
        return {"unit": "kg", "price": price, "grams": None}, ""
    grams = _parse_grams(str(form.get(f"grams_{suffix}", "")))
    if grams is None:
        return None, "Enter what one piece weighs in grams, for example 60."
    return {"unit": "piece", "price": price, "grams": grams}, ""


def _apply(row: FoodPriceRow, price: dict) -> None:
    """Store a price; a per-piece price also keeps its rate per kilogram, which is what values are worked out from."""
    if price["unit"] == "piece":
        piece_kg = price["grams"] / 1000
        values = (price["price"] / piece_kg, price["price"], piece_kg)
    else:
        values = (price["price"], None, None)
    if (row.price_per_kg, row.price_per_piece, row.piece_kg) != values:
        row.price_per_kg, row.price_per_piece, row.piece_kg = values
        row.updated_at = _now()


@router.post("/food-prices", name="save_food_prices")
async def save_food_prices(request: Request, db: Session = Depends(get_session)):
    form = await request.form()
    errors, entered = {}, {}
    try:
        rows = _rows(db)
        changes = {}
        for row in rows:
            key = str(row["id"])
            entered[key] = {"price": str(form.get(f"price_{key}", "")).strip(), "unit": "piece" if form.get(f"unit_{key}") == "piece" else "kg",
                            "grams": str(form.get(f"grams_{key}", "")).strip()}
            price, problem = _read(form, key)
            if problem:
                errors[key] = problem
            elif price is None and row["mixed"]:
                errors[key] = "Mixed food needs a price: it is used for any food without its own."
            changes[row["id"]] = price

        new_name = " ".join(str(form.get("new_name", "")).split())
        new = {"name": new_name, "price": str(form.get("price_new", "")).strip(), "unit": "piece" if form.get("unit_new") == "piece" else "kg",
               "grams": str(form.get("grams_new", "")).strip()}
        new_price = None
        if new_name or new["price"]:
            if not new_name or len(new_name) > NAME_MAX:
                errors["new_name"] = f"Enter the food's name (up to {NAME_MAX} letters)."
            elif category_named(db, new_name, create=False) is not None:
                errors["new_name"] = f"{new_name} is already on the list."
            new_price, problem = _read(form, "new")
            if new_price is None:
                errors["new_price"] = problem or f"Enter a price above 0 and up to {MAX_PRICE:,}."

        if errors:
            db.rollback()
            return _page(request, db, status_code=400, errors=errors, entered=entered, new=new)

        existing = {row.category_id: row for row in db.scalars(select(FoodPriceRow))}
        for row in rows:
            price = changes[row["id"]]
            if price is None:
                if row["id"] in existing:   # blank means "use the Mixed food price"
                    db.delete(existing[row["id"]])
            elif row["id"] in existing:
                _apply(existing[row["id"]], price)
            else:
                fresh = FoodPriceRow(category_id=row["id"], price_per_kg=1, updated_at=_now())
                _apply(fresh, price)
                db.add(fresh)
        if new_name:
            food = category_named(db, new_name)
            fresh = FoodPriceRow(category_id=food.id, price_per_kg=1, updated_at=_now())
            _apply(fresh, new_price)
            db.add(fresh)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not save the food prices")
        return _page(request, db, status_code=500, errors={"form": "The prices could not be saved. Try again."})
    return RedirectResponse(f"{url_path(request.app, 'food_prices')}?saved=1", status_code=303)
