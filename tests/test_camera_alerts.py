"""Camera offline alerts: detection, the warning on screen, the emails, recovery, and the Camera status page."""

import smtplib

import pytest

from app.camera.capture import CameraError
from app.camera.schedule import add_health_checks, build_scheduler
from app.reports import store
from conftest import client, database, make_app, scalar
from test_camera import STATIONS, FakeCamera, jpeg
from test_weekly_report import FakeSMTP, MAIL


@pytest.fixture(autouse=True)
def fake_mail(monkeypatch):
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.started_tls, FakeSMTP.fail = [], [], [], None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)


def camera_app(tmp_path, grabber=None, recipients=("manager@hotel.com",), mail=True, **config):
    grabber = grabber or FakeCamera()
    app = make_app(tmp_path, CAMERA_SOURCES=STATIONS[:1], FRAME_GRABBER=grabber, CAPTURE_DIR=tmp_path / "captures",
                   CAPTURE_RETRY_DELAY=0, **(MAIL if mail else {}), **config)
    with database(app) as db:
        for address in recipients:
            store.add_recipient(db, address)
    return app, grabber


def test_a_camera_goes_offline_after_three_failed_checks_in_a_row(tmp_path):
    app, grabber = camera_app(tmp_path, FakeCamera(down=[STATIONS[0]["url"]]))
    monitor = app.state.camera_monitor
    assert monitor.snapshot()[0].status == "unknown" and monitor.offline() == []
    monitor.check_all()
    monitor.check_all()
    assert monitor.offline() == [] and monitor.snapshot()[0].failures == 2
    monitor.check_all()
    [camera] = monitor.offline()
    assert camera.name == "Station 1" and camera.offline_since and "could not be opened" in camera.last_error


def test_one_good_check_resets_the_count(tmp_path):
    camera = FakeCamera(down=[STATIONS[0]["url"]])
    app, _ = camera_app(tmp_path, camera)
    monitor = app.state.camera_monitor
    monitor.check_all()
    monitor.check_all()
    camera.down.clear()
    monitor.check_all()
    camera.down.add(STATIONS[0]["url"])
    monitor.check_all()
    monitor.check_all()
    assert monitor.offline() == [] and monitor.snapshot()[0].failures == 2


def test_the_offline_email_goes_out_once_and_a_second_one_says_it_is_back(tmp_path):
    camera = FakeCamera(down=[STATIONS[0]["url"]])
    app, _ = camera_app(tmp_path, camera)
    store_two = "owner@hotel.com"
    with database(app) as db:
        store.add_recipient(db, store_two)
    monitor = app.state.camera_monitor
    for _ in range(5):
        monitor.check_all()
    assert [message["To"] for message in FakeSMTP.sent] == ["manager@hotel.com", "owner@hotel.com"]     # once, not five times
    message = FakeSMTP.sent[0]
    assert message["Subject"] == "Wastewise alert: Station 1 camera is offline"
    body = message.get_body(("plain",)).get_content()
    assert "offline (since" in body and "could not be opened" in body and "/cameras" in body and "cam-one.test" not in body
    assert "Alert email sent to 2 addresses." in monitor.snapshot()[0].note

    camera.down.clear()
    monitor.check_all()
    assert monitor.offline() == [] and monitor.snapshot()[0].status == "online"
    assert FakeSMTP.sent[-1]["Subject"] == "Wastewise: Station 1 camera is back online" and len(FakeSMTP.sent) == 4
    monitor.check_all()
    assert len(FakeSMTP.sent) == 4                                                                      # nothing more while it stays up


def test_a_failed_capture_counts_as_offline_at_once(tmp_path):
    camera = FakeCamera(down=[STATIONS[0]["url"]])
    app, _ = camera_app(tmp_path, camera, PHOTOS_PER_CAPTURE=2)
    event = app.state.capture_service.capture_event("lunch", "start")
    assert event.ok_count == 0
    assert [state.name for state in app.state.camera_monitor.offline()] == ["Station 1"]
    assert len(FakeSMTP.sent) == 1
    camera.down.clear()
    app.state.capture_service.capture_event("lunch", "end")                                             # a good capture brings it back
    assert app.state.camera_monitor.offline() == [] and len(FakeSMTP.sent) == 2


def test_a_capture_with_some_good_photos_keeps_the_camera_online(tmp_path):
    results = iter([None, CameraError("blip"), None, CameraError("blip"), CameraError("blip"), CameraError("blip")])

    def sometimes(url):
        problem = next(results, None)
        if problem:
            raise problem
        return jpeg()

    app, _ = camera_app(tmp_path, sometimes, PHOTOS_PER_CAPTURE=2)
    app.state.capture_service.capture_event("lunch", "start")
    assert app.state.camera_monitor.offline() == [] and app.state.camera_monitor.snapshot()[0].status == "online"


