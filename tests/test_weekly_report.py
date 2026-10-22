"""The weekly email report: recipients, the report's content, sending (with a fake mail server) and the schedule."""

from datetime import datetime, timedelta, timezone
import smtplib

import pytest

from app.database.seed import seed_demo_data
from app.reports import schedule as report_schedule
from app.reports import service, store
from app.waste_records.common import DEMO_TIMEZONE
from conftest import client, database, make_app, scalar, sql
from test_waste_value import add, food_id

MAIL = {"ADMIN_EMAIL": "admin@hotel.com", "SMTP_HOST": "smtp.test", "SMTP_USER": "admin@hotel.com", "SMTP_PASSWORD": "secret-pass"}
SUNDAY = datetime(2026, 10, 18, 18, 0, tzinfo=DEMO_TIMEZONE)          # 18 Oct 2026 is a Sunday


class FakeSMTP:
    """Stands in for the mail server: remembers what would have been sent."""
    sent, logins, started_tls, fail = [], [], [], None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def __enter__(self):
        if FakeSMTP.fail:
            raise FakeSMTP.fail
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        FakeSMTP.started_tls.append(self.host)

    def login(self, user, password):
        FakeSMTP.logins.append((user, password))

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def fake_mail(monkeypatch):
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.started_tls, FakeSMTP.fail = [], [], [], None
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)


def report_app(tmp_path, name="test.sqlite3", **config):
    app = make_app(tmp_path, name, **{**MAIL, **config})
    with database(app) as db:
        seed_demo_data(db)
        user = scalar(db, "SELECT id FROM users WHERE username = 'demo_entry'")
        sql(db, "DELETE FROM waste_records")
        db.commit()
        add(db, "Fried rice", 4.0, when=SUNDAY - timedelta(days=2))
        add(db, "Fried rice", 2.0, when=SUNDAY - timedelta(days=9))                   # last week
        add(db, "Fish curry", 1.0, reason="Ran out (shortage)", when=SUNDAY - timedelta(days=1))
        store.add_recipient(db, "Manager@Hotel.com")
    return app


# ---- recipients -----------------------------------------------------------------------------------

def test_recipients_are_added_checked_and_removed(tmp_path):
    app = make_app(tmp_path, **MAIL)
    browser = client(app)
    assert "Nobody yet" in browser.get("/reports").text
    assert browser.post("/reports/recipients", data={"email": " Chef@Hotel.com "}).status_code == 303
    page = browser.get("/reports").text
    assert "chef@hotel.com" in page and "Sent from admin@hotel.com" in page
    bad = browser.post("/reports/recipients", data={"email": "not an email"})
    assert bad.status_code == 400 and "Enter a full email address" in bad.text and 'value="not an email"' in bad.text
    assert "already gets the report" in browser.post("/reports/recipients", data={"email": "CHEF@hotel.com"}).text
    with database(app) as db:
        recipient = scalar(db, "SELECT id FROM report_recipients")
    assert browser.post(f"/reports/recipients/{recipient}/remove").status_code == 303
    assert "Nobody yet" in browser.get("/reports").text


def test_the_page_says_when_email_is_not_set_up(tmp_path):
    app = make_app(tmp_path)
    page = client(app).get("/reports").text
    assert "Email is not set up yet" in page and "ADMIN_EMAIL and SMTP_HOST" in page
    assert "Weekly report</a>" in page and 'aria-current="page"' in page


# ---- the report -----------------------------------------------------------------------------------

def test_the_report_compares_with_last_week_and_shows_each_day(tmp_path):
    app = report_app(tmp_path)
    with database(app) as db:
        title, text, html = service.render_report(db, app, SUNDAY)
    assert title == "Wastewise weekly report: Rs 2,400 of food waste, 12 Oct to 18 Oct"
    assert "≈ Rs 2,400" in html and "4.0 kg thrown away" in html
    assert "▲ 100%" in html and "Last week ≈ Rs 1,200" in html                  # 4 kg against 2 kg of Fried rice
    assert "Day by day" in html and "Fri 16 Oct" in html and "Rs 2,400" in html
    assert "Food ran out on <strong>1 day</strong>" in html and "Saturday 17 Oct" in html   # a shortage is not waste
    assert "Prepare about 0.6 kg less of fried rice each day." in html
    assert "no forecast" in html.lower()                                                   # no model, no meal checks
    assert "Compared with last week" in text and "up 100%" in text and "Fri 16 Oct: Rs 2,400" in text
    assert "Where to cut" in text and "Open Wastewise: http://localhost:5000" in text


