"""Automatic camera capture (milestone 1): config, schedule, saved photos, failures, run-now."""

import io
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from app.camera.capture import CameraError, CameraUnavailable, CaptureBusy, CaptureService, safe_url, slug
from app.camera.schedule import SingleInstanceLock, build_scheduler, meal_at, run_event, start_scheduler
from app.config import load_settings, parse_camera_sources, parse_meal_schedule
from conftest import client, make_app


def jpeg() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (64, 48), "#d76a36").save(stream, format="JPEG")
    return stream.getvalue()


class FakeCamera:
    """Stands in for OpenCV: returns a small JPEG, or fails for the addresses in ``down``."""

    def __init__(self, down=()):
        self.down, self.calls = set(down), []

    def __call__(self, url):
        self.calls.append(url)
        if url in self.down:
            raise CameraError("The camera could not be opened. Check that it is on and reachable.")
        return jpeg()


STATIONS = [{"name": "Station 1", "url": "http://cam-one.test:8080/video"},
            {"name": "Station 2", "url": "http://cam-two.test:8080/video"}]


def settings_for(tmp_path, cameras, **changes):
    return load_settings({"TESTING": True, "DATABASE": str(tmp_path / "x.sqlite3"), "CAPTURE_DIR": tmp_path / "captures",
                          "CAMERA_SOURCES": cameras, "CAPTURE_RETRY_DELAY": 0, **changes})


def service_for(tmp_path, cameras, grabber=None, **changes):
    grabber = grabber or FakeCamera()
    return CaptureService(settings_for(tmp_path, cameras, FRAME_GRABBER=grabber, **changes), sleep=lambda _: None), grabber


# ---- config ---------------------------------------------------------------------------------

def test_defaults_match_the_agreed_schedule(monkeypatch):
    for name in ("MEAL_SCHEDULE", "CAMERA_SOURCES", "PHOTOS_PER_CAPTURE", "TIMEZONE", "CAPTURE_TEST_MODE"):
        monkeypatch.delenv(name, raising=False)
    settings = load_settings({"TESTING": True})
    assert settings["TIMEZONE"] == "Asia/Colombo"
    assert settings["MEAL_SCHEDULE"]["breakfast"] == {"start": "06:00", "end": "10:00"}
    assert settings["PHOTOS_PER_CAPTURE"] == 4
    assert settings["CAMERA_SOURCES"] == []                  # no address is built into the code
    assert settings["CAPTURE_TEST_MODE"] is False


def test_settings_come_from_environment_variables(monkeypatch):
    monkeypatch.setenv("CAMERA_SOURCES", "Station 1=http://192.168.8.10:8080/video; Station 2=rtsp://user:secret@10.0.0.5/live")
    monkeypatch.setenv("MEAL_SCHEDULE", "breakfast=05:30/09:30;lunch=12:15/14:00")
    monkeypatch.setenv("CAPTURE_TEST_MODE", "1")
    monkeypatch.setenv("PHOTOS_PER_CAPTURE", "3")
    settings = load_settings({"TESTING": True})
    assert [camera["name"] for camera in settings["CAMERA_SOURCES"]] == ["Station 1", "Station 2"]
    assert settings["CAMERA_SOURCES"][1]["url"] == "rtsp://user:secret@10.0.0.5/live"
    assert settings["MEAL_SCHEDULE"] == {"breakfast": {"start": "05:30", "end": "09:30"},
                                         "lunch": {"start": "12:15", "end": "14:00"}}
    assert settings["CAPTURE_TEST_MODE"] is True and settings["PHOTOS_PER_CAPTURE"] == 3


@pytest.mark.parametrize("text", ["breakfast=10:00/06:00", "breakfast=6:00/10:00", "breakfast", "lunch=12:00/25:00"])
def test_bad_meal_schedules_are_rejected(text):
    with pytest.raises(ValueError):
        parse_meal_schedule(text)


def test_bad_camera_sources_are_rejected_without_leaking_the_address():
    for text in ("Station 1=ftp://host/video", "=http://host/video", "A=http://h/v;a=http://h/w"):
        with pytest.raises(ValueError):
            parse_camera_sources(text)
    with pytest.raises(ValueError) as error:
        parse_camera_sources("Station 1=ftp://user:topsecret@host/video")
    assert "topsecret" not in str(error.value)
    assert parse_camera_sources("Station 1=0") == [{"name": "Station 1", "url": "0"}]   # a webcam


def test_addresses_are_masked_in_logs():
    assert safe_url("rtsp://user:topsecret@10.0.0.5:554/live?token=abc") == "rtsp://10.0.0.5:554/live"
    assert safe_url("0") == "webcam 0"
    assert slug("Station 1") == "Station-1" and slug("../../etc") == "etc"


