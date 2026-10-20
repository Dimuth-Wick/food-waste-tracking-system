"""Flask application factory. Every page and API URL is registered here."""

from pathlib import Path

from flask import Flask

from app.database import connection
from app.forecast import model as forecast_model
from app.forecast import views as forecast
from app.vision import counting, prediction
from app.waste_records import add_record, dashboard, edit_record, record_list


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(DATABASE=str(Path(app.instance_path) / "food_waste.sqlite3"))
    if test_config:
        app.config.update(test_config)

    connection.init_app(app)
    forecast_model.init_app(app)

    # Waste records (Flask templates)
    app.add_url_rule("/", endpoint="dashboard",
                     view_func=dashboard.dashboard, methods=["GET"])
    app.add_url_rule("/records", endpoint="records",
                     view_func=record_list.records, methods=["GET"])
    app.add_url_rule("/records/new", endpoint="new_record",
                     view_func=add_record.new_record, methods=["GET", "POST"])
    app.add_url_rule("/records/<int:record_id>/edit", endpoint="edit_record",
                     view_func=edit_record.edit_record, methods=["GET", "POST"])

    # Meal forecast (React page + JSON APIs)
    app.add_url_rule("/forecast", endpoint="forecast",
                     view_func=forecast.forecast_page, methods=["GET"])
    app.add_url_rule("/api/predict-meal", endpoint="predict_meal",
                     view_func=forecast.predict_meal, methods=["POST"])
    app.add_url_rule("/api/forecast-history", endpoint="forecast_history",
                     view_func=forecast.forecast_history, methods=["GET"])

    # Food image prediction (React page + JSON API)
    app.add_url_rule("/food-prediction", endpoint="food_prediction",
                     view_func=prediction.food_prediction, methods=["GET"])
    app.add_url_rule("/api/food-predict", endpoint="predict_food",
                     view_func=prediction.predict_food, methods=["POST"])

    # Food counting (React page + JSON API)
    app.add_url_rule("/food-counting", endpoint="food_counting",
                     view_func=counting.food_counting, methods=["GET"])
    app.add_url_rule("/api/food-count", endpoint="count_food",
                     view_func=counting.count_food, methods=["POST"])

    return app
