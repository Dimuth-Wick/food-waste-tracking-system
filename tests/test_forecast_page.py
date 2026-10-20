import json
from html import unescape

from app import create_app
from app.forecast.views import FOOD_ITEMS, MEAL_TYPES


def test_forecast_page_mounts_react_app(tmp_path):
    client = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3")}).test_client()
    page = client.get("/forecast")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "<h1>Meal demand forecast</h1>" in html
    assert "<title>Meal forecast · Food Waste Tracking</title>" in html
    assert 'href="/forecast" aria-current="page"' in html
    assert "react/forecast.js" in html
    settings = json.loads(unescape(html.split('data-settings="')[1].split('"')[0]))
    assert settings == {
        "predictUrl": "/api/predict-meal",
        "historyUrl": "/api/forecast-history",
        "mealTypes": MEAL_TYPES,
        "foodItems": FOOD_ITEMS,
    }
