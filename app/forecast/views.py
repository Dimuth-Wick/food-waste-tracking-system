"""Meal forecast page and its JSON APIs.

``POST /api/predict-meal`` returns a consumption forecast with a 10% safety
margin. ``GET /api/forecast-history`` compares past consumption with what the
model would have predicted. Neither changes the database.
"""

import json
import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.connection import get_session
from app.database.queries import list_record_notes
from app.forecast.model import get_model
from app.web import api_error, render, url_path


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Meal forecast"])

# Food items and meal types the model was trained on.
MEAL_TYPES = ["Breakfast", "Lunch", "Dinner"]
FOOD_ITEMS = [
    "Bread", "Chicken curry", "Dessert pudding", "Dhal curry",
    "Egg curry", "Fish curry", "Fried rice", "Fruit platter",
    "Milk rice", "Noodles", "Pancakes", "Pasta", "Pol roti",
    "Salad", "Steamed rice", "String hoppers", "Vegetable curry",
]
SAFETY_MARGIN = 0.10
HISTORY_ITEMS = 5
HISTORY_RECORDS_SCANNED = 2000


class MealRequest(BaseModel):
    meal_type: Any = Field(None, validate_default=True, examples=["Dinner"])
    food_item: Any = Field(None, validate_default=True, examples=["Fried rice"])
    guest_count: Any = Field(None, validate_default=True, examples=[150])

    @field_validator("meal_type", "food_item", mode="before")
    @classmethod
    def _not_empty(cls, value, info):
        if value is None or not str(value).strip():
            raise ValueError(f"{info.field_name} must not be empty.")
        return str(value).strip()

    @field_validator("guest_count", mode="before")
    @classmethod
    def _positive_number(cls, value):
        if value is None:
            raise ValueError("guest_count is required.")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError("guest_count must be a number.") from None
        if not number > 0:
            raise ValueError("guest_count must be greater than 0.")
        return number


class MealForecast(BaseModel):
    predicted_consumption: float
    safety_margin: float
    recommended_quantity: float


class HistoryPoint(BaseModel):
    date: str
    actual: float
    predicted: float


class HistoryItem(BaseModel):
    food_item: str
    history: list[HistoryPoint]


class ForecastHistory(BaseModel):
    items: list[HistoryItem]


def _frame(rows):
    return pd.DataFrame([{"Meal type": meal, "Food item": food, "Guest count": guests}
                         for meal, food, guests in rows])


@router.get("/forecast", name="forecast", include_in_schema=False)
def forecast_page(request: Request):
    return render(
        request, "_react_page.html",
        react_page="forecast",
        active_page="forecast",
        page_title="Meal forecast",
        heading="Meal demand forecast",
        description=("Choose the meal, the dish and how many guests are expected to see "
                     "how much to prepare. The forecast updates as you change them."),
        settings={
            "predictUrl": url_path(request.app, "predict_meal"),
            "historyUrl": url_path(request.app, "forecast_history"),
            "mealTypes": MEAL_TYPES,
            "foodItems": FOOD_ITEMS,
        },
    )


@router.post("/api/predict-meal", name="predict_meal", response_model=MealForecast,
             summary="Forecast how much of a dish will be eaten")
def predict_meal(request: Request, meal: MealRequest):
    try:
        predicted = float(get_model(request).predict(
            _frame([(meal.meal_type, meal.food_item, meal.guest_count)]))[0])
    except Exception:
        logger.exception("Prediction failed")
        return api_error("Prediction failed. Check the server logs for details.", 500)
    margin = predicted * SAFETY_MARGIN
    return MealForecast(predicted_consumption=round(predicted, 2), safety_margin=round(margin, 2),
                        recommended_quantity=round(predicted + margin, 2))


@router.get("/api/forecast-history", name="forecast_history", response_model=ForecastHistory,
            summary="Past consumption compared with the model's forecast")
def forecast_history(request: Request, db: Session = Depends(get_session)):
    """Uses records whose notes hold meal_type, food_item, guest_count and consumed_quantity."""
    try:
        rows = list_record_notes(db, limit=HISTORY_RECORDS_SCANNED)
    except SQLAlchemyError:
        logger.exception("Could not read forecast history")
        return api_error("The database is unavailable.", 503)

    points = []
    for event_at, notes in rows:
        try:
            data = json.loads(notes)
            meal, food = data["meal_type"], data["food_item"]
            guests, actual = float(data["guest_count"]), float(data["consumed_quantity"])
        except (ValueError, TypeError, KeyError):
            continue
        if None in (meal, food):
            continue
        points.append((event_at.split("T")[0], meal, food, guests, actual))

    order = list(dict.fromkeys(food for _, _, food, _, _ in points))[:HISTORY_ITEMS]
    points = [point for point in points if point[2] in order]
    if not points:
        return ForecastHistory(items=[])
    try:
        # One model call for every point, instead of one call per record.
        predictions = get_model(request).predict(_frame([(meal, food, guests) for _, meal, food, guests, _ in points]))
    except Exception:
        logger.exception("History prediction failed")
        return api_error("Prediction failed. Check the server logs for details.", 500)

    history = {food: [] for food in order}
    for (day, _, food, _, actual), predicted in zip(points, predictions):
        history[food].append(HistoryPoint(date=day, actual=round(actual, 2), predicted=round(float(predicted), 2)))
    return ForecastHistory(items=[HistoryItem(food_item=food, history=history[food]) for food in order])
