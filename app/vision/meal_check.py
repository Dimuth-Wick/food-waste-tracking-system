"""Save a buffet meal check: pieces counted in the start and end photos of a meal.

Leftover pieces x weight per piece becomes a waste record (so the overview's totals,
charts and table update), any pieces that ran short become a shortage record, and
what was eaten feeds the meal forecast's "How close past forecasts were" section.
"""

from datetime import datetime
import logging
import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.connection import get_session
from app.database.queries import (
    SHORTAGE_REASON,
    create_meal_check,
    get_user_by_username,
    latest_piece_weights,
)
from app.forecast.views import FOOD_ITEMS, MEAL_TYPES
from app.waste_records.common import DEMO_TIMEZONE, DEMO_USERNAME, load_lookups
from app.web import api_error, url_path


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Food counting"])

MAX_PIECES = 10_000
MAX_KG_PER_PIECE = 20
MAX_GUESTS = 100_000
DEFAULT_AREA = "Buffet"
DEFAULT_REASON = "Overproduction"
# When each meal usually ends, to prefill the time of the end-of-meal photo.
MEAL_ENDS = {"Breakfast": "10:00", "Lunch": "15:00", "Dinner": "22:00"}


class MealCheckIn(BaseModel):
    food_item: str = Field(examples=["Bread"])
    count_label: str = Field("", examples=["bun"])
    meal_type: str = Field(examples=["Breakfast"])
    ended_at: str = Field(examples=["2026-10-20T10:00"], description="Sri Lanka local time")
    area_id: int
    reason_id: int
    start_count: int = Field(examples=[14])
    end_count: int = Field(examples=[2])
    short_count: int = Field(0, examples=[0])
    kg_per_piece: float = Field(examples=[0.06])
    guest_count: int = Field(examples=[120])


class MealCheckOut(BaseModel):
    meal_check_id: int
    waste_record_id: int | None
    shortage_record_id: int | None
    eaten_kg: float
    waste_kg: float
    short_kg: float
    overview_url: str
    forecast_url: str


def meal_check_settings(request: Request, db: Session) -> dict | None:
    """Choices for the save form on the Food counting page, or None if the database is unavailable."""
    try:
        lookups = load_lookups(db, active_only=True)
        weights = latest_piece_weights(db)
    except SQLAlchemyError:
        logger.exception("Could not load meal check choices")
        return None
    reasons = [item for item in lookups["reasons"] if item.name != SHORTAGE_REASON]

    def default(items, name):
        return next((item.id for item in items if item.name == name), items[0].id if items else None)

    return {
        "saveUrl": url_path(request.app, "save_meal_check"),
        "foodItems": FOOD_ITEMS,
        "mealTypes": MEAL_TYPES,
        "mealEnds": MEAL_ENDS,
        "areas": [{"id": item.id, "name": item.name} for item in lookups["areas"]],
        "reasons": [{"id": item.id, "name": item.name} for item in reasons],
        "defaultAreaId": default(lookups["areas"], DEFAULT_AREA),
        "defaultReasonId": default(reasons, DEFAULT_REASON),
        "pieceWeights": weights,
        "maxPieces": MAX_PIECES,
    }


def _errors(data: MealCheckIn, lookups) -> tuple[dict[str, str], datetime | None]:
    errors = {}
    if data.food_item not in FOOD_ITEMS:
        errors["food_item"] = "Choose a food item from the list."
    if data.meal_type not in MEAL_TYPES:
        errors["meal_type"] = "Choose breakfast, lunch or dinner."
    ended = None
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", data.ended_at):
            raise ValueError
        ended = datetime.fromisoformat(data.ended_at).replace(tzinfo=DEMO_TIMEZONE)
    except ValueError:
        errors["ended_at"] = "Enter the date and time the meal ended."
    if data.area_id not in {item.id for item in lookups["areas"]}:
        errors["area_id"] = "Choose an area."
    if data.reason_id not in {item.id for item in lookups["reasons"] if item.name != SHORTAGE_REASON}:
        errors["reason_id"] = "Choose a reason for the leftovers."
    for field, label in (("start_count", "start"), ("end_count", "end"), ("short_count", "short")):
        if not 0 <= getattr(data, field) <= MAX_PIECES:
            errors[field] = f"The {label} count must be between 0 and {MAX_PIECES:,}."
    if "start_count" not in errors and "end_count" not in errors and data.end_count > data.start_count:
        errors["end_count"] = "There can't be more pieces at the end than at the start."
    if data.start_count == 0:
        errors["start_count"] = "Count the start-of-meal photo first; it found no pieces."
    if not 0 < data.kg_per_piece <= MAX_KG_PER_PIECE:
        errors["kg_per_piece"] = f"Enter a weight per piece above 0 and up to {MAX_KG_PER_PIECE} kg."
    if not 0 < data.guest_count <= MAX_GUESTS:
        errors["guest_count"] = "Enter how many guests came, at least 1."
    return errors, ended


@router.post("/api/meal-checks", name="save_meal_check", response_model=MealCheckOut,
             summary="Save a meal counted from start and end photos")
def save_meal_check(request: Request, data: MealCheckIn, db: Session = Depends(get_session)):
    """Leftovers become a waste record, shortages a shortage record, and eaten amounts feed the forecast."""
    try:
        lookups = load_lookups(db, active_only=True)
        actor = get_user_by_username(db, DEMO_USERNAME)
    except SQLAlchemyError:
        logger.exception("Could not load meal check choices")
        return api_error("The database is unavailable. Initialize it and try again.", 503)
    if actor is None or not actor.active:
        return api_error("Demo entry data is missing. Initialize and seed the local database first.", 503)

    errors, ended = _errors(data, lookups)
    if errors:
        return api_error("Check the highlighted fields.", 400, fields=errors)
    try:
        check, leftovers, shortage = create_meal_check(
            db, event_at=ended, meal_type=data.meal_type, food_item=data.food_item,
            count_label=" ".join(data.count_label.split())[:40], start_count=data.start_count,
            end_count=data.end_count, short_count=data.short_count, kg_per_piece=data.kg_per_piece,
            guest_count=data.guest_count, area_id=data.area_id, reason_id=data.reason_id,
            user_id=actor.id,
        )
    except (SQLAlchemyError, ValueError):
        logger.exception("Could not save meal check")
        return api_error("The meal check could not be saved. Check the details and try again.", 500)

    saved = leftovers or shortage
    overview = url_path(request.app, "day_details", day=ended.date().isoformat(),
                        **({"created": saved.id} if saved else {}))
    return MealCheckOut(
        meal_check_id=check.id,
        waste_record_id=leftovers.id if leftovers else None,
        shortage_record_id=shortage.id if shortage else None,
        eaten_kg=round(check.eaten_kg, 3),
        waste_kg=round(data.end_count * data.kg_per_piece, 3),
        short_kg=round(data.short_count * data.kg_per_piece, 3),
        overview_url=overview,
        forecast_url=url_path(request.app, "forecast"),
    )
