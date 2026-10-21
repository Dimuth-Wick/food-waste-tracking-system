"""Buffet meal checks: counts from the start and end photos become waste and forecast history."""

import json
from html import unescape

from sqlalchemy import text

from app.database.seed import seed_demo_data
from conftest import client, database, make_app, scalar
from test_forecast_page import FakeForecastModel


def _app(tmp_path):
    app = make_app(tmp_path, ML_MODEL=FakeForecastModel())
    with database(app) as db:
        seed_demo_data(db)
        # Databases made before meal checks existed do not have the table; the app adds it.
        db.execute(text("DROP TABLE IF EXISTS meal_checks"))
        db.commit()
    return app


def _check(app, **changes):
    with database(app) as db:
        body = {
            "food_item": "Bread", "count_label": "bun", "meal_type": "Breakfast",
            "ended_at": "2026-10-20T10:00",
            "area_id": scalar(db, "SELECT id FROM areas WHERE name = 'Buffet'"),
            "reason_id": scalar(db, "SELECT id FROM reasons WHERE name = 'Overproduction'"),
            "start_count": 14, "end_count": 2, "short_count": 0,
            "kg_per_piece": 0.06, "guest_count": 40,
        }
    return {**body, **changes}


def test_counting_page_offers_the_save_form(tmp_path):
    html = client(_app(tmp_path)).get("/food-counting").text
    settings = json.loads(unescape(html.split('data-settings="')[1].split('"')[0]))
    meal = settings["mealCheck"]
    assert meal["saveUrl"] == "/api/meal-checks"
    assert "Bread" in meal["foodItems"] and meal["mealTypes"] == ["Breakfast", "Lunch", "Dinner"]
    assert "Ran out (shortage)" not in [reason["name"] for reason in meal["reasons"]]
    assert meal["pieceWeights"] == {}


def test_leftovers_become_a_waste_record_and_eaten_food_feeds_the_forecast(tmp_path):
    app = _app(tmp_path)
    browser = client(app)
    saved = browser.post("/api/meal-checks", json=_check(app))
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert result["waste_kg"] == 0.12 and result["eaten_kg"] == 0.72 and result["short_kg"] == 0
    assert result["overview_url"] == f"/days/2026-10-20?created={result['waste_record_id']}"

    with database(app) as db:
        kg = scalar(db, "SELECT quantity_kg FROM waste_records WHERE id = :id", id=result["waste_record_id"])
        assert round(kg, 3) == 0.12

    overview = browser.get(result["overview_url"]).text
    assert "saved successfully" in overview
    assert "Bun: 2 of 14 left" in overview and "From photos" in overview   # the counted food, not just the dish

    history = browser.get("/api/forecast-history").json()["items"]
    assert history[0]["food_item"] == "Bread"                 # most recently served first
    assert history[0]["history"] == [
        {"date": "2026-10-20", "meal_type": "Breakfast", "actual": 0.72, "predicted": 10.0}]

    # The weight per piece is remembered for next time.
    html = browser.get("/food-counting").text
    settings = json.loads(unescape(html.split('data-settings="')[1].split('"')[0]))
    assert settings["mealCheck"]["pieceWeights"] == {"Bread": 0.06}


def test_nothing_left_and_a_shortage(tmp_path):
    app = _app(tmp_path)
    result = client(app).post("/api/meal-checks", json=_check(app, end_count=0, short_count=5)).json()
    assert result["waste_record_id"] is None                  # nothing was thrown away
    assert result["short_kg"] == 0.3
    with database(app) as db:
        reason = scalar(db, "SELECT r.name FROM waste_records w JOIN reasons r ON r.id = w.reason_id "
                            "WHERE w.id = :id", id=result["shortage_record_id"])
        assert reason == "Ran out (shortage)"


def test_bad_counts_are_rejected_without_saving(tmp_path):
    app = _app(tmp_path)
    browser = client(app)
    bad = browser.post("/api/meal-checks", json=_check(app, end_count=20, kg_per_piece=0,
                                                       guest_count=0, food_item="Pizza"))
    assert bad.status_code == 400
    fields = bad.json()["fields"]
    assert set(fields) == {"end_count", "kg_per_piece", "guest_count", "food_item"}
    with database(app) as db:
        assert scalar(db, "SELECT COUNT(*) FROM waste_records") == 3   # only the seeded records
