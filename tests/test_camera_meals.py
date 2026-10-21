"""Camera capture milestone 4: start and end photos paired into drafts that staff confirm as meal checks."""

from app.database.seed import seed_demo_data
from conftest import client, database, make_app, scalar, sql
from test_camera import STATIONS
from test_camera_counting import jpeg


class CountingOwl:
    """Finds ``counts[label]`` items of each food, each in its own spot; change counts between captures."""

    def __init__(self, **counts):
        self.counts = counts

    ROWS = {"bread roll": 0, "egg": 1, "donut": 2, "cupcake": 3, "apple": 4}   # each food on its own row

    def __call__(self, image, label, threshold):
        top = 3 + 15 * self.ROWS.get(label, 0)
        return [{"score": 0.9, "box": [3 + 11 * n, top, 12 + 11 * n, top + 9]} for n in range(self.counts.get(label, 0))]


def meal_app(tmp_path, owl, cameras=STATIONS[:1], camera=None):
    app = make_app(tmp_path, CAMERA_SOURCES=cameras, CAPTURE_DIR=tmp_path / "captures", FRAME_GRABBER=camera or (lambda url: jpeg()),
                   CAPTURE_RETRY_DELAY=0, PHOTO_GAP_SECONDS=0, FOOD_COUNTER=owl, ML_MODEL=_Forecast())
    with database(app) as db:
        seed_demo_data(db)
    return app


class _Forecast:
    def predict(self, frame):
        return [row["Guest count"] * 0.01 for row in frame.to_dict("records")]


def capture(app, meal, kind):
    client(app).post("/api/captures/run-now", json={"meal": meal, "kind": kind})
    app.state.counting_worker.process_pending()


def day(app, date=""):
    return client(app).get("/api/captures", params={"date": date} if date else None).json()


def confirm_body(app, draft, guests=40, **changes):
    with database(app) as db:
        body = {"guest_count": guests,
                "area_id": scalar(db, "SELECT id FROM areas WHERE name = 'Buffet'"),
                "reason_id": scalar(db, "SELECT id FROM reasons WHERE name = 'Overproduction'"),
                "foods": [{"label": line["label"], "start_count": line["start"], "end_count": line["end"]}
                          for line in draft["foods"]]}
    return {**body, **changes}


def test_a_draft_appears_only_when_start_and_end_are_both_counted(tmp_path):
    owl = CountingOwl(egg=8, donut=3)
    app = meal_app(tmp_path, owl)
    capture(app, "breakfast", "start")
    view = day(app)
    breakfast = view["meals"][0]
    assert breakfast["meal"] == "breakfast" and breakfast["times"] == {"start": "06:00", "end": "10:00"}
    station = breakfast["stations"][0]
    assert len(station["start"]["photos"]) == 4 and station["end"]["photos"] == []
    assert station["start"]["combined"] == {"apple": 0, "bread roll": 0, "cupcake": 0, "donut": 3, "egg": 8}
    assert station["draft"] is None                            # nothing to confirm before the end photos

    owl.counts = {"egg": 2}
    capture(app, "breakfast", "end")
    draft = day(app)["meals"][0]["stations"][0]["draft"]
    assert draft["status"] == "waiting"
    lines = {line["label"]: line for line in draft["foods"]}
    assert (lines["egg"]["start"], lines["egg"]["end"], lines["egg"]["dish"]) == (8, 2, "Egg curry")
    assert (lines["donut"]["start"], lines["donut"]["end"]) == (3, 0)
    with database(app) as db:
        assert scalar(db, "SELECT COUNT(*) FROM meal_check_drafts") == 1
    day(app)
    with database(app) as db:
        assert scalar(db, "SELECT COUNT(*) FROM meal_check_drafts") == 1   # pairing again adds nothing


def test_photos_show_their_counts_and_boxes_and_cameras_their_state(tmp_path):
    app = meal_app(tmp_path, CountingOwl(egg=2), cameras=STATIONS)
    capture(app, "lunch", "start")
    view = day(app)
    lunch = next(meal for meal in view["meals"] if meal["meal"] == "lunch")
    photo = lunch["stations"][0]["start"]["photos"][0]
    assert photo["countStatus"] == "counted" and photo["counts"]["egg"] == 2
    assert [match["label"] for match in photo["detections"]] == ["egg", "egg"]
    assert (photo["width"], photo["height"]) == (120, 80)
    assert client(app).get(photo["url"]).headers["content-type"] == "image/jpeg"
    assert [camera["state"] for camera in view["cameras"]] == ["ok", "ok"]
    assert view["counting"] == 0 and view["dates"] == [view["date"]]


def test_an_offline_camera_shows_as_offline(tmp_path):
    def camera(url):
        if "cam-two" in url:
            raise OSError("no route")
        return jpeg()
    app = meal_app(tmp_path, CountingOwl(), cameras=STATIONS, camera=camera)
    capture(app, "dinner", "start")
    states = {camera["station"]: camera["state"] for camera in day(app)["cameras"]}
    assert states == {"Station 1": "ok", "Station 2": "offline"}


