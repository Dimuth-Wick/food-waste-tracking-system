"""Food image prediction page: name the dish in a photo with the Food-101 model."""

import logging
from pathlib import Path

import numpy as np
from fastapi import APIRouter, File, Request, UploadFile
from PIL import ImageOps
from pydantic import BaseModel

from app.config import PROJECT_ROOT
from app.vision.uploads import UploadError, read_uploaded_image
from app.web import api_error, render, url_path


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Food image prediction"])


MODEL_FILENAME = "food101_mobilenetv2.keras"
LABELS = tuple(
    line.strip()
    for line in Path(__file__).with_name("food101_labels.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    if line.strip()
)
if len(LABELS) != 101 or len(set(LABELS)) != 101:
    raise RuntimeError("Food-101 labels must contain 101 unique ordered names.")


def _get_model(app):
    """Load once per app; tests may supply a model as settings["FOOD_CLASSIFIER_MODEL"]."""
    settings = app.state.settings
    model = settings.get("FOOD_CLASSIFIER_MODEL") or getattr(app.state, "food_classifier_model", None)
    if model is not None:
        return model

    path = Path(settings.get("FOOD_CLASSIFIER_MODEL_PATH", PROJECT_ROOT / "ml_models" / MODEL_FILENAME))
    if not path.is_file():
        raise FileNotFoundError(f"Food classifier model is missing: {path}")

    import tensorflow as tf

    model = tf.keras.models.load_model(path, compile=False)
    if tuple(model.input_shape[1:]) != (224, 224, 3):
        raise ValueError("Food classifier must accept 224 x 224 RGB images.")
    if model.output_shape[-1] != len(LABELS):
        raise ValueError("Food classifier output count does not match Food-101 labels.")
    app.state.food_classifier_model = model
    return model


def _prepare_image(image):
    """Match the training pipeline: RGB, 224-square resize, MobileNetV2 scaling."""
    import tensorflow as tf

    image = ImageOps.exif_transpose(image).convert("RGB")
    pixels = tf.image.resize(np.asarray(image), (224, 224))
    return tf.keras.applications.mobilenet_v2.preprocess_input(
        tf.expand_dims(pixels, axis=0)
    )


def _predict(app, image):
    scores = np.asarray(_get_model(app).predict(_prepare_image(image), verbose=0))[0]
    if scores.shape != (len(LABELS),) or not np.all(np.isfinite(scores)):
        raise ValueError("Food classifier returned invalid predictions.")
    top = np.argsort(scores)[-3:][::-1]
    return [
        {"label": LABELS[index].replace("_", " ").title(),
         "confidence": float(scores[index] * 100)}
        for index in top
    ]


class Prediction(BaseModel):
    label: str
    confidence: float


class FoodPredictions(BaseModel):
    predictions: list[Prediction]


@router.get("/food-prediction", name="food_prediction", include_in_schema=False)
def food_prediction(request: Request):
    return render(
        request, "_react_page.html",
        react_page="prediction",
        active_page="food_prediction",
        heading="Food image prediction",
        description=("Add a photo of one dish to see what the Food-101 model recognises. "
                     "Predictions are not saved as waste records."),
        settings={"apiUrl": url_path(request.app, "predict_food"), "classCount": len(LABELS)},
    )


@router.post("/api/food-predict", name="predict_food", response_model=FoodPredictions,
             summary="Name the dish in a photo (top three Food-101 guesses)")
def predict_food(request: Request, image: UploadFile | None = File(None)):
    try:
        photo = read_uploaded_image(image, "Choose a food photo before predicting.")
        predictions = _predict(request.app, photo)
    except UploadError as error:
        return api_error(error.message, error.status)
    except (FileNotFoundError, ImportError):
        logger.exception("Food classifier is unavailable")
        return api_error("The food model is unavailable. Check the server setup.", 503)
    except Exception:
        logger.exception("Food classification failed")
        return api_error("Prediction failed. Check the server logs.", 500)
    return FoodPredictions(predictions=[
        Prediction(label=item["label"], confidence=round(item["confidence"], 1))
        for item in predictions
    ])
