"""Waste in money: approximate prices per food, values on every page, and the Food prices page."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.database.prices import DEFAULT_PRICES, MIXED_FOOD, ensure_price_data, price_map
from app.database.queries import (RecordFilters, create_user, create_waste_record, total_waste_kg, total_waste_value,
                                  waste_by)
from app.database.seed import seed_demo_data
from app.waste_records.common import DEMO_TIMEZONE
from conftest import client, database, make_app, scalar, sql
from test_camera_meals import CountingOwl, capture, confirm_body, day, meal_app

WHEN = datetime(2026, 10, 1, 12, 0, tzinfo=DEMO_TIMEZONE)


def app_with_prices(tmp_path, **config):
    app = make_app(tmp_path, **config)
    with database(app) as db:
        seed_demo_data(db)
    return app


def food_id(db, name):
    return scalar(db, "SELECT id FROM categories WHERE lower(name) = lower(:name)", name=name)


def add(db, food, kg, *, reason="Spoilage", when=WHEN, notes=""):
    user = scalar(db, "SELECT id FROM users WHERE username = 'demo_entry'")
    return create_waste_record(
        db, event_at=when, area_id=scalar(db, "SELECT id FROM areas WHERE name = 'Buffet'"), category_id=food_id(db, food),
        reason_id=scalar(db, "SELECT id FROM reasons WHERE name = :name", name=reason), quantity_kg=kg, user_id=user, notes=notes)


# ---- setting up foods and prices ------------------------------------------------------------

def test_foods_and_approximate_prices_are_set_up_once(tmp_path):
    app = make_app(tmp_path)
    with database(app) as db:
        assert ensure_price_data(db) is True
        prices = dict(sql(db, "SELECT c.name, p.price_per_kg FROM food_prices p JOIN categories c ON c.id = p.category_id").all())
        assert prices == {name: float(price) for name, price in DEFAULT_PRICES.items()}
        assert {"Fried rice", "Chicken curry", "Egg", "Cupcake", MIXED_FOOD} <= set(prices)

        sql(db, "UPDATE food_prices SET price_per_kg = 777 WHERE category_id = :id", id=food_id(db, "Fried rice"))
        db.commit()
        assert ensure_price_data(db) is True                                    # running again changes nothing
        assert scalar(db, "SELECT price_per_kg FROM food_prices WHERE category_id = :id", id=food_id(db, "Fried rice")) == 777
        assert scalar(db, "SELECT COUNT(*) FROM categories") == len(DEFAULT_PRICES)


def test_an_uninitialized_database_is_left_alone(tmp_path):
    app = make_app(tmp_path, initialize=False)
    with database(app) as db:
        assert ensure_price_data(db) is False


def test_older_records_are_sorted_into_their_foods(tmp_path):
    app = make_app(tmp_path)
    with database(app) as db:
        sql(db, "INSERT INTO categories (name, active) VALUES ('Whole waste', 1)")       # the earlier name of Mixed food
        sql(db, "INSERT INTO areas (name, active) VALUES ('Buffet', 1)")
        sql(db, "INSERT INTO reasons (name, active) VALUES ('Spoilage', 1)")
        sql(db, "INSERT INTO users (name, username, password_hash, role, active) VALUES ('K', 'demo_entry', 'x', 'entry', 1)")
        db.commit()
        placeholder = scalar(db, "SELECT id FROM categories WHERE name = 'Whole waste'")
        for kg, notes in ((2, json.dumps({"meal_type": "Lunch", "food_item": "Fried rice", "guest_count": 5})),
                          (1, json.dumps({"source": "photo count", "item": "Egg curry", "label": "egg"})),
                          (3, json.dumps({"food_item": "Mystery stew"})), (4, "plain note"), (5, "")):
            sql(db, "INSERT INTO waste_records (event_at, area_id, category_id, reason_id, quantity_kg, user_id, notes, created_at, updated_at) "
                    "VALUES ('2026-10-01T05:00:00Z', 1, :c, 1, :kg, 1, :n, 'x', 'x')", c=placeholder, kg=kg, n=notes)
        db.commit()
        ensure_price_data(db)
        foods = [row[0] for row in sql(db, "SELECT c.name FROM waste_records w JOIN categories c ON c.id = w.category_id ORDER BY w.id").all()]
    assert foods == ["Fried rice", "Egg", "Mystery stew", MIXED_FOOD, MIXED_FOOD]     # the photo label beats its dish; unknown notes stay mixed
    with database(app) as db:
        assert scalar(db, "SELECT COUNT(*) FROM categories WHERE name = 'Whole waste'") == 0   # renamed


# ---- the maths ------------------------------------------------------------------------------

def test_value_is_kilograms_times_the_price_of_the_food(tmp_path):
    app = app_with_prices(tmp_path)
    with database(app) as db:
        add(db, "Fried rice", 2)            # Rs 600/kg
        add(db, "Chicken curry", 1.5)       # Rs 1,000/kg
        # the three demo records (Rs 840 + 3,060 + 960) plus these two (Rs 1,200 + 1,500)
        assert round(total_waste_value(db)) == 7560 and total_waste_kg(db) == pytest.approx(3.5 + 5.1 + 2.4 + 1.2)
        by_food = {name: (round(kg, 2), round(value)) for name, kg, value in waste_by(db, "categories")}
    assert by_food["Fried rice"] == (7.1, 4260)               # the 5.1 kg demo record plus 2 kg
    assert by_food["Chicken curry"] == (1.5, 1500)


def test_foods_are_ranked_by_what_they_cost_not_by_weight(tmp_path):
    app = app_with_prices(tmp_path)
    with database(app) as db:
        sql(db, "DELETE FROM waste_records")
        db.commit()
        add(db, "Salad", 5)                 # heavy but cheap: Rs 2,250
        add(db, "Fish curry", 2)            # light but dear: Rs 2,600
        ranked = [(name, round(value)) for name, _, value in waste_by(db, "categories")]
    assert ranked == [("Fish curry", 2600), ("Salad", 2250)]


def test_shortages_are_not_counted_as_waste_value(tmp_path):
    app = app_with_prices(tmp_path)
    with database(app) as db:
        before = total_waste_value(db)
        add(db, "Fried rice", 10, reason="Ran out (shortage)")
        assert total_waste_value(db) == before


def test_a_food_without_a_price_uses_the_mixed_food_price(tmp_path):
    app = app_with_prices(tmp_path)
    with database(app) as db:
        sql(db, "INSERT INTO categories (name, active) VALUES ('Boiled egg', 1)")
        db.commit()
        add(db, "Boiled egg", 2)
        base = total_waste_value(db)
        sql(db, "UPDATE food_prices SET price_per_kg = 1000 WHERE category_id = :id", id=food_id(db, MIXED_FOOD))
        db.commit()
        assert total_waste_value(db) == pytest.approx(base + 2 * 400)          # 2 kg now at Rs 1,000 instead of Rs 600
        sql(db, "DELETE FROM food_prices WHERE category_id = :id", id=food_id(db, MIXED_FOOD))
        db.commit()
        assert total_waste_value(db) == pytest.approx(base - 2 * 600 + 2 * 600)   # no mixed price at all: the built-in Rs 600
        assert price_map(db)["mixed"] == 600


def test_changing_a_price_changes_every_value_of_that_food(tmp_path):
    app = app_with_prices(tmp_path)
    with database(app) as db:
        add(db, "Fried rice", 10)
        one = total_waste_value(db, RecordFilters(category_id=food_id(db, "Fried rice")))
        sql(db, "UPDATE food_prices SET price_per_kg = 1200 WHERE category_id = :id", id=food_id(db, "Fried rice"))
        db.commit()
        assert total_waste_value(db, RecordFilters(category_id=food_id(db, "Fried rice"))) == pytest.approx(one * 2)


# ---- pages ----------------------------------------------------------------------------------

def test_the_overview_leads_with_money_and_breaks_it_down_by_food(tmp_path):
    app = app_with_prices(tmp_path)
    with database(app) as db:
        sql(db, "DELETE FROM waste_records")
        db.commit()
        add(db, "Fish curry", 2, when=datetime.now(DEMO_TIMEZONE))
        add(db, "Salad", 5, when=datetime.now(DEMO_TIMEZONE) - timedelta(days=1))
    html = client(app).get("/").text
    assert "Waste value" in html and "4,850" in html and "7.00 kg" in html          # Rs 2,600 + Rs 2,250; the weight stays underneath
    assert "Where the waste cost comes from" in html and "<h3 id=\"food-title\">By food</h3>" in html
    assert html.index("Fish curry") < html.index("Salad")                             # most costly first
    assert 'aria-label="Fish curry: 2.00 kilograms, about Rs 2,600"' in html
    assert "Values are estimates" in html and 'href="/food-prices"' in html
    assert '"currency": "Rs"' in html.replace("&#34;", '"')                          # the chart knows the currency


def test_each_record_on_a_day_page_shows_its_food_and_what_it_cost(tmp_path):
    app = app_with_prices(tmp_path)
    with database(app) as db:
        sql(db, "DELETE FROM waste_records")
        db.commit()
        add(db, "Chicken curry", 1.5)
        add(db, "Salad", 2, when=WHEN + timedelta(hours=8))
    page = client(app).get("/days/2026-10-01").text
    assert "Chicken curry" in page and "Salad" in page
    assert "≈ Rs 1,500 lost" in page and "≈ Rs 900 lost" in page                   # per record
    assert "2,400" in page                                                           # the day's total, beside a small Rs
    assert "Rs 1,500 · 1.50 kg thrown away" in page                                # a meal's subtotal


def test_the_overview_can_be_filtered_by_food(tmp_path):
    app = app_with_prices(tmp_path)
    with database(app) as db:
        sql(db, "DELETE FROM waste_records")
        db.commit()
        add(db, "Fish curry", 2)
        add(db, "Salad", 5)
        fish = food_id(db, "Fish curry")
    page = client(app).get(f"/?category_id={fish}").text
    assert "1 record matching filters" in page and "2,600" in page and "2,250" not in page


# ---- recording waste by food ----------------------------------------------------------------

def form_for(app, **changes):
    with database(app) as db:
        body = {"event_at": "2026-10-02T12:30", "area_id": scalar(db, "SELECT id FROM areas WHERE name = 'Buffet'"),
                "category_id": food_id(db, "Steamed rice"), "reason_id": scalar(db, "SELECT id FROM reasons WHERE name = 'Spoilage'"),
                "quantity_kg": "4"}
    return {**body, **changes}


def test_a_waste_record_says_which_food_it_is(tmp_path):
    app = app_with_prices(tmp_path)
    browser = client(app)
    panel = browser.get("/records/new").text
    assert 'name="category_id"' in panel and "Select the food" in panel and 'id="cost-preview"' in panel
    foods = panel.split("<dialog")[1].split('id="food"')[1].split("</select>")[0]
    assert foods.index("Steamed rice") < foods.index(">Mixed food<") and foods.rindex("<option") > foods.index(">Mixed food<") - 40   # Mixed food is last
    assert '"mixed": 600.0' in panel.replace("&#34;", '"')

    saved = browser.post("/records/new", data=form_for(app))
    assert saved.status_code == 303
    page = browser.get(saved.headers["location"]).text
    assert "Steamed rice" in page and "≈ Rs 1,000 lost" in page                      # 4 kg at Rs 250
    with database(app) as db:
        assert scalar(db, "SELECT c.name FROM waste_records w JOIN categories c ON c.id = w.category_id ORDER BY w.id DESC LIMIT 1") == "Steamed rice"


def test_the_food_is_required_and_must_be_real(tmp_path):
    app = app_with_prices(tmp_path)
    browser = client(app)
    missing = browser.post("/records/new", data=form_for(app, category_id=""))
    assert missing.status_code == 400 and "Select a food." in missing.text
    unknown = browser.post("/records/new", data=form_for(app, category_id="99999"))
    assert unknown.status_code == 400 and "Select a valid food." in unknown.text
    assert 'value="4"' in unknown.text                                              # what was typed is kept


def test_a_record_can_be_changed_to_another_food(tmp_path):
    app = app_with_prices(tmp_path)
    browser = client(app)
    record = browser.post("/records/new", data=form_for(app)).headers["location"]
    with database(app) as db:
        record_id = scalar(db, "SELECT MAX(id) FROM waste_records")
    edit = browser.get(f"/records/{record_id}/edit").text
    assert f'<option value="{form_for(app)["category_id"]}" selected>Steamed rice</option>' in edit
    with database(app) as db:
        fish = food_id(db, "Fish curry")
    assert browser.post(f"/records/{record_id}/edit", data=form_for(app, category_id=fish)).status_code == 303
    assert "≈ Rs 5,200 lost" in browser.get("/days/2026-10-02").text                 # 4 kg of Fish curry at Rs 1,300


# ---- the Food prices page -------------------------------------------------------------------

def test_the_food_prices_page_lists_every_food_with_its_price(tmp_path):
    app = app_with_prices(tmp_path)
    page = client(app).get("/food-prices").text
    assert "<h1>Food prices</h1>" in page and 'aria-current="page"' in page and "rough estimates" in page
    with database(app) as db:
        fried, mixed = food_id(db, "Fried rice"), food_id(db, MIXED_FOOD)
    assert f'name="price_{fried}"' in page and 'value="600"' in page
    assert page.index("Vegetable curry") < page.index("Used for any food without its own price")    # Mixed food is last
    assert "Add a food" in page and "1 record" in page


def test_saving_prices_updates_every_value(tmp_path):
    app = app_with_prices(tmp_path)
    browser = client(app)
    with database(app) as db:
        fried, steamed = food_id(db, "Fried rice"), food_id(db, "Steamed rice")
        before = total_waste_value(db)
    with database(app) as db:       # the real form sends every price, as shown
        body = {f"price_{row[0]}": f"{row[1]:g}" for row in sql(db, "SELECT category_id, price_per_kg FROM food_prices").all()}
    body.update({f"price_{fried}": "1,200", f"price_{steamed}": "", "new_name": "  Boiled   egg ", "new_price": "700"})
    response = browser.post("/food-prices", data=body)
    assert response.status_code == 303 and response.headers["location"] == "/food-prices?saved=1"
    assert "Prices saved." in browser.get(response.headers["location"]).text
    with database(app) as db:
        assert scalar(db, "SELECT price_per_kg FROM food_prices WHERE category_id = :id", id=fried) == 1200
        assert scalar(db, "SELECT COUNT(*) FROM food_prices WHERE category_id = :id", id=steamed) == 0     # blank: use Mixed food
        assert scalar(db, "SELECT p.price_per_kg FROM food_prices p JOIN categories c ON c.id = p.category_id "
                          "WHERE c.name = 'Boiled egg'") == 700
        assert total_waste_value(db) == pytest.approx(before + 5.1 * 600)       # the 5.1 kg of fried rice now costs twice as much
    assert "Using Rs 600" in browser.get("/food-prices").text                  # the unpriced food says what it uses


def test_bad_prices_are_explained_and_nothing_is_saved(tmp_path):
    app = app_with_prices(tmp_path)
    browser = client(app)
    with database(app) as db:
        fried, mixed = food_id(db, "Fried rice"), food_id(db, MIXED_FOOD)
    response = browser.post("/food-prices", data={f"price_{fried}": "free", f"price_{mixed}": "", "new_name": "Fried rice", "new_price": "-5"})
    assert response.status_code == 400
    page = response.text
    assert "Enter a price above 0" in page and "Mixed food needs a price" in page
    assert "already on the list" in page and 'value="free"' in page                  # what was typed is kept
    with database(app) as db:
        assert scalar(db, "SELECT price_per_kg FROM food_prices WHERE category_id = :id", id=fried) == 600


def test_prices_need_a_sign_in_when_sign_in_is_required(tmp_path):
    app = make_app(tmp_path, REQUIRE_LOGIN=True)
    with database(app) as db:
        seed_demo_data(db)
        create_user(db, name="Mira", username="mira", password="a long password", role="manager")
    browser = client(app)
    assert browser.get("/food-prices").status_code == 303
    assert browser.post("/food-prices", data={}).status_code == 303
    browser.post("/login", data={"username": "mira", "password": "a long password"})
    assert browser.get("/food-prices").status_code == 200


# ---- the camera flow ------------------------------------------------------------------------

def test_camera_meal_checks_record_the_counted_food_and_show_its_cost(tmp_path):
    owl = CountingOwl(egg=8, donut=3)
    app = meal_app(tmp_path, owl)
    capture(app, "breakfast", "start")
    owl.counts = {"egg": 2}
    capture(app, "breakfast", "end")
    draft = day(app)["meals"][0]["stations"][0]["draft"]
    lines = {line["label"]: line for line in draft["foods"]}
    assert lines["egg"]["pricePerKg"] == 650 and lines["donut"]["pricePerKg"] == 1400    # the counted foods' own prices

    browser = client(app)
    result = browser.post(f"/api/captures/drafts/{draft['id']}/confirm", json=confirm_body(app, draft)).json()
    with database(app) as db:
        foods = [row[0] for row in sql(db, "SELECT c.name FROM waste_records w JOIN categories c ON c.id = w.category_id "
                                           f"WHERE w.id IN ({','.join(map(str, result['waste_record_ids']))})").all()]
    assert foods == ["Egg"]                                                           # the counted food, not just its menu dish
    page = browser.get(result["day_url"]).text
    assert "Egg: 2 of 8 left" in page and "≈ Rs 78 lost" in page                      # 2 eggs x 0.06 kg x Rs 650
    confirmed = day(app)["meals"][0]["stations"][0]["draft"]
    assert confirmed["foods"][0]["wasteValue"] == 78


def test_the_camera_page_knows_the_currency(tmp_path):
    from html import unescape
    app = meal_app(tmp_path, CountingOwl())
    html = unescape(client(app).get("/food-counting").text)
    assert '"currency": "Rs"' in html


def test_amounts_are_shown_in_whole_rupees(tmp_path):
    from app.web import templates
    money = templates.env.filters["money"]
    amount = templates.env.filters["amount"]
    templates.env.globals["CURRENCY_SYMBOL"] = "Rs"
    assert amount(12340.6) == "12,341" and amount(0) == "0" and amount(None) == "0" and amount(999999.4) == "999,999"
    assert templates.env.from_string("{{ x|money }}").render(x=1234567.2) == "Rs 1,234,567"
