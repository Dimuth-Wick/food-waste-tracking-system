import io

import numpy as np
from PIL import Image

from app import create_app
from app.vision import prediction


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
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "test.sqlite3"),
        "FOOD_CLASSIFIER_MODEL": FakeFoodModel(),
    })
    monkeypatch.setattr(prediction, "_prepare_image", lambda image: np.zeros((1, 224, 224, 3)))
    client = app.test_client()
    page = client.get("/food-prediction")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "<h1>Food image prediction</h1>" in html
    assert 'aria-current="page"' in html
    assert "react/prediction.js" in html
    assert "/api/food-predict" in html

    result = client.post(
        "/api/food-predict",
        data={"image": (_image_bytes(), "sample.png")},
        content_type="multipart/form-data",
    )
    assert result.status_code == 200
    assert result.get_json()["predictions"] == [
        {"label": "Pizza", "confidence": 82.0},
        {"label": "Hamburger", "confidence": 12.0},
        {"label": "Tacos", "confidence": 6.0},
    ]


def test_food_prediction_rejects_missing_and_invalid_uploads(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3")})
    client = app.test_client()
    missing = client.post("/api/food-predict", data={})
    assert missing.status_code == 400
    assert "Choose a food photo" in missing.get_json()["error"]
    result = client.post(
        "/api/food-predict",
        data={"image": (io.BytesIO(b"not an image"), "fake.jpg")},
        content_type="multipart/form-data",
    )
    assert result.status_code == 400
    assert "not a valid image" in result.get_json()["error"]
    assert client.post("/food-prediction").status_code == 405


def test_food101_label_order():
    assert len(prediction.LABELS) == 101
    assert prediction.LABELS[0] == "apple_pie"
    assert prediction.LABELS[76] == "pizza"
    assert prediction.LABELS[-1] == "waffles"
