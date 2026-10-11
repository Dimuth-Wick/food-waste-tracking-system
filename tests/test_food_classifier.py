import io

import numpy as np
from PIL import Image

from app import create_app
from app import food_classifier


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
    monkeypatch.setattr(food_classifier, "_prepare_image", lambda image: np.zeros((1, 224, 224, 3)))
    client = app.test_client()
    page = client.get("/food-prediction")
    assert page.status_code == 200
    assert b"Food image prediction" in page.data
    assert b'aria-current="page"' in page.data

    result = client.post(
        "/food-prediction",
        data={"image": (_image_bytes(), "sample.png")},
        content_type="multipart/form-data",
    )
    assert result.status_code == 200
    assert b"Pizza" in result.data
    assert b"82.0%" in result.data
    assert b"Hamburger" in result.data
    assert b"data:image/jpeg;base64," in result.data


def test_food_prediction_rejects_missing_and_invalid_uploads(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3")})
    client = app.test_client()
    assert client.post("/food-prediction", data={}).status_code == 400
    result = client.post(
        "/food-prediction",
        data={"image": (io.BytesIO(b"not an image"), "fake.jpg")},
        content_type="multipart/form-data",
    )
    assert result.status_code == 400
    assert b"not a valid image" in result.data


def test_food101_label_order():
    assert len(food_classifier.LABELS) == 101
    assert food_classifier.LABELS[0] == "apple_pie"
    assert food_classifier.LABELS[76] == "pizza"
    assert food_classifier.LABELS[-1] == "waffles"
