"""Manager sign-in: the page, the access rules, sessions, and protection against guessing passwords."""

import base64
import json
import time

import pytest
from itsdangerous import TimestampSigner
from sqlalchemy import text

from app import auth
from app.auth import AttemptLimiter, safe_next
from app.database.queries import create_user, set_user_password
from app.database.seed import seed_demo_data
from conftest import client, database, make_app, scalar, sql

PASSWORD = "correct horse battery"


def app_with_users(tmp_path, **config):
    app = make_app(tmp_path, REQUIRE_LOGIN=True, **config)
    with database(app) as db:
        seed_demo_data(db)
        create_user(db, name="Mira Fernando", username="mira", password=PASSWORD, role="manager")
        create_user(db, name="Anil Perera", username="anil", password=PASSWORD, role="admin")
        create_user(db, name="Kitchen Kamal", username="kamal", password=PASSWORD, role="entry")
        create_user(db, name="Former Manager", username="gone", password=PASSWORD, role="manager")
        sql(db, "UPDATE users SET active = 0 WHERE username = 'gone'")
        db.commit()
    return app


def sign_in(browser, username="mira", password=PASSWORD, **extra):
    return browser.post("/login", data={"username": username, "password": password, **extra})


def cookie_data(browser) -> dict:
    """What the sign-in cookie holds (it is signed, not secret)."""
    raw = browser.cookies.get("wastewise_session")
    signer = TimestampSigner(browser.app.state.settings["SECRET_KEY"])
    return json.loads(base64.b64decode(signer.unsign(raw)))


# ---- the page -------------------------------------------------------------------------------

def test_the_login_page_is_public_and_has_everything_it_needs(tmp_path):
    browser = client(app_with_users(tmp_path))
    page = browser.get("/login")
    assert page.status_code == 200
    html = page.text
    assert "<title>Sign in · Wastewise</title>" in html and "<h1" in html and "Manager sign in" in html
    assert 'autocomplete="username"' in html and 'autocomplete="current-password"' in html and 'type="password"' in html
    assert 'name="remember"' in html and "Keep me signed in for 30 days" in html
    assert 'href="/static/login.css?v=' in html and 'src="/static/login.js?v=' in html
    assert 'aria-hidden="true"' in html and "Sample data" in html     # the moving picture is decoration, labelled as a sample
    assert page.headers["cache-control"] == "no-store"
    assert browser.get("/static/login.css").status_code == 200 and browser.get("/static/login.js").status_code == 200
    assert "prefers-reduced-motion" in browser.get("/static/login.css").text


# ---- keeping people out ---------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/forecast", "/food-counting", "/records/new", "/days/2026-10-01", "/docs"])
def test_pages_send_visitors_to_the_login_and_back_afterwards(tmp_path, path):
    response = client(app_with_users(tmp_path)).get(path)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=%2F")


def test_the_original_address_is_kept_through_the_login(tmp_path):
    browser = client(app_with_users(tmp_path))
    location = browser.get("/?area_id=1&show=25").headers["location"]
    assert location == "/login?next=%2F%3Farea_id%3D1%26show%3D25"
    page = browser.get(location).text
    assert 'name="next" value="/?area_id=1&amp;show=25"' in page
    done = sign_in(browser, next="/?area_id=1&show=25")
    assert done.status_code == 303 and done.headers["location"] == "/?area_id=1&show=25"


def test_apis_and_photos_answer_401_instead_of_redirecting(tmp_path):
    browser = client(app_with_users(tmp_path))
    for method, path in (("get", "/api/captures"), ("get", "/api/forecast-history"), ("get", "/api/camera-foods"),
                         ("post", "/api/predict-meal"), ("post", "/api/captures/run-now"), ("get", "/captures/1/photo")):
        response = getattr(browser, method)(path)
        assert response.status_code == 401 and response.json() == {"error": "Sign in to continue."}, path


# ---- signing in -----------------------------------------------------------------------------

def test_a_manager_signs_in_sees_the_app_and_signs_out(tmp_path):
    browser = client(app_with_users(tmp_path))
    done = sign_in(browser)
    assert done.status_code == 303 and done.headers["location"] == "/"
    cookie = done.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie        # scripts cannot read it; other sites cannot send it

    home = browser.get("/")
    assert home.status_code == 200 and home.headers["cache-control"] == "no-store"
    assert "Mira Fernando" in home.text and "Manager" in home.text and "Sign out" in home.text
    assert "Local demo" not in home.text
    assert browser.get("/api/forecast-history").status_code in (200, 500, 503)    # allowed through (model may be absent)

    out = browser.post("/logout")
    assert out.status_code == 303 and out.headers["location"] == "/login?signed_out=1"
    assert "You&#39;ve been signed out." in browser.get("/login?signed_out=1").text
    assert browser.get("/").status_code == 303                  # signed out for real

    sign_in(browser)
    assert browser.get("/logout").status_code == 405           # a link or an image cannot sign anyone out
    assert browser.get("/").status_code == 200