# ---- schedule -------------------------------------------------------------------------------

def test_scheduler_has_a_start_and_end_job_for_every_meal(tmp_path):
    service, _ = service_for(tmp_path, STATIONS)
    scheduler = build_scheduler(service_settings := settings_for(tmp_path, STATIONS), service)
    scheduler.start(paused=True)                              # paused: jobs are registered but nothing runs
    try:
        jobs = {job.id: job for job in scheduler.get_jobs()}
    finally:
        scheduler.shutdown(wait=False)
    assert set(jobs) == {f"{meal}-{kind}" for meal in ("breakfast", "lunch", "dinner") for kind in ("start", "end")}
    breakfast_start = jobs["breakfast-start"]
    assert str(breakfast_start.trigger.timezone) == "Asia/Colombo"
    fields = {field.name: str(field) for field in breakfast_start.trigger.fields}
    assert fields["hour"] == "6" and fields["minute"] == "0"
    assert breakfast_start.misfire_grace_time == 300 and breakfast_start.max_instances == 1
    assert str({f.name: f for f in jobs["breakfast-end"].trigger.fields}["hour"]) == "10"
    assert service_settings["MEAL_SCHEDULE"]["lunch"]["end"] == "14:30"


def test_test_mode_ignores_meal_times_and_captures_every_15_seconds(tmp_path):
    service, grabber = service_for(tmp_path, STATIONS, CAPTURE_TEST_MODE=True)
    scheduler = build_scheduler(settings_for(tmp_path, STATIONS, CAPTURE_TEST_MODE=True), service)
    (job,) = scheduler.get_jobs()
    assert job.id == "test-mode" and job.trigger.interval.total_seconds() == 15
    job.func(); job.func()                                    # two ticks: a start capture, then an end capture
    kinds = sorted(path.parent.name for path in (tmp_path / "captures").rglob("*.jpg"))
    assert kinds == ["end", "end", "start", "start"]          # one photo per station each time


def test_meal_at_picks_the_meal_that_started_last(tmp_path):
    schedule = settings_for(tmp_path, STATIONS)["MEAL_SCHEDULE"]
    zone = ZoneInfo("Asia/Colombo")
    assert meal_at(schedule, datetime(2026, 10, 21, 7, 0, tzinfo=zone)) == "breakfast"
    assert meal_at(schedule, datetime(2026, 10, 21, 13, 0, tzinfo=zone)) == "lunch"
    assert meal_at(schedule, datetime(2026, 10, 21, 23, 0, tzinfo=zone)) == "dinner"
    assert meal_at(schedule, datetime(2026, 10, 21, 3, 0, tzinfo=zone)) == "dinner"   # before breakfast


def test_scheduler_does_not_start_in_tests_or_without_cameras(tmp_path):
    app = make_app(tmp_path, CAMERA_SOURCES=STATIONS)
    assert start_scheduler(app) is None                       # TESTING is on
    app.state.settings["TESTING"] = False
    app.state.capture_service.cameras = []
    assert start_scheduler(app) is None                       # no cameras set up


def test_only_one_process_can_hold_the_scheduler_lock(tmp_path):
    first, second = SingleInstanceLock(tmp_path / "a.lock"), SingleInstanceLock(tmp_path / "a.lock")
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_a_scheduled_capture_that_fails_never_raises(tmp_path):
    service, _ = service_for(tmp_path, STATIONS, grabber=FakeCamera(down=[s["url"] for s in STATIONS]))
    run_event(service, "breakfast", "start")                  # every camera is down: logged, not raised
    run_event(CaptureService(settings_for(tmp_path, [])), "breakfast", "start")   # no cameras: also fine


# ---- capture --------------------------------------------------------------------------------

def test_one_camera_takes_four_photos_and_saves_them_in_dated_folders(tmp_path):
    service, grabber = service_for(tmp_path, STATIONS[:1])
    event = service.capture_event("breakfast", "start")
    assert len(grabber.calls) == 4 and event.ok_count == 4 and event.failed_count == 0
    day = event.started_at.strftime("%Y-%m-%d")
    files = sorted((tmp_path / "captures" / day / "breakfast" / "start").glob("Station-1_*.jpg"))
    assert len(files) == 4                                    # same second or not, none overwrite another
    assert all(Image.open(path).size == (64, 48) for path in files)
    assert event.photos[0].relative.startswith(f"{day}/breakfast/start/Station-1_")
    assert not list((tmp_path / "captures").rglob("*.tmp"))


