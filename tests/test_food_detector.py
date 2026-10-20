import io
import json
from html import unescape
from pathlib import Path

from PIL import Image

from app import create_app
from app import food_detector


class FakeDetector:
    """Three cupcakes, plus a duplicate box and a part-of-item box to drop."""

    def __init__(self):
        self.calls = []

    def __call__(self, image, item, threshold):
        self.calls.append((item, threshold))
        return [
            {"score": 0.72, "box": [5, 5, 40, 40]},
            {"score": 0.65, "box": [6, 6, 41, 41]},      # same cupcake again
            {"score": 0.74, "box": [50, 5, 90, 40]},
            {"score": 0.31, "box": [60, 10, 75, 25]},    # inside the cupcake above
            {"score": 0.70, "box": [-10, 45, 60, 120]},  # runs off the photo
        ]


def _image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (120, 80), "#d76a36").save(stream, format="PNG")
    stream.seek(0)
    return stream


def _client(tmp_path, detector=None):
    config = {"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3")}
    if detector is not None:
        config["FOOD_DETECTOR"] = detector
    return create_app(config).test_client()


def _post(client, **fields):
    data = {"image": (_image_bytes(), "cupcakes.png"), "item": "cupcake"}
    data.update(fields)
    return client.post("/api/food-count", data=data, content_type="multipart/form-data")


def test_food_counting_page_mounts_react_app(tmp_path):
    page = _client(tmp_path).get("/food-detection")
    assert page.status_code == 200
    html = page.data.decode()
    assert "<h1>Food counting</h1>" in html
    assert 'aria-current="page"' in html
    assert "react/counting.js" in html
    assert "react/react.css" in html
    settings = json.loads(unescape(html.split('data-settings="')[1].split('"')[0]))
    assert settings["apiUrl"] == "/api/food-count"
    assert settings["defaultItem"] == "cupcake"
    assert settings["minConfidence"] == food_detector.MIN_CONFIDENCE


def test_react_bundles_are_built():
    react = Path(create_app({"TESTING": True}).static_folder) / "react"
    for name in ["counting.js", "forecast.js", "prediction.js", "react.css"]:
        assert (react / name).is_file(), f"Run npm run build in frontend/ ({name} missing)"


def test_food_count_api_returns_deduplicated_boxes(tmp_path):
    detector = FakeDetector()
    result = _post(_client(tmp_path, detector), item="  Cupcake ")
    assert result.status_code == 200
    assert detector.calls == [("cupcake", food_detector.MIN_CONFIDENCE / 100)]
    data = result.get_json()
    assert data["item"] == "cupcake"
    assert data["image"] == {"width": 120, "height": 80}
    assert data["minConfidence"] == food_detector.MIN_CONFIDENCE
    assert [found["confidence"] for found in data["detections"]] == [74.0, 72.0, 70.0]
    assert data["detections"][2]["box"] == [0.0, 45.0, 60.0, 80.0]


def test_food_count_api_rejects_bad_item_names(tmp_path):
    detector = FakeDetector()
    client = _client(tmp_path, detector)
    for item in ["", "   ", "<script>", "x" * 41]:
        result = _post(client, item=item)
        assert result.status_code == 400
        assert "Type the food item to count" in result.get_json()["error"]
    assert detector.calls == []


def test_food_count_api_rejects_missing_and_invalid_uploads(tmp_path):
    client = _client(tmp_path, FakeDetector())
    missing = client.post("/api/food-count", data={"item": "cupcake"})
    assert missing.status_code == 400
    assert "Choose a photo" in missing.get_json()["error"]
    invalid = client.post(
        "/api/food-count",
        data={"image": (io.BytesIO(b"not an image"), "fake.jpg"), "item": "cupcake"},
        content_type="multipart/form-data",
    )
    assert invalid.status_code == 400
    assert "not a valid image" in invalid.get_json()["error"]


def test_food_count_api_reports_model_failure(tmp_path):
    def broken(image, item, threshold):
        raise RuntimeError("model crashed")

    result = _post(_client(tmp_path, broken))
    assert result.status_code == 500
    assert "Counting failed" in result.get_json()["error"]


def test_food_count_api_returns_empty_list(tmp_path):
    result = _post(_client(tmp_path, lambda image, item, threshold: []), item="egg")
    assert result.status_code == 200
    assert result.get_json()["detections"] == []


def test_food_count_api_only_accepts_post(tmp_path):
    assert _client(tmp_path).get("/api/food-count").status_code == 405
    assert _client(tmp_path).post("/food-detection").status_code == 405
