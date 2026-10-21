"""Camera capture milestones 2 and 3: photos stored in the database, then counted in the background."""

import io
import json

from PIL import Image
from sqlalchemy import update

from app.camera.store import DEFAULT_FOODS, combined_counts, ensure_camera_tables, photo_counts, sync_from_disk
from app.database.tables import CameraFoodRow
from conftest import client, database, make_app, scalar, sql
from test_camera import STATIONS, FakeCamera


class FakeOwl:
    """Answers one label at a time, like the real detector's simple form, with boxes in pixels."""

    def __init__(self, fail=False):
        self.fail, self.labels = fail, []

    def __call__(self, image, label, threshold):
        self.labels.append(label)
        if self.fail:
            raise RuntimeError("model crashed")
        found = {
            "egg": [{"score": 0.81, "box": [5, 5, 30, 30]}, {"score": 0.70, "box": [35, 5, 60, 30]}],
            "donut": [{"score": 0.74, "box": [65, 40, 110, 75]}, {"score": 0.25, "box": [5, 45, 25, 70]}],
            "cupcake": [{"score": 0.60, "box": [66, 41, 109, 74]}],   # the same item as the donut, weaker
        }.get(label, [])
        return [match for match in found if match["score"] >= threshold]


def jpeg(size=(120, 80)) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, "#d76a36").save(stream, format="JPEG")
    return stream.getvalue()


def camera_app(tmp_path, owl=None, camera=None, cameras=STATIONS[:1]):
    return make_app(tmp_path, CAMERA_SOURCES=cameras, CAPTURE_DIR=tmp_path / "captures", FRAME_GRABBER=camera or (lambda url: jpeg()),
                    CAPTURE_RETRY_DELAY=0, PHOTO_GAP_SECONDS=0, FOOD_COUNTER=owl or FakeOwl())


def run_now(app, meal="breakfast", kind="start"):
    return client(app).post("/api/captures/run-now", json={"meal": meal, "kind": kind})


def test_photos_are_stored_and_queued_but_not_counted_during_the_request(tmp_path):
    app = camera_app(tmp_path)
    body = run_now(app).json()
    assert len(body["capture_ids"]) == 4
    with database(app) as db:
        rows = sql(db, "SELECT meal_type, kind, station, status, count_status, file_path FROM captures ORDER BY id").all()
    assert len(rows) == 4
    assert all(row[:5] == ("breakfast", "start", "Station 1", "ok", "pending") for row in rows)
    assert [row[5] for row in rows] == [photo["file"] for photo in body["photos"]]
    assert not app.state.counting_worker.running            # nothing runs in the background during tests


def test_failed_photos_are_stored_with_the_reason(tmp_path):
    app = camera_app(tmp_path, camera=FakeCamera(down=[STATIONS[1]["url"]]), cameras=STATIONS)
    run_now(app, "lunch", "end")
    with database(app) as db:
        rows = sql(db, "SELECT station, status, count_status, file_path, error FROM captures ORDER BY id").all()
    assert rows[0][:3] == ("Station 1", "ok", "pending")
    assert rows[1][:4] == ("Station 2", "failed", "not_counted", None) and "could not be opened" in rows[1][4]


def test_the_worker_counts_every_food_in_one_photo(tmp_path):
    owl = FakeOwl()
    app = camera_app(tmp_path, owl=owl)
    capture_id = run_now(app).json()["capture_ids"][0]
    assert app.state.counting_worker.process_pending() == 4
    assert set(owl.labels) == {label for label, _, _ in DEFAULT_FOODS}   # one look per food, no typing

    with database(app) as db:
        counts = photo_counts(db, [capture_id])[capture_id]
        status = scalar(db, "SELECT count_status FROM captures WHERE id = :id", id=capture_id)
        donut = json.loads(scalar(db, "SELECT detections FROM capture_counts WHERE capture_id = :id AND label = 'donut'",
                                  id=capture_id))
        model = scalar(db, "SELECT DISTINCT model_name FROM capture_counts")
    assert status == "counted"
    # The cupcake box is the donut again, so it is counted once, as a donut. Zeros are kept.
    assert counts == {"egg": 2, "donut": 1, "cupcake": 0, "bread roll": 0, "apple": 0}
    assert [match["confidence"] for match in donut] == [74.0, 25.0]   # the weak match is kept for training, not counted
    assert model == "google/owlv2-base-patch16-ensemble"

    path = next((tmp_path / "captures").rglob("*.jpg"))
    sidecar = json.loads(path.with_suffix(".json").read_text())
    assert sidecar["foods"]["egg"]["count"] == 2 and sidecar["kind"] == "start" and sidecar["image_size"] == [120, 80]


