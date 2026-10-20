import io

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
    return client.post("/food-detection", data=data, content_type="multipart/form-data")


def test_food_counting_page_and_image_upload(tmp_path):
    detector = FakeDetector()
    client = _client(tmp_path, detector)
    page = client.get("/food-detection")
    assert page.status_code == 200
    assert b"Food counting" in page.data
    assert b'value="cupcake"' in page.data

    result = _post(client, item="  Cupcake ", threshold="20")
    assert result.status_code == 200
    assert detector.calls == [("cupcake", 0.2)]
    html = result.data.decode()
    assert '<p class="detection-count">3</p>' in html
    assert "Number of “cupcake” found" in html
    assert html.index("74.0%") < html.index("72.0%") < html.index("70.0%")
    assert "65.0%" not in html and "31.0%" not in html
    assert "data:image/jpeg;base64," in html


def test_food_counting_merges_duplicates_and_clamps_boxes(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3"),
                      "FOOD_DETECTOR": FakeDetector()})
    with app.app_context():
        found = food_detector._count(Image.new("RGB", (120, 80)), "cupcake", 30)
    assert [round(item["confidence"]) for item in found] == [74, 72, 70]
    assert found[2]["box"] == (0.0, 45.0, 60.0, 80.0)
    food_detector._draw_boxes(Image.new("RGB", (120, 80)), found)


def test_food_counting_ignores_unknown_threshold(tmp_path):
    detector = FakeDetector()
    _post(_client(tmp_path, detector), threshold="3")
    assert detector.calls == [("cupcake", food_detector.DEFAULT_THRESHOLD / 100)]


def test_food_counting_rejects_bad_item_names(tmp_path):
    detector = FakeDetector()
    client = _client(tmp_path, detector)
    for item in ["", "   ", "<script>", "x" * 41]:
        result = _post(client, item=item)
        assert result.status_code == 400
        assert b"Type the food item to count" in result.data
    assert detector.calls == []


def test_food_counting_rejects_missing_and_invalid_uploads(tmp_path):
    client = _client(tmp_path, FakeDetector())
    assert client.post("/food-detection", data={"item": "cupcake"}).status_code == 400
    result = client.post(
        "/food-detection",
        data={"image": (io.BytesIO(b"not an image"), "fake.jpg"), "item": "cupcake"},
        content_type="multipart/form-data",
    )
    assert result.status_code == 400
    assert b"not a valid image" in result.data


def test_food_counting_shows_empty_state(tmp_path):
    result = _post(_client(tmp_path, lambda image, item, threshold: []), item="egg")
    assert result.status_code == 200
    assert b'<p class="detection-count">0</p>' in result.data
    assert "No “egg” found at 30%+ confidence".encode() in result.data
