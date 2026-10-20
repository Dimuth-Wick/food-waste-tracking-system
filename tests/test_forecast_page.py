import json
from html import unescape

from app.forecast.views import FOOD_ITEMS, MEAL_TYPES
from conftest import client, make_app


class FakeForecastModel:
    """Predicts 0.25 kg per guest and records each call."""

    def __init__(self):
        self.calls = []

    def predict(self, frame):
        self.calls.append(frame.to_dict("records"))
        return [row["Guest count"] * 0.25 for row in frame.to_dict("records")]


def test_forecast_page_mounts_react_app(tmp_path):
    page = client(make_app(tmp_path)).get("/forecast")
    assert page.status_code == 200
    html = page.text
    assert "<h1>Meal demand forecast</h1>" in html
    assert "<title>Meal forecast · Wastewise</title>" in html
    assert 'href="/forecast" aria-current="page"' in html
    assert "react/forecast.js" in html
    settings = json.loads(unescape(html.split('data-settings="')[1].split('"')[0]))
    assert settings == {
        "predictUrl": "/api/predict-meal",
        "historyUrl": "/api/forecast-history",
        "mealTypes": MEAL_TYPES,
        "foodItems": FOOD_ITEMS,
    }


def test_predict_meal_adds_safety_margin(tmp_path):
    model = FakeForecastModel()
    browser = client(make_app(tmp_path, ML_MODEL=model))
    result = browser.post("/api/predict-meal", json={
        "meal_type": " Dinner ", "food_item": "Fried rice", "guest_count": "150"})
    assert result.status_code == 200
    assert result.json() == {"predicted_consumption": 37.5, "safety_margin": 3.75,
                             "recommended_quantity": 41.25}
    assert model.calls == [[{"Meal type": "Dinner", "Food item": "Fried rice", "Guest count": 150.0}]]


def test_predict_meal_explains_bad_input(tmp_path):
    browser = client(make_app(tmp_path, ML_MODEL=FakeForecastModel()))
    invalid = browser.post("/api/predict-meal", json={"meal_type": " ", "guest_count": -3})
    assert invalid.status_code == 400
    assert invalid.json() == {"error": "Validation failed.", "fields": {
        "meal_type": "meal_type must not be empty.",
        "food_item": "food_item must not be empty.",
        "guest_count": "guest_count must be greater than 0.",
    }}
    assert browser.post("/api/predict-meal", json={
        "meal_type": "Lunch", "food_item": "Salad", "guest_count": "many"}
    ).json()["fields"] == {"guest_count": "guest_count must be a number."}

    not_json = browser.post("/api/predict-meal", content=b"meal=lunch",
                            headers={"content-type": "text/plain"})
    assert not_json.status_code == 400
    assert "must be JSON" in not_json.json()["error"]


def test_forecast_history_compares_actual_with_predicted(tmp_path):
    from datetime import datetime, timezone

    from app.database.queries import create_user, create_waste_record
    from conftest import add_lookups, database

    model = FakeForecastModel()
    app = make_app(tmp_path, ML_MODEL=model)
    with database(app) as db:
        add_lookups(db, {"areas": ["Buffet"], "categories": ["Rice"], "reasons": ["Overproduction"]})
        user = create_user(db, name="Staff", username="staff", password="test", role="entry")
        for day, guests, eaten in ((1, 100, 24.0), (2, 120, 31.0)):
            create_waste_record(
                db, event_at=datetime(2026, 10, day, 12, tzinfo=timezone.utc), area_id=1,
                category_id=1, reason_id=1, quantity_kg=1, user_id=user.id,
                notes=json.dumps({"meal_type": "Dinner", "food_item": "Fried rice",
                                  "guest_count": guests, "consumed_quantity": eaten}),
            )
        create_waste_record(db, event_at=datetime(2026, 10, 3, tzinfo=timezone.utc), area_id=1,
                            category_id=1, reason_id=1, quantity_kg=1, user_id=user.id,
                            notes="Plain note, not service details")

    history = client(app).get("/api/forecast-history")
    assert history.status_code == 200
    assert history.json() == {"items": [{"food_item": "Fried rice", "history": [
        {"date": "2026-10-01", "meal_type": "Dinner", "actual": 24.0, "predicted": 25.0},
        {"date": "2026-10-02", "meal_type": "Dinner", "actual": 31.0, "predicted": 30.0},
    ]}]}
    assert len(model.calls) == 1  # one model call for every point