def test_large_camera_photos_are_shrunk_for_counting_and_boxes_scaled_back(tmp_path):
    seen = []

    def owl(image, label, threshold):
        seen.append(image.size)
        return [{"score": 0.9, "box": [100, 100, 200, 200]}] if label == "egg" else []

    app = camera_app(tmp_path, owl=owl, camera=lambda url: jpeg((2560, 1440)))
    capture_id = run_now(app).json()["capture_ids"][0]
    app.state.counting_worker.process_pending()
    assert max(seen[0]) == 1280                                # the model never sees the full-size frame
    with database(app) as db:
        egg = json.loads(scalar(db, "SELECT detections FROM capture_counts WHERE capture_id = :id AND label = 'egg'",
                                id=capture_id))
    assert egg[0]["box"] == [200.0, 200.0, 400.0, 400.0]       # back in the 2560 x 1440 photo


def test_a_station_without_foods_needs_setup_and_counts_nothing(tmp_path):
    owl = FakeOwl()
    app = camera_app(tmp_path, owl=owl)
    run_now(app)
    with database(app) as db:
        db.execute(update(CameraFoodRow).values(active=0))
        db.commit()
    app.state.counting_worker.process_pending()
    with database(app) as db:
        assert {row[0] for row in sql(db, "SELECT count_status FROM captures").all()} == {"needs_setup"}
        assert scalar(db, "SELECT COUNT(*) FROM capture_counts") == 0
    assert owl.labels == []


def test_a_station_can_have_its_own_food_list(tmp_path):
    app = camera_app(tmp_path)
    with database(app) as db:
        ensure_camera_tables(db)
        db.add(CameraFoodRow(station="Station 1", count_label="egg", dish="Egg curry", kg_per_piece=0.06, active=1))
        db.commit()
    capture_id = run_now(app).json()["capture_ids"][0]
    app.state.counting_worker.process_pending()
    with database(app) as db:
        assert photo_counts(db, [capture_id])[capture_id] == {"egg": 2}


def test_a_counting_failure_is_stored_and_the_worker_keeps_going(tmp_path):
    app = camera_app(tmp_path, owl=FakeOwl(fail=True))
    run_now(app)
    assert app.state.counting_worker.process_pending() == 4   # every photo was tried
    with database(app) as db:
        rows = sql(db, "SELECT count_status, count_error FROM captures").all()
    assert all(status == "failed" and "RuntimeError" in error for status, error in rows)


def test_photos_already_on_disk_are_picked_up_once(tmp_path):
    folder = tmp_path / "captures" / "2026-10-21" / "breakfast" / "start"
    folder.mkdir(parents=True)
    for name in ("Station-1_142343.jpg", "Station-1_142343-2.jpg"):
        (folder / name).write_bytes(jpeg())
    (folder / "notes.txt").write_text("not a photo")
    (folder.parent / "middle").mkdir()
    (folder.parent / "middle" / "Station-1_100000.jpg").write_bytes(jpeg())    # not start or end: ignored
    app = camera_app(tmp_path)
    with database(app) as db:
        added = sync_from_disk(db, tmp_path / "captures", STATIONS, "Asia/Colombo")
        assert len(added) == 2
        assert sync_from_disk(db, tmp_path / "captures", STATIONS, "Asia/Colombo") == []   # no duplicates
        row = sql(db, "SELECT captured_at, capture_date, meal_type, kind, station, count_status FROM captures "
                      "ORDER BY id LIMIT 1").one()
    # 14:23:43 in Sri Lanka is 08:53:43 UTC; the station name comes back from the configured cameras.
    assert tuple(row) == ("2026-10-21T08:53:43Z", "2026-10-21", "breakfast", "start", "Station 1", "pending")


def test_default_foods_are_added_once(tmp_path):
    app = make_app(tmp_path)
    with database(app) as db:
        ensure_camera_tables(db)
        ensure_camera_tables(db)
        labels = [row[0] for row in sql(db, "SELECT count_label FROM camera_foods ORDER BY id").all()]
    assert labels == [label for label, _, _ in DEFAULT_FOODS]


def test_start_uses_the_highest_count_and_end_the_lowest():
    photos = [{"egg": 8, "donut": 3}, {"egg": 6, "donut": 3}, {"egg": 9}, {"egg": 7, "donut": 2}]
    assert combined_counts(photos, "start") == {"donut": 3, "egg": 9}
    assert combined_counts(photos, "end") == {"donut": 0, "egg": 6}   # a photo without donuts saw none