def test_confirming_saves_meal_checks_waste_and_forecast_history(tmp_path):
    owl = CountingOwl(egg=8, donut=3)
    app = meal_app(tmp_path, owl)
    capture(app, "breakfast", "start")
    owl.counts = {"egg": 2}
    capture(app, "breakfast", "end")
    view = day(app)
    draft = view["meals"][0]["stations"][0]["draft"]
    browser = client(app)

    saved = browser.post(f"/api/captures/drafts/{draft['id']}/confirm", json=confirm_body(app, draft))
    assert saved.status_code == 200, saved.text
    result = saved.json()
    assert len(result["meal_check_ids"]) == 2                  # eggs and donuts were put out; the rest were not
    assert result["day_url"] == f"/days/{view['date']}"
    with database(app) as db:
        waste = sql(db, "SELECT quantity_kg, notes FROM waste_records WHERE id IN (%s)" %
                    ",".join(map(str, result["waste_record_ids"]))).all()
        checks = sql(db, "SELECT food_item, count_label, start_count, end_count, guest_count, meal_type FROM meal_checks "
                         "ORDER BY id").all()
    assert len(waste) == 1 and round(waste[0][0], 3) == 0.12   # 2 eggs x 0.06 kg; the donuts were all eaten
    assert [tuple(row) for row in checks] == [("Egg curry", "egg", 8, 2, 40, "Breakfast"),
                                              ("Dessert pudding", "donut", 3, 0, 40, "Breakfast")]
    page = browser.get(result["day_url"]).text
    assert "Egg: 2 of 8 left" in page                          # the day page names the counted food

    history = {item["food_item"]: item["history"] for item in browser.get("/api/forecast-history").json()["items"]}
    assert history["Egg curry"][0]["actual"] == 0.36           # 6 eggs eaten x 0.06 kg

    confirmed = day(app)["meals"][0]["stations"][0]["draft"]
    assert confirmed["status"] == "confirmed" and confirmed["guests"] == 40
    assert browser.post(f"/api/captures/drafts/{draft['id']}/confirm",
                        json=confirm_body(app, draft)).status_code == 409   # cannot be saved twice


def test_staff_corrections_and_shortages_are_saved(tmp_path):
    owl = CountingOwl(egg=8)
    app = meal_app(tmp_path, owl)
    capture(app, "breakfast", "start")
    owl.counts = {"egg": 0}
    capture(app, "breakfast", "end")
    draft = day(app)["meals"][0]["stations"][0]["draft"]
    body = confirm_body(app, draft)
    body["foods"] = [{"label": "egg", "start_count": 10, "end_count": 0, "short_count": 4}]   # staff counted 10
    result = client(app).post(f"/api/captures/drafts/{draft['id']}/confirm", json=body).json()
    with database(app) as db:
        rows = sql(db, "SELECT r.name, w.quantity_kg FROM waste_records w JOIN reasons r ON r.id = w.reason_id "
                       "WHERE w.id IN (%s)" % ",".join(map(str, result["waste_record_ids"]))).all()
    assert [(name, round(kg, 2)) for name, kg in rows] == [("Ran out (shortage)", 0.24)]


def test_bad_confirmations_save_nothing(tmp_path):
    owl = CountingOwl(egg=8)
    app = meal_app(tmp_path, owl)
    capture(app, "breakfast", "start")
    owl.counts = {"egg": 2}
    capture(app, "breakfast", "end")
    draft = day(app)["meals"][0]["stations"][0]["draft"]
    browser = client(app)
    url = f"/api/captures/drafts/{draft['id']}/confirm"

    bad = confirm_body(app, draft, guests=0)
    bad["foods"] = [{"label": "egg", "start_count": 2, "end_count": 5}, {"label": "pizza", "start_count": 1}]
    response = browser.post(url, json=bad)
    assert response.status_code == 400
    assert set(response.json()["fields"]) == {"guest_count", "foods.egg", "foods.pizza"}
    nothing = confirm_body(app, draft)
    nothing["foods"] = [{"label": "egg", "start_count": 0, "end_count": 0}]
    assert "nothing to save" in browser.post(url, json=nothing).json()["fields"]["foods"]
    assert browser.post("/api/captures/drafts/999/confirm", json=confirm_body(app, draft)).status_code == 404
    with database(app) as db:
        assert scalar(db, "SELECT COUNT(*) FROM meal_checks") == 0
        assert scalar(db, "SELECT status FROM meal_check_drafts") == "waiting"


def test_photos_are_served_only_by_id_from_the_captures_folder(tmp_path):
    app = meal_app(tmp_path, CountingOwl())
    capture(app, "lunch", "start")
    browser = client(app)
    assert browser.get("/captures/1/photo").status_code == 200
    assert browser.get("/captures/999/photo").status_code == 404
    (tmp_path / "secret.jpg").write_bytes(jpeg())
    with database(app) as db:
        sql(db, "UPDATE captures SET file_path = '../secret.jpg' WHERE id = 1")
        db.commit()
    assert browser.get("/captures/1/photo").status_code == 404   # nothing outside the captures folder


def test_the_food_list_can_be_edited(tmp_path):
    app = meal_app(tmp_path, CountingOwl())
    browser = client(app)
    foods = browser.get("/api/camera-foods").json()["foods"]
    assert [food["count_label"] for food in foods] == ["bread roll", "egg", "donut", "cupcake", "apple"]
    changed = [{**food, "kg_per_piece": 0.065} if food["count_label"] == "egg" else food
               for food in foods if food["count_label"] != "apple"]                     # apple left out
    changed.append({"count_label": "  Boiled   Egg ", "dish": "Egg curry", "kg_per_piece": 0.05})
    saved = browser.put("/api/camera-foods", json=changed).json()["foods"]
    by_label = {food["count_label"]: food for food in saved}
    assert by_label["egg"]["kg_per_piece"] == 0.065
    assert by_label["apple"]["active"] is False                 # switched off, not deleted
    assert by_label["boiled egg"]["active"] is True

    bad = browser.put("/api/camera-foods", json=[{"count_label": "x", "dish": "Pizza", "kg_per_piece": 0}])
    assert bad.status_code == 400 and set(bad.json()["fields"]) == {"0.count_label", "0.dish", "0.kg_per_piece"}
