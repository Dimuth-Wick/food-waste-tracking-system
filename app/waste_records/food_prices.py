"""Food prices: the approximate price per kilogram of each food, which turns waste into money.

Every food is a row of the categories table; its price lives in food_prices. A food with no price is valued
at the "Mixed food" price. Changing a price changes the value of every record of that food, past and future.
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


def _rows(db: Session) -> list[dict]:
    """Every food in use: its name, price (or None), and how many records are of that food."""
    prices = {row.category_id: row.price_per_kg for row in db.scalars(select(FoodPriceRow))}
    used = dict(db.execute(select(WasteRecordRow.category_id, func.count(WasteRecordRow.id))
                           .group_by(WasteRecordRow.category_id)).all())
    foods = db.scalars(select(CategoryRow).where(CategoryRow.active == 1)).all()
    rows = [{"id": food.id, "name": food.name, "price": prices.get(food.id), "records": used.get(food.id, 0),
             "mixed": food.name == MIXED_FOOD} for food in foods]
    return sorted(rows, key=lambda row: (row["mixed"], row["name"].lower()))


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


@router.post("/food-prices", name="save_food_prices")
async def save_food_prices(request: Request, db: Session = Depends(get_session)):
    form = await request.form()
    errors, entered = {}, {}
    try:
        rows = _rows(db)
        changes = {}
        for row in rows:
            raw = str(form.get(f"price_{row['id']}", "")).strip()
            entered[str(row["id"])] = raw
            if not raw:
                if row["mixed"]:
                    errors[str(row["id"])] = "Mixed food needs a price: it is used for any food without its own."
                continue
            price = _parse_price(raw)
            if price is None:
                errors[str(row["id"])] = f"Enter a price above 0 and up to {MAX_PRICE:,}."
            else:
                changes[row["id"]] = price

        new_name = " ".join(str(form.get("new_name", "")).split())
        new_raw = str(form.get("new_price", "")).strip()
        new = {"name": new_name, "price": new_raw}
        if new_name or new_raw:
            if not new_name or len(new_name) > NAME_MAX:
                errors["new_name"] = f"Enter the food's name (up to {NAME_MAX} letters)."
            elif category_named(db, new_name, create=False) is not None:
                errors["new_name"] = f"{new_name} is already on the list."
            if _parse_price(new_raw) is None:
                errors["new_price"] = f"Enter a price above 0 and up to {MAX_PRICE:,}."

        if errors:
            db.rollback()
            return _page(request, db, status_code=400, errors=errors, entered=entered, new=new)

        existing = {row.category_id: row for row in db.scalars(select(FoodPriceRow))}
        for row in rows:
            raw = entered[str(row["id"])]
            if not raw:
                if row["id"] in existing:   # blank means "use the Mixed food price"
                    db.delete(existing[row["id"]])
            elif row["id"] in existing:
                if existing[row["id"]].price_per_kg != changes[row["id"]]:
                    existing[row["id"]].price_per_kg, existing[row["id"]].updated_at = changes[row["id"]], _now()
            else:
                db.add(FoodPriceRow(category_id=row["id"], price_per_kg=changes[row["id"]], updated_at=_now()))
        if new_name:
            food = category_named(db, new_name)
            db.add(FoodPriceRow(category_id=food.id, price_per_kg=_parse_price(new_raw), updated_at=_now()))
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not save the food prices")
        return _page(request, db, status_code=500, errors={"form": "The prices could not be saved. Try again."})
    return RedirectResponse(f"{url_path(request.app, 'food_prices')}?saved=1", status_code=303)
