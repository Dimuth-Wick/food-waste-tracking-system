import io

from PIL import Image

from app import create_app
from app import food_detector


class FakeDetector:
    def __init__(self):
        self.thresholds = []

    def __call__(self, image, threshold):
        self.thresholds.append(threshold)
        return [
            {"label": "cup", "score": 0.75, "box": [2, 2, 12, 12]},
            {"label": "pizza", "score": 0.93, "box": [5, 4, 80, 50]},
            {"label": "dining table", "score": 0.81, "box": [-10, 30, 200, 90]},
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


def test_food_detection_page_and_image_upload(tmp_path):
    detector = FakeDetector()
    client = _client(tmp_path, detector)
    page = client.get("/food-detection")
    assert page.status_code == 200
    assert b"Food detection" in page.data
    assert b"hustvl/yolos-small" in page.data

    result = client.post(
        "/food-detection",
        data={"image": (_image_bytes(), "table.png"), "threshold": "50"},
        content_type="multipart/form-data",
    )
    assert result.status_code == 200
    assert detector.thresholds == [0.5]
    html = result.data.decode()
    assert html.index("Pizza") < html.index("Dining Table") < html.index("Cup")
    assert "93.0%" in html
    assert "3 objects found at 50%+ confidence" in html
    assert "1 of them food" in html
    assert "detection-tag-tableware" in html
    assert "data:image/jpeg;base64," in html


def test_food_detection_clamps_boxes_and_groups_labels(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3"),
                      "FOOD_DETECTOR": FakeDetector()})
    with app.app_context():
        detections = food_detector._detect(Image.new("RGB", (120, 80)), 70)
    assert [item["label"] for item in detections] == ["Pizza", "Dining Table", "Cup"]
    assert [item["group"] for item in detections] == ["food", "tableware", "tableware"]
    assert detections[1]["box"] == (0.0, 30.0, 120.0, 80.0)
    food_detector._draw_boxes(Image.new("RGB", (120, 80)), detections)


def test_food_detection_ignores_unknown_threshold(tmp_path):
    detector = FakeDetector()
    client = _client(tmp_path, detector)
    client.post(
        "/food-detection",
        data={"image": (_image_bytes(), "table.png"), "threshold": "3"},
        content_type="multipart/form-data",
    )
    assert detector.thresholds == [food_detector.DEFAULT_THRESHOLD / 100]


def test_food_detection_rejects_missing_and_invalid_uploads(tmp_path):
    client = _client(tmp_path, FakeDetector())
    assert client.post("/food-detection", data={}).status_code == 400
    result = client.post(
        "/food-detection",
        data={"image": (io.BytesIO(b"not an image"), "fake.jpg")},
        content_type="multipart/form-data",
    )
    assert result.status_code == 400
    assert b"not a valid image" in result.data


def test_food_detection_shows_empty_state(tmp_path):
    client = _client(tmp_path, lambda image, threshold: [])
    result = client.post(
        "/food-detection",
        data={"image": (_image_bytes(), "empty.png")},
        content_type="multipart/form-data",
    )
    assert result.status_code == 200
    assert b"No objects found at 70%+ confidence" in result.data
