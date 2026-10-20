import io

import numpy as np
from PIL import Image

from app.vision import prediction
from conftest import client, make_app


class FakeFoodModel:
    def predict(self, batch, verbose=0):
        scores = np.zeros((1, 101), dtype=np.float32)
        scores[0, 76] = 0.82  # pizza in the TFDS Food-101 label file
        scores[0, 53] = 0.12  # hamburger
        scores[0, 96] = 0.06  # tacos
        return scores


def _image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (30, 20), "#d76a36").save(stream, format="PNG")
    stream.seek(0)
    return stream


def test_food_prediction_page_and_image_upload(monkeypatch, tmp_path):
    app = make_app(tmp_path, FOOD_CLASSIFIER_MODEL=FakeFoodModel())
    monkeypatch.setattr(prediction, "_prepare_image", lambda image: np.zeros((1, 224, 224, 3)))
    browser = client(app)
    page = browser.get("/food-prediction")
    assert page.status_code == 200
    html = page.text
    assert "<h1>Food image prediction</h1>" in html
    assert 'aria-current="page"' in html
    assert "react/prediction.js" in html
    assert "/api/food-predict" in html

    result = browser.post("/api/food-predict",
                          files={"image": ("sample.png", _image_bytes(), "image/png")})
    assert result.status_code == 200
    assert result.json()["predictions"] == [
        {"label": "Pizza", "confidence": 82.0},
        {"label": "Hamburger", "confidence": 12.0},
        {"label": "Tacos", "confidence": 6.0},
    ]


def test_food_prediction_rejects_missing_and_invalid_uploads(tmp_path):
    browser = client(make_app(tmp_path))
    missing = browser.post("/api/food-predict", data={})
    assert missing.status_code == 400
    assert "Choose a food photo" in missing.json()["error"]
    result = browser.post("/api/food-predict",
                          files={"image": ("fake.jpg", b"not an image", "image/jpeg")})
    assert result.status_code == 400
    assert "not a valid image" in result.json()["error"]
    assert browser.post("/food-prediction").status_code == 405


def test_food101_label_order():
    assert len(prediction.LABELS) == 101
    assert prediction.LABELS[0] == "apple_pie"
    assert prediction.LABELS[76] == "pizza"
    assert prediction.LABELS[-1] == "waffles"