def test_an_administrator_can_sign_in_too(tmp_path):
    browser = client(app_with_users(tmp_path))
    assert sign_in(browser, "anil").status_code == 303
    assert "Administrator" in browser.get("/").text


def test_wrong_credentials_get_the_same_vague_answer(tmp_path):
    browser = client(app_with_users(tmp_path))
    wrong_password = sign_in(browser, "mira", "not the password")
    wrong_user = sign_in(browser, "nobody", "not the password")
    assert wrong_password.status_code == wrong_user.status_code == 401
    message = "That username and password don&#39;t match."
    assert message in wrong_password.text and message in wrong_user.text      # nothing says which part was wrong
    assert 'value="mira"' in wrong_password.text                            # the username is kept
    assert "not the password" not in wrong_password.text                    # the password never comes back
    assert 'aria-invalid="true"' in wrong_password.text and 'role="alert"' in wrong_password.text
    assert "wastewise_session" not in wrong_password.headers.get("set-cookie", "")


def test_empty_fields_are_explained(tmp_path):
    response = sign_in(client(app_with_users(tmp_path)), "", "")
    assert response.status_code == 400 and "Enter your username and your password." in response.text


def test_kitchen_staff_and_switched_off_accounts_cannot_sign_in(tmp_path):
    browser = client(app_with_users(tmp_path))
    staff = sign_in(browser, "kamal")
    assert staff.status_code == 403 and "can&#39;t sign in here" in staff.text
    assert browser.get("/").status_code == 303
    gone = sign_in(browser, "gone")
    assert gone.status_code == 401 and "don&#39;t match" in gone.text           # no hint that the account exists


def test_an_unknown_username_still_costs_a_password_check(tmp_path, monkeypatch):
    checked = []
    real = auth.check_password_hash
    monkeypatch.setattr(auth, "check_password_hash", lambda hashed, password: checked.append(hashed) or real(hashed, password))
    browser = client(app_with_users(tmp_path))
    sign_in(browser, "nobody", "whatever")
    assert checked == [auth._DUMMY_HASH]        # so a wrong username is not quicker than a wrong password


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/", "/\\evil.example", "javascript:alert(1)",
                                    "/login", "/login?next=/", "", "relative/path"])
def test_only_pages_of_this_app_can_follow_a_sign_in(target):
    assert safe_next(target) == "/"


def test_next_cannot_send_a_manager_to_another_site(tmp_path):
    browser = client(app_with_users(tmp_path))
    assert sign_in(browser, next="https://evil.example/steal").headers["location"] == "/"
    assert safe_next("/forecast?x=1") == "/forecast?x=1"


def test_visiting_the_login_page_while_signed_in_goes_to_the_app(tmp_path):
    browser = client(app_with_users(tmp_path))
    sign_in(browser)
    response = browser.get("/login?next=%2Fforecast")
    assert response.status_code == 303 and response.headers["location"] == "/forecast"


# ---- sessions -------------------------------------------------------------------------------

def test_keep_me_signed_in_lasts_30_days_otherwise_8_hours(tmp_path):
    short, long = client(app_with_users(tmp_path)), client(app_with_users(tmp_path / "b"))
    sign_in(short)
    sign_in(long, remember="1")
    now = time.time()
    assert 8 * 3600 - 30 < cookie_data(short)["exp"] - now <= 8 * 3600
    assert 30 * 86400 - 30 < cookie_data(long)["exp"] - now <= 30 * 86400
    assert set(cookie_data(short)) == {"uid", "pv", "exp"}       # no name, role or password in the cookie


def test_a_sign_in_ends_when_its_time_is_up(tmp_path, monkeypatch):
    browser = client(app_with_users(tmp_path))
    sign_in(browser)
    assert browser.get("/").status_code == 200
    later = time.time() + 9 * 3600
    monkeypatch.setattr(auth.time, "time", lambda: later)
    response = browser.get("/forecast")
    assert response.status_code == 303 and response.headers["location"].endswith("&expired=1")
    assert "Your sign-in ended. Please sign in again." in browser.get(response.headers["location"]).text


def test_a_new_password_or_a_switched_off_account_signs_the_user_out(tmp_path):
    app = app_with_users(tmp_path)
    browser = client(app)
    sign_in(browser)
    assert browser.get("/").status_code == 200
    with database(app) as db:
        set_user_password(db, scalar(db, "SELECT id FROM users WHERE username = 'mira'"), "a brand new password")
    assert browser.get("/").status_code == 303                   # the old sign-in is no good any more

    sign_in(browser, password="a brand new password")
    assert browser.get("/").status_code == 200
    with database(app) as db:
        sql(db, "UPDATE users SET active = 0 WHERE username = 'mira'")
        db.commit()
    assert browser.get("/").status_code == 303