def test_the_forecast_uses_last_weeks_guest_numbers(tmp_path):
    class Model:
        def predict(self, frame):
            assert list(frame.columns) == ["Meal type", "Food item", "Guest count"]
            return [guests * 0.2 for guests in frame["Guest count"]]

    app = report_app(tmp_path, ML_MODEL=Model())
    with database(app) as db:
        from app.database.queries import create_meal_check
        create_meal_check(db, event_at=SUNDAY - timedelta(days=2), meal_type="Lunch", food_item="Fried rice", count_label="plate",
                          start_count=10, end_count=2, short_count=0, kg_per_piece=0.5, guest_count=100,
                          area_id=scalar(db, "SELECT id FROM areas WHERE name = 'Buffet'"),
                          reason_id=scalar(db, "SELECT id FROM reasons WHERE name = 'Spoilage'"),
                          user_id=scalar(db, "SELECT id FROM users WHERE username = 'demo_entry'"))
        _, text, html = service.render_report(db, app, SUNDAY)
    assert "Lunch · Fried rice" in html and "for 100 guests" in html and "22.0 kg" in html      # 100 x 0.2 x 1.1
    assert "Lunch Fried rice: prepare 22.0 kg for 100 guests" in text


def test_the_preview_shows_the_report(tmp_path):
    app = report_app(tmp_path)
    page = client(app).get("/reports/preview")
    assert page.status_code == 200 and "Wastewise weekly report" in page.text and "Open Wastewise" in page.text


# ---- sending ----------------------------------------------------------------------------------------

def test_sending_the_report_emails_each_recipient_separately(tmp_path):
    app = report_app(tmp_path)
    with database(app) as db:
        store.add_recipient(db, "owner@hotel.com")
    outcome = service.send_report(app, kind="manual", end=SUNDAY)
    assert outcome.ok and outcome.message == "The report was sent to 2 addresses."
    assert [message["To"] for message in FakeSMTP.sent] == ["manager@hotel.com", "owner@hotel.com"]
    message = FakeSMTP.sent[0]
    assert message["From"] == "Wastewise <admin@hotel.com>" and message["Subject"].startswith("Wastewise weekly report")
    assert "Day by day" in message.get_body(("html",)).get_content() and "WASTEWISE WEEKLY REPORT" in message.get_body(("plain",)).get_content()
    assert FakeSMTP.started_tls == ["smtp.test"] and FakeSMTP.logins == [("admin@hotel.com", "secret-pass")]
    with database(app) as db:
        assert scalar(db, "SELECT status FROM report_log") == "sent"


def test_a_failure_is_explained_and_logged_without_the_password(tmp_path):
    app = report_app(tmp_path)
    FakeSMTP.fail = smtplib.SMTPAuthenticationError(535, b"bad credentials secret-pass")
    outcome = service.send_report(app, kind="manual")
    assert not outcome.ok and "app password" in outcome.message and "secret-pass" not in outcome.message
    FakeSMTP.fail = ConnectionRefusedError("nope")
    assert "Could not reach the mail server" in service.send_report(app, kind="manual").message
    with database(app) as db:
        assert scalar(db, "SELECT COUNT(*) FROM report_log WHERE status = 'failed'") == 2
        assert "secret-pass" not in scalar(db, "SELECT group_concat(error) FROM report_log")
    page = client(app).get("/reports").text
    assert "failed" in page and "Could not reach the mail server" in page


def test_the_buttons_need_email_set_up_and_someone_to_send_to(tmp_path):
    assert "Email is not set up" in service.send_report(make_app(tmp_path, "a.sqlite3"), kind="manual").message
    assert service.send_test(make_app(tmp_path, "b.sqlite3", **MAIL)).message == "Add at least one email address first."
    app = report_app(tmp_path, "c.sqlite3")
    browser = client(app)
    response = browser.post("/reports/test")
    assert response.status_code == 200 and "A test email was sent to 1 address." in response.text
    assert FakeSMTP.sent[-1]["Subject"] == "Wastewise test email"
    response = browser.post("/reports/send-now")
    assert response.status_code == 200 and "The report was sent to 1 address." in response.text
    FakeSMTP.fail = OSError("down")
    assert browser.post("/reports/send-now").status_code == 502


