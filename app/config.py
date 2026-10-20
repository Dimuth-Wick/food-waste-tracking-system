"""App settings, read from environment variables with local-demo defaults.

DATABASE_URL       SQLAlchemy URL. Defaults to the SQLite file in instance/.
                   For PostgreSQL: postgresql+psycopg://user:password@host/dbname
ML_MODEL_SKIP      Set to 1 to start without loading the forecast model.
"""

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE = PROJECT_ROOT / "instance" / "food_waste.sqlite3"


def load_settings(overrides=None):
    """Return the settings dict. Tests pass overrides, such as a temporary DATABASE.

    Keys other code reads:
        DATABASE_URL, TESTING, ML_MODEL_SKIP, ML_MODEL_PATH, ML_MODEL,
        FOOD_CLASSIFIER_MODEL, FOOD_CLASSIFIER_MODEL_PATH,
        FOOD_COUNTER, FOOD_COUNTER_MODEL_NAME
    """
    settings = {
        "DATABASE_URL": os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DATABASE.as_posix()}"),
        "TESTING": False,
        "ML_MODEL_SKIP": os.environ.get("ML_MODEL_SKIP") == "1",
    }
    overrides = dict(overrides or {})
    # Shortcut for tests and scripts: a plain SQLite file path.
    if "DATABASE" in overrides:
        settings["DATABASE_URL"] = f"sqlite:///{Path(overrides.pop('DATABASE')).as_posix()}"
    settings.update(overrides)
    return settings
