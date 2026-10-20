"""Temporary image-upload demo for the user's Food-101 MobileNetV2 model."""

from pathlib import Path

import numpy as np
from flask import current_app, jsonify, render_template, url_for
from PIL import ImageOps

from app.image_upload import UploadError, read_uploaded_image


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


def _model_path():
    return Path(
        current_app.config.get(
            "FOOD_CLASSIFIER_MODEL_PATH",
            Path(current_app.root_path).parent / "models" / MODEL_FILENAME,
        )
    )


def _get_model():
    """Load once per Flask app; tests may supply a model through config."""
    model = current_app.config.get("FOOD_CLASSIFIER_MODEL")
    if model is not None:
        return model
    model = current_app.extensions.get("food_classifier_model")
    if model is not None:
        return model

    path = _model_path()
    if not path.is_file():
        raise FileNotFoundError(f"Food classifier model is missing: {path}")

    import tensorflow as tf

    model = tf.keras.models.load_model(path, compile=False)
    if tuple(model.input_shape[1:]) != (224, 224, 3):
        raise ValueError("Food classifier must accept 224 x 224 RGB images.")
    if model.output_shape[-1] != len(LABELS):
        raise ValueError("Food classifier output count does not match Food-101 labels.")
    current_app.extensions["food_classifier_model"] = model
    return model


def _prepare_image(image):
    """Match the training pipeline: RGB, 224-square resize, MobileNetV2 scaling."""
    import tensorflow as tf

    image = ImageOps.exif_transpose(image).convert("RGB")
    pixels = tf.image.resize(np.asarray(image), (224, 224))
    return tf.keras.applications.mobilenet_v2.preprocess_input(
        tf.expand_dims(pixels, axis=0)
    )


def _predict(image):
    scores = np.asarray(_get_model().predict(_prepare_image(image), verbose=0))[0]
    if scores.shape != (len(LABELS),) or not np.all(np.isfinite(scores)):
        raise ValueError("Food classifier returned invalid predictions.")
    top = np.argsort(scores)[-3:][::-1]
    return [
        {"label": LABELS[index].replace("_", " ").title(),
         "confidence": float(scores[index] * 100)}
        for index in top
    ]


def food_prediction():
    """``GET /food-prediction`` - the React image prediction page."""
    return render_template(
        "_react_page.html",
        react_page="prediction",
        active_page="food_prediction",
        heading="Food image prediction",
        description=("Add a photo of one dish to see what the Food-101 model recognises. "
                     "Predictions are not saved as waste records."),
        settings={"apiUrl": url_for("predict_food"), "classCount": len(LABELS)},
    )


def predict_food():
    """``POST /api/food-predict`` - the three most likely Food-101 dishes."""
    try:
        image = read_uploaded_image("Choose a food photo before predicting.")
        predictions = _predict(image)
    except UploadError as error:
        return jsonify({"error": error.message}), error.status
    except (FileNotFoundError, ImportError):
        current_app.logger.exception("Food classifier is unavailable")
        return jsonify({"error": "The food model is unavailable. Check the server setup."}), 503
    except Exception:
        current_app.logger.exception("Food classification failed")
        return jsonify({"error": "Prediction failed. Check the server logs."}), 500
    return jsonify({"predictions": [
        {"label": item["label"], "confidence": round(item["confidence"], 1)}
        for item in predictions
    ]})