# ---- the schedule ---------------------------------------------------------------------------------

def test_the_latest_due_time_is_the_last_sunday_evening(tmp_path):
    settings = make_app(tmp_path, **MAIL).state.settings
    assert service.latest_slot(settings, datetime(2026, 10, 18, 19, 0, tzinfo=DEMO_TIMEZONE)) == SUNDAY
    assert service.latest_slot(settings, datetime(2026, 10, 18, 17, 59, tzinfo=DEMO_TIMEZONE)) == SUNDAY - timedelta(days=7)
    assert service.latest_slot(settings, datetime(2026, 10, 21, 9, 0, tzinfo=DEMO_TIMEZONE)) == SUNDAY
    monday = make_app(tmp_path, "m.sqlite3", REPORT_DAY="monday", REPORT_TIME="08:30").state.settings
    assert service.latest_slot(monday, datetime(2026, 10, 21, 9, 0, tzinfo=DEMO_TIMEZONE)) == datetime(2026, 10, 19, 8, 30, tzinfo=DEMO_TIMEZONE)


def test_a_report_missed_while_the_app_was_off_is_sent_once(tmp_path):
    app = report_app(tmp_path)
    with database(app) as db:
        sql(db, "INSERT INTO report_settings (key, value) VALUES ('enabled_at', '2026-10-01T00:00:00.000Z')")
        db.commit()
    after = datetime(2026, 10, 20, 9, 0, tzinfo=DEMO_TIMEZONE)
    outcome = service.send_if_due(app, after)
    assert outcome.ok and len(FakeSMTP.sent) == 1
    assert service.send_if_due(app, after + timedelta(hours=1)) is None             # already sent for that Sunday
    assert len(FakeSMTP.sent) == 1
    with database(app) as db:
        assert scalar(db, "SELECT kind FROM report_log") == "weekly"


def test_nothing_is_sent_when_it_is_off_new_or_unaddressed(tmp_path):
    after = datetime(2026, 10, 20, 9, 0, tzinfo=DEMO_TIMEZONE)
    app = report_app(tmp_path)                                                       # just set up: a Sunday before this does not count
    assert service.send_if_due(app, after) is None
    with database(app) as db:
        sql(db, "UPDATE report_settings SET value = '2026-10-01T00:00:00.000Z' WHERE key = 'enabled_at'")
        db.commit()
    assert client(app).post("/reports/switch", data={"on": "0"}).status_code == 303
    assert service.send_if_due(app, after) is None
    assert service.send_if_due(make_app(tmp_path, "n.sqlite3", **MAIL), after) is None     # nobody to send to
    assert service.send_if_due(make_app(tmp_path, "o.sqlite3"), after) is None             # email not set up
    assert FakeSMTP.sent == []
    client(app).post("/reports/switch", data={"on": "1"})                            # turning it on again starts from now
    assert service.send_if_due(app, after) is None


def test_the_weekly_job_runs_on_the_chosen_day_and_time(tmp_path):
    app = make_app(tmp_path, **MAIL, REPORT_DAY="sun", REPORT_TIME="18:00")
    scheduler = report_schedule.build_scheduler(app)
    job = scheduler.get_job("weekly-report")
    assert str(job.trigger.fields[4]) == "sun" and str(job.trigger.fields[5]) == "18" and str(job.trigger.fields[6]) == "0"
    assert scheduler.get_job("weekly-report-catch-up") is not None
    assert report_schedule.start_report_scheduler(app) is None                       # never starts in tests


def test_report_settings_are_checked(tmp_path):
    for bad in ({"REPORT_DAY": "someday"}, {"REPORT_TIME": "6pm"}, {"SMTP_PORT": "x"}, {"SMTP_SECURITY": "maybe"}):
        with pytest.raises(ValueError):
            make_app(tmp_path, **bad)


def test_the_report_page_needs_a_sign_in_when_sign_in_is_required(tmp_path):
    app = make_app(tmp_path, REQUIRE_LOGIN=True, **MAIL)
    browser = client(app)
    for method, path in (("get", "/reports"), ("post", "/reports/send-now"), ("get", "/reports/preview")):
        assert getattr(browser, method)(path).status_code == 303