def test_several_cameras_take_one_photo_each(tmp_path):
    service, grabber = service_for(tmp_path, STATIONS)
    event = service.capture_event("lunch", "end")
    assert grabber.calls == [s["url"] for s in STATIONS]
    assert [photo.station for photo in event.photos] == ["Station 1", "Station 2"]
    assert all(photo.path.parent.parts[-2:] == ("lunch", "end") for photo in event.photos)


def test_a_camera_failure_is_retried_and_the_other_cameras_still_work(tmp_path):
    camera = FakeCamera(down=[STATIONS[0]["url"]])
    service, _ = service_for(tmp_path, STATIONS, grabber=camera)
    event = service.capture_event("dinner", "start")
    assert camera.calls.count(STATIONS[0]["url"]) == 3        # first try plus 2 retries
    assert [photo.ok for photo in event.photos] == [False, True]
    assert "could not be opened" in event.photos[0].error and "cam-one" not in event.photos[0].error


def test_an_unexpected_camera_error_is_contained(tmp_path):
    def broken(url):
        raise RuntimeError(f"boom at {url}")
    service, _ = service_for(tmp_path, STATIONS, grabber=broken)
    event = service.capture_event("breakfast", "end")
    assert event.ok_count == 0 and "RuntimeError" in event.photos[0].error and "cam-one" not in event.photos[0].error


def test_nothing_is_captured_without_cameras_or_while_busy(tmp_path):
    with pytest.raises(CameraUnavailable):
        CaptureService(settings_for(tmp_path, [])).capture_event("breakfast", "start")
    service, _ = service_for(tmp_path, STATIONS)
    assert service._busy.acquire(blocking=False)
    with pytest.raises(CaptureBusy):
        service.capture_event("breakfast", "start")
    service._busy.release()
    with pytest.raises(ValueError):
        service.capture_event("brunch", "start")


# ---- run-now endpoint -----------------------------------------------------------------------

def app_with(tmp_path, cameras=STATIONS, grabber=None):
    return make_app(tmp_path, CAMERA_SOURCES=cameras, CAPTURE_DIR=tmp_path / "captures",
                    FRAME_GRABBER=grabber or FakeCamera(), CAPTURE_RETRY_DELAY=0, PHOTO_GAP_SECONDS=0)


def test_run_now_takes_photos_and_lists_them(tmp_path):
    response = client(app_with(tmp_path)).post("/api/captures/run-now", json={"meal": "Breakfast", "kind": "start"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["meal"], body["kind"], body["ok_count"], body["failed_count"]) == ("breakfast", "start", 2, 0)
    assert [photo["station"] for photo in body["photos"]] == ["Station 1", "Station 2"]
    assert all(photo["file"].endswith(".jpg") and not photo["file"].startswith(("/", "C:")) for photo in body["photos"])
    assert len(list((tmp_path / "captures").rglob("*.jpg"))) == 2


def test_run_now_reports_partial_and_total_failure(tmp_path):
    partial = app_with(tmp_path, grabber=FakeCamera(down=[STATIONS[1]["url"]]))
    body = client(partial).post("/api/captures/run-now", json={"meal": "lunch", "kind": "end"}).json()
    assert (body["ok_count"], body["failed_count"]) == (1, 1) and body["photos"][1]["ok"] is False

    (tmp_path / "b").mkdir()
    down = app_with(tmp_path / "b", grabber=FakeCamera(down=[s["url"] for s in STATIONS]))
    response = client(down).post("/api/captures/run-now", json={"meal": "lunch", "kind": "end"})
    assert response.status_code == 502 and len(response.json()["photos"]) == 2


def test_run_now_rejects_bad_requests_and_missing_cameras(tmp_path):
    browser = client(app_with(tmp_path))
    assert browser.post("/api/captures/run-now", json={"meal": "brunch", "kind": "start"}).status_code == 400
    assert browser.post("/api/captures/run-now", json={"meal": "lunch", "kind": "middle"}).status_code == 400
    assert browser.post("/api/captures/run-now", json={"meal": "lunch"}).status_code == 400
    (tmp_path / "c").mkdir()
    nothing = client(app_with(tmp_path / "c", cameras=[])).post("/api/captures/run-now", json={"meal": "lunch", "kind": "start"})
    assert nothing.status_code == 503 and "CAMERA_SOURCES" in nothing.json()["error"]


def test_run_now_says_so_when_a_capture_is_already_running(tmp_path):
    app = app_with(tmp_path)
    app.state.capture_service._busy.acquire()
    response = client(app).post("/api/captures/run-now", json={"meal": "lunch", "kind": "start"})
    assert response.status_code == 409
