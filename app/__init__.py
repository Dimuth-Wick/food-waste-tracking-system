from pathlib import Path

from flask import Flask

from app import db
from app import ml
from app import dashboard as dashboard_view
from app import entry
from app import edit_record as record_edit
from app import record_list
from app import forecast
from app import food_classifier
from app import food_detector


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(DATABASE=str(Path(app.instance_path) / "food_waste.sqlite3"))
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    ml.init_app(app)

    app.add_url_rule("/", endpoint="dashboard", view_func=dashboard_view.dashboard,
                     methods=["GET"])

    app.add_url_rule("/records", view_func=record_list.records, methods=["GET"])

    app.add_url_rule("/records/new", view_func=entry.new_record, methods=["GET", "POST"])

    app.add_url_rule("/records/<int:record_id>/edit", endpoint="edit_record",
                     view_func=record_edit.edit_record, methods=["GET", "POST"])

    app.add_url_rule("/forecast", endpoint="forecast",
                     view_func=forecast.forecast_page, methods=["GET"])

    app.add_url_rule("/api/predict-meal", endpoint="predict_meal",
                     view_func=forecast.predict_meal, methods=["POST"])

    app.add_url_rule("/api/forecast-history", endpoint="forecast_history",
                     view_func=forecast.forecast_history, methods=["GET"])

    app.add_url_rule("/food-prediction", endpoint="food_prediction",
                     view_func=food_classifier.food_prediction, methods=["GET"])

    app.add_url_rule("/api/food-predict", endpoint="predict_food",
                     view_func=food_classifier.predict_food, methods=["POST"])

    app.add_url_rule("/food-detection", endpoint="food_detection",
                     view_func=food_detector.food_detection, methods=["GET"])

    app.add_url_rule("/api/food-count", endpoint="count_food",
                     view_func=food_detector.count_food, methods=["POST"])

    return app
