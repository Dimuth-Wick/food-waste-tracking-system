"""Meal forecast API and page — predict consumed quantity using the trained ML model.

Provides a JSON endpoint that accepts meal details and returns
a predicted consumption figure with a 10 % safety margin, plus
the GET page that hosts the forecast form.

The endpoint does **not** touch the waste-record database; it only uses
the scikit-learn pipeline loaded at startup via :mod:`app.ml`.
"""

import traceback
import json
import pandas as pd
from flask import current_app, jsonify, render_template, request

from app.ml import get_model
from app.db import get_db

# Food items and meal types the model was trained on.
MEAL_TYPES = ["Breakfast", "Lunch", "Dinner"]
FOOD_ITEMS = [
    "Bread", "Chicken curry", "Dessert pudding", "Dhal curry",
    "Egg curry", "Fish curry", "Fried rice", "Fruit platter",
    "Milk rice", "Noodles", "Pancakes", "Pasta", "Pol roti",
    "Salad", "Steamed rice", "String hoppers", "Vegetable curry",
]


def forecast_page():
    """``GET /forecast`` — render the meal forecast form."""
    return render_template(
        "forecast.html",
        active_page="forecast",
        meal_types=MEAL_TYPES,
        food_items=FOOD_ITEMS,
    )


def predict_meal():
    """``POST /api/predict-meal`` — return a consumption forecast."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request must be JSON with Content-Type: application/json."}), 400

    errors = {}
    meal_type = data.get("meal_type")
    if not meal_type or not str(meal_type).strip():
        errors["meal_type"] = "meal_type must not be empty."
    else:
        meal_type = str(meal_type).strip()

    food_item = data.get("food_item")
    if not food_item or not str(food_item).strip():
        errors["food_item"] = "food_item must not be empty."
    else:
        food_item = str(food_item).strip()

    raw_guest_count = data.get("guest_count")
    guest_count = None
    if raw_guest_count is None:
        errors["guest_count"] = "guest_count is required."
    else:
        try:
            guest_count = float(raw_guest_count)
            if guest_count <= 0:
                errors["guest_count"] = "guest_count must be greater than 0."
        except (TypeError, ValueError):
            errors["guest_count"] = "guest_count must be a number."

    if errors:
        return jsonify({"error": "Validation failed.", "fields": errors}), 400

    df = pd.DataFrame([{
        "Meal type":   meal_type,
        "Food item":   food_item,
        "Guest count": guest_count,
    }])

    try:
        model = get_model()
        prediction = model.predict(df)
        predicted_consumption = float(prediction[0])
    except Exception:
        current_app.logger.exception("Prediction failed")
        return jsonify({"error": "Prediction failed. Check the server logs for details."}), 500

    safety_margin = predicted_consumption * 0.10
    recommended_quantity = predicted_consumption + safety_margin

    return jsonify({
        "predicted_consumption": round(predicted_consumption, 2),
        "safety_margin":         round(safety_margin, 2),
        "recommended_quantity":  round(recommended_quantity, 2),
    })


def forecast_history():
    """``GET /api/forecast-history`` — return historical actual vs predicted consumption."""
    db = get_db()
    rows = db.execute("SELECT event_at, notes FROM waste_records ORDER BY event_at ASC").fetchall()

    food_items_order = []
    history_by_item = {}
    model = get_model()
    
    for row in rows:
        event_at = row["event_at"]
        notes = row["notes"]
        
        try:
            data = json.loads(notes)
        except (ValueError, TypeError):
            continue
            
        meal_type = data.get("meal_type")
        food_item = data.get("food_item")
        guest_count = data.get("guest_count")
        consumed_quantity = data.get("consumed_quantity")
        
        if None in (meal_type, food_item, guest_count, consumed_quantity):
            continue
            
        try:
            guest_count = float(guest_count)
            consumed_quantity = float(consumed_quantity)
        except (ValueError, TypeError):
            continue

        if food_item not in history_by_item:
            if len(food_items_order) >= 5:
                continue
            food_items_order.append(food_item)
            history_by_item[food_item] = []
            
        df = pd.DataFrame([{
            "Meal type": meal_type,
            "Food item": food_item,
            "Guest count": guest_count
        }])
        
        try:
            prediction = float(model.predict(df)[0])
        except Exception:
            continue
            
        date_str = event_at.split("T")[0]
        
        history_by_item[food_item].append({
            "date": date_str,
            "actual": round(consumed_quantity, 2),
            "predicted": round(prediction, 2)
        })

    items_list = [
        {"food_item": item, "history": history_by_item[item]}
        for item in food_items_order
    ]

    return jsonify({"items": items_list})

