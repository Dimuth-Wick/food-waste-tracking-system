"""Load the trained food-demand forecasting model once, at startup.

The scikit-learn pipeline is stored on ``app.state.forecast_model``.

Expected model inputs (pandas DataFrame columns):
    - Meal type   (str)
    - Food item   (str)
    - Guest count (int / float)

Model output:
    - Consumed quantity (float)
"""

import logging
from pathlib import Path

import joblib
from fastapi import FastAPI, Request

from app.config import PROJECT_ROOT


logger = logging.getLogger(__name__)
MODEL_FILENAME = "food_demand_model.pkl"


def init_app(app: FastAPI) -> None:
    """Load the model into app.state.

    Skipped when TESTING or ML_MODEL_SKIP is set, so tests and pages that do
    not need the forecast can run without the .pkl file. A model object can
    also be passed directly as settings["ML_MODEL"].
    """
    settings = app.state.settings
    app.state.forecast_model = settings.get("ML_MODEL")
    if app.state.forecast_model is not None or settings.get("TESTING") or settings.get("ML_MODEL_SKIP"):
        return

    model_path = Path(settings.get("ML_MODEL_PATH", PROJECT_ROOT / "ml_models" / MODEL_FILENAME))
    if not model_path.exists():
        raise FileNotFoundError(
            f"\n\n"
            f"  *** ML model file not found ***\n"
            f"  Expected path : {model_path}\n"
            f"  Please place your trained scikit-learn pipeline at:\n"
            f"      ml_models/{MODEL_FILENAME}\n"
            f"  (relative to the project root)\n"
        )
    app.state.forecast_model = joblib.load(model_path)
    logger.info("Forecast model loaded from %s", model_path)


def get_model(request: Request):
    """Return the loaded forecast model, or raise if it was not loaded."""
    model = request.app.state.forecast_model
    if model is None:
        raise RuntimeError(
            "The ML model is not available. "
            "Ensure the model file exists and the app was started correctly."
        )
    return model