def test_without_email_set_up_the_warning_still_shows_and_the_page_says_why(tmp_path):
    app, _ = camera_app(tmp_path, FakeCamera(down=[STATIONS[0]["url"]]), mail=False)
    for _ in range(3):
        app.state.camera_monitor.check_all()
    assert FakeSMTP.sent == []
    page = client(app).get("/cameras").text
    assert "email is not set up" in page and "Offline" in page


def test_nobody_on_the_list_or_alerts_turned_off(tmp_path):
    app, _ = camera_app(tmp_path, FakeCamera(down=[STATIONS[0]["url"]]), recipients=())
    for _ in range(3):
        app.state.camera_monitor.check_all()
    assert FakeSMTP.sent == [] and "nobody is on the Weekly report list" in app.state.camera_monitor.snapshot()[0].note
    with database(app) as db:
        store.add_recipient(db, "manager@hotel.com")
    app.state.camera_monitor.check_all()                                                                # an unsent alert is retried
    assert len(FakeSMTP.sent) == 1

    quiet, _ = camera_app(tmp_path / "q", FakeCamera(down=[STATIONS[0]["url"]]), CAMERA_ALERTS=False)
    for _ in range(3):
        quiet.state.camera_monitor.check_all()
    assert len(FakeSMTP.sent) == 1 and len(quiet.state.camera_monitor.offline()) == 1


def test_an_email_that_fails_is_retried_and_does_not_break_the_check(tmp_path):
    app, _ = camera_app(tmp_path, FakeCamera(down=[STATIONS[0]["url"]]))
    FakeSMTP.fail = ConnectionRefusedError("down")
    for _ in range(3):
        app.state.camera_monitor.check_all()
    assert FakeSMTP.sent == [] and "could not be sent" in app.state.camera_monitor.snapshot()[0].note
    FakeSMTP.fail = None
    app.state.camera_monitor.check_all()
    assert len(FakeSMTP.sent) == 1


def test_a_warning_shows_on_every_page_until_the_camera_is_back(tmp_path):
    camera = FakeCamera(down=[STATIONS[0]["url"]])
    app, _ = camera_app(tmp_path, camera)
    browser = client(app)
    assert "camera-banner" not in browser.get("/forecast").text
    for _ in range(3):
        app.state.camera_monitor.check_all()
    for path in ("/", "/forecast", "/food-prices"):
        page = browser.get(path).text
        assert "Station 1 camera is offline." in page and "See camera status" in page and "nav-alert" in page
    status = browser.get("/cameras").text
    assert "Offline since" in status and "could not be opened" in status and "camera-banner" not in status
    camera.down.clear()
    assert browser.post("/cameras/check").headers["location"] == "/cameras?checked=1"
    assert "camera-banner" not in browser.get("/").text and "Cameras checked." in browser.get("/cameras?checked=1").text


def test_an_outage_is_remembered_after_a_restart(tmp_path):
    app, _ = camera_app(tmp_path, FakeCamera(down=[STATIONS[0]["url"]]))
    for _ in range(3):
        app.state.camera_monitor.check_all()
    with database(app) as db:
        assert scalar(db, "SELECT status FROM camera_status") == "offline" and scalar(db, "SELECT alerted_at FROM camera_status")
    again = make_app(tmp_path, CAMERA_SOURCES=STATIONS[:1], FRAME_GRABBER=FakeCamera(), **MAIL)
    assert [state.name for state in again.state.camera_monitor.offline()] == ["Station 1"]
    again.state.camera_monitor.check_all()
    assert again.state.camera_monitor.offline() == [] and len(FakeSMTP.sent) == 2                       # the "back online" email


def test_checks_wait_while_a_capture_is_running(tmp_path):
    app, grabber = camera_app(tmp_path)
    app.state.capture_service._busy.acquire()
    app.state.camera_monitor.check_all()
    assert grabber.calls == []
    app.state.camera_monitor.check_all(force=True)
    assert len(grabber.calls) == 1


def test_the_page_without_cameras_explains_how_to_set_them_up(tmp_path):
    page = client(make_app(tmp_path)).get("/cameras").text
    assert "No cameras are set up" in page and "CAMERA_SOURCES" in page and "Camera status</a>" in page


def test_the_camera_check_is_scheduled(tmp_path):
    app, _ = camera_app(tmp_path, CAMERA_CHECK_MINUTES=2)
    scheduler = build_scheduler(app.state.settings, app.state.capture_service)
    add_health_checks(scheduler, app)
    job = scheduler.get_job("camera-health")
    assert job.trigger.interval.total_seconds() == 120


def test_camera_alert_settings_are_checked(tmp_path):
    for bad in ({"CAMERA_CHECK_MINUTES": "0"}, {"CAMERA_OFFLINE_AFTER": "x"}, {"CAMERA_OFFLINE_AFTER": "11"}):
        with pytest.raises(ValueError):
            make_app(tmp_path, **bad)


def test_the_camera_page_needs_a_sign_in_when_sign_in_is_required(tmp_path):
    browser = client(make_app(tmp_path, REQUIRE_LOGIN=True))
    assert browser.get("/cameras").status_code == 303 and browser.post("/cameras/check").status_code == 303
