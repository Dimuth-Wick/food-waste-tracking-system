"""Load and expose the trained food-demand forecasting model.

The scikit-learn pipeline is loaded once when the Flask application starts
and stored on ``app.config`` so any view (e.g. the future forecast page)
can retrieve it without reloading from disk on every request.

Expected model inputs (pandas DataFrame columns):
    - Meal type   (str)
    - Food item   (str)
    - Guest count (int / float)

Model output:
    - Consumed quantity (float)
"""

from pathlib import Path

import joblib
from flask import current_app


MODEL_FILENAME = "food_demand_model.pkl"


def _default_model_path(app):
    """Resolve the model file path relative to the project root."""
    # app.root_path points to the ``app/`` package directory.
    project_root = Path(app.root_path).parent
    return project_root / "models" / MODEL_FILENAME


def init_app(app):
    """Load the trained model at startup and attach it to the app config.

    Call this inside the application factory **after** the app is created.
    Raises ``FileNotFoundError`` with a clear message if the ``.pkl`` file
    is missing so the developer gets immediate feedback rather than a
    cryptic error on the first prediction request.

    When ``TESTING`` is enabled or ``ML_MODEL_SKIP`` is set to ``True``
    in the app config the model loading step is silently skipped so that
    existing tests keep working without requiring the ``.pkl`` file.
    """
    if app.config.get("TESTING") or app.config.get("ML_MODEL_SKIP"):
        app.logger.info("ML model loading skipped (TESTING or ML_MODEL_SKIP).")
        return

    model_path = Path(
        app.config.get("ML_MODEL_PATH", _default_model_path(app))
    )

    if not model_path.exists():
        raise FileNotFoundError(
            f"\n\n"
            f"  *** ML model file not found ***\n"
            f"  Expected path : {model_path}\n"
            f"  Please place your trained scikit-learn pipeline at:\n"
            f"      models/{MODEL_FILENAME}\n"
            f"  (relative to the project root)\n"
        )

    app.config["ML_MODEL"] = joblib.load(model_path)
    app.logger.info("ML model loaded from %s", model_path)


def get_model():
    """Return the loaded model from the current Flask application context.

    Usage from any view or module:

        from app.ml import get_model
        model = get_model()
        prediction = model.predict(df)
    """
    model = current_app.config.get("ML_MODEL")
    if model is None:
        raise RuntimeError(
            "The ML model is not available. "
            "Ensure the model file exists and the app was started correctly."
        )
    return model