def test_a_forged_or_damaged_cookie_means_signed_out(tmp_path):
    browser = client(app_with_users(tmp_path))
    sign_in(browser)
    good = browser.cookies.get("wastewise_session")
    for bad in (good[:-3] + "xyz", "garbage", good.split(".")[0]):
        browser.cookies.clear()
        browser.cookies.set("wastewise_session", bad)
        assert browser.get("/").status_code == 303
    # signed with another key
    forged = TimestampSigner("some other key").sign(base64.b64encode(json.dumps({"uid": 2, "exp": time.time() + 99999, "pv": "x"}).encode()))
    browser.cookies.clear()
    browser.cookies.set("wastewise_session", forged.decode())
    assert browser.get("/").status_code == 303


def test_signing_in_replaces_whatever_the_session_held_before(tmp_path):
    browser = client(app_with_users(tmp_path))
    sign_in(browser)
    assert set(cookie_data(browser)) == {"uid", "pv", "exp"}


# ---- too many wrong passwords ---------------------------------------------------------------

def test_five_wrong_passwords_lock_that_account_for_a_while(tmp_path):
    browser = client(app_with_users(tmp_path))
    for _ in range(5):
        assert sign_in(browser, "mira", "wrong").status_code == 401
    locked = sign_in(browser, "mira", PASSWORD)                    # even the right password has to wait
    assert locked.status_code == 429 and "Too many wrong attempts. Try again in 15 minutes." in locked.text
    assert 'data-wait="' in locked.text
    assert browser.get("/").status_code == 303
    assert sign_in(browser, "anil", PASSWORD).status_code == 303   # another account is not affected


def test_a_good_sign_in_clears_the_count(tmp_path):
    browser = client(app_with_users(tmp_path))
    for _ in range(4):
        sign_in(browser, "mira", "wrong")
    assert sign_in(browser, "mira", PASSWORD).status_code == 303
    browser.post("/logout")
    for _ in range(4):
        assert sign_in(browser, "mira", "wrong").status_code == 401   # a fresh set of attempts


def test_one_address_cannot_try_account_after_account(tmp_path):
    app = app_with_users(tmp_path, LOGIN_MAX_ATTEMPTS=2)
    browser = client(app)
    for number in range(8):                                        # 2 attempts x 4 accounts is the limit
        assert sign_in(browser, f"user{number}", "wrong").status_code == 401
    assert sign_in(browser, "mira", PASSWORD).status_code == 429


def test_the_lock_runs_out(tmp_path):
    limiter = AttemptLimiter(max_attempts=3, lock_minutes=10)
    for second in (0, 1, 2):
        limiter.failed("1.2.3.4", "Mira", now=second)
    assert limiter.seconds_left("1.2.3.4", "mira", now=3) == 597                  # the name's case does not matter
    assert limiter.seconds_left("1.2.3.4", "someone else", now=3) == 0
    assert limiter.seconds_left("9.9.9.9", "mira", now=3) == 0
    assert limiter.seconds_left("1.2.3.4", "mira", now=599) == 1                  # one second to go
    assert limiter.seconds_left("1.2.3.4", "mira", now=601) == 0                  # the oldest failure has aged out


# ---- the rest of the app, signed in ---------------------------------------------------------

def test_records_are_saved_in_the_signed_in_managers_name(tmp_path):
    app = app_with_users(tmp_path)
    browser = client(app)
    sign_in(browser)
    with database(app) as db:
        body = {"event_at": "2026-10-01T12:30",
                "area_id": scalar(db, "SELECT id FROM areas WHERE name = 'Buffet'"),
                "reason_id": scalar(db, "SELECT id FROM reasons WHERE name = 'Spoilage'"), "quantity_kg": "2.5"}
    saved = browser.post("/records/new", data=body)
    assert saved.status_code == 303
    day = browser.get(saved.headers["location"]).text
    assert "Mira Fernando" in day and "Demo Kitchen Staff" not in day.split("Recorded by")[1].split("Record<")[0]
    with database(app) as db:
        assert scalar(db, "SELECT u.username FROM waste_records w JOIN users u ON u.id = w.user_id ORDER BY w.id DESC LIMIT 1") == "mira"
    seeded = scalar(db := app.state.session_factory(), "SELECT MIN(id) FROM waste_records")
    assert browser.get(f"/records/{seeded}/edit").status_code == 200     # a manager may edit anyone's record
    db.close()


def test_without_the_sign_in_requirement_nothing_changes(tmp_path):
    app = make_app(tmp_path, REQUIRE_LOGIN=False)
    with database(app) as db:
        seed_demo_data(db)
    browser = client(app)
    home = browser.get("/")
    assert home.status_code == 200 and "Local demo" in home.text and "Sign out" not in home.text
    assert browser.get("/api/captures").status_code == 200
