from datetime import datetime, timedelta, timezone

import pytest

from app.database.queries import create_user, create_waste_record
from app.waste_records.common import DEMO_TIMEZONE
from app.database.prices import ensure_price_data
from conftest import add_lookups, client, database, make_app, scalar, sql


@pytest.fixture
def overview_app(tmp_path, monkeypatch):
    app = make_app(tmp_path, "overview.sqlite3")
    monkeypatch.setattr("app.waste_records.overview._now_local",
                        lambda: datetime(2026, 10, 2, 12, tzinfo=DEMO_TIMEZONE))
    with database(app) as db:
        add_lookups(db, {"areas": ["Kitchen", "Buffet"], "categories": ["Vegetables", "Bakery"],
                         "reasons": ["Spoilage", "Overproduction"]})
        user = create_user(db, name="Staff", username="staff", password="test", role="entry")
        ids = {
            table: {row.name: row.id for row in sql(db, f"SELECT id, name FROM {table}")}
            for table in ("areas", "categories", "reasons")
        }
    return app, user.id, ids


def add_record(app, user_id, ids, when, kg, area="Kitchen", category="Vegetables", reason="Spoilage"):
    with database(app) as db:
        return create_waste_record(
            db, event_at=datetime.fromisoformat(when).replace(tzinfo=DEMO_TIMEZONE),
            area_id=ids["areas"][area], category_id=ids["categories"][category],
            reason_id=ids["reasons"][reason], quantity_kg=kg, user_id=user_id,
        )


def test_empty_overview_invites_the_first_record(overview_app):
    app, *_ = overview_app
    page = client(app).get("/")
    assert page.status_code == 200
    assert "No waste records yet" in page.text
    assert "0.00" in page.text
    assert 'href="/records/new"' in page.text
    assert "<dialog" not in page.text


def test_overview_uses_stored_rows_and_local_calendar_boundaries(overview_app):
    app, user_id, ids = overview_app
    entries = [
        ("2026-09-27T23:59", 1, "Kitchen", "Vegetables", "Spoilage"),
        ("2026-09-28T00:00", 2, "Kitchen", "Vegetables", "Spoilage"),
        ("2026-09-30T23:59", 3, "Buffet", "Bakery", "Overproduction"),
        ("2026-10-01T00:00", 4, "Buffet", "Bakery", "Overproduction"),
        ("2026-10-02T00:00", 5, "Buffet", "Vegetables", "Spoilage"),
        ("2026-10-02T23:59", 6, "Kitchen", "Bakery", "Overproduction"),
        ("2026-10-03T00:00", 7, "Kitchen", "Vegetables", "Spoilage"),
    ]
    for when, kg, area, category, reason in entries:
        add_record(app, user_id, ids, when, kg, area, category, reason)

    html = client(app).get("/").text
    for label, value in (("Waste value", "28.00"), ("Today", "11.00"),
                         ("This week", "20.00"), ("This month", "15.00")):
        assert label in html
        assert value in html                                  # the kilograms are still shown under each value
    assert "7 records" in html
    # Vegetables 15 kg at Rs 350 and Bakery 13 kg at Rs 900: the money leads, and food is a breakdown too.
    assert "16,950" in html and "Rs 11,700" in html and "Rs 5,250" in html
    assert 'aria-label="Bakery: 13.00 kilograms, about Rs 11,700"' in html
    assert "Kitchen: 16.00 kilograms" in html
    assert "Buffet: 12.00 kilograms" in html
    assert "Spoilage: 15.00 kilograms" in html
    # One row per day, newest first; only the newest five days are listed to begin with.
    assert "03 Oct 2026" in html and "28 Sep 2026" in html and "27 Sep 2026" not in html
    assert "See 1 more day" in html and "Waste by day" in html
    assert "FW-" not in html                                  # records are listed inside each day
    day = client(app).get("/days/2026-10-02").text           # the day panel lists that day's records
    assert "<h1>02 Oct 2026</h1>" in day
    assert "FW-005" in day and "FW-006" in day and "FW-004" not in day
    assert "Breakfast" in day and "Dinner" in day            # 00:00 and 23:59 local time
    assert "sample data" not in html.lower()


def test_one_set_of_filters_drives_totals_and_records(overview_app):
    app, user_id, ids = overview_app
    first = add_record(app, user_id, ids, "2026-10-01T00:00", 4, "Buffet", "Bakery", "Overproduction")
    other = add_record(app, user_id, ids, "2026-10-02T00:00", 5, "Buffet", "Vegetables", "Spoilage")
    browser = client(app)
    query = (f"start_date=2026-10-01&end_date=2026-10-01&area_id={ids['areas']['Buffet']}"
             f"&reason_id={ids['reasons']['Overproduction']}")
    page = browser.get(f"/?{query}").text
    assert "4.00" in page
    assert "1 record matching filters" in page
    day = browser.get(f"/days/2026-10-01?{query}").text
    assert f"FW-{first.id:03d}" in day
    assert f"FW-{other.id:03d}" not in day

    with database(app) as db:
        sql(db, "UPDATE waste_records SET quantity_kg = 8 WHERE id = :id", id=first.id)
        db.commit()
    updated = browser.get(f"/?{query}").text
    assert "8.00" in updated and "4.00" not in updated

    invalid = browser.get("/?start_date=2026-10-03&end_date=2026-10-01")
    assert invalid.status_code == 400
    assert "To date must be on or after From date" in invalid.text
    assert "Waste summary" not in invalid.text

    no_match = browser.get("/?start_date=2026-11-01")
    assert no_match.status_code == 200
    assert "No matching records" in no_match.text
    assert "No records match these filters" in no_match.text

    bad_reason = browser.get("/?reason_id=999")
    assert bad_reason.status_code == 400
    assert "Select a valid reason" in bad_reason.text
    page = browser.get("/").text
    assert "All foods" in page and 'name="category_id"' in page             # records can be filtered by food
    by_food = browser.get(f"/?category_id={ids['categories']['Bakery']}").text
    assert "1 record matching filters" in by_food and "Rs 7,200" in by_food     # 8 kg of Bakery at Rs 900
    assert browser.get("/?category_id=999").status_code == 400


def test_record_row_shows_local_time_user_and_edit_link(overview_app):
    app, user_id, ids = overview_app
    with database(app) as db:
        demo = create_user(db, name="Demo Kitchen Staff", username="demo_entry",
                           password="test password", role="entry")
        record = create_waste_record(
            db, event_at=datetime(2026, 9, 30, 19, 0, tzinfo=timezone.utc), area_id=ids["areas"]["Kitchen"],
            category_id=ids["categories"]["Vegetables"], reason_id=ids["reasons"]["Spoilage"],
            quantity_kg=1.25, user_id=demo.id)
    assert 'href="/days/2026-10-01"' in client(app).get("/").text
    page = client(app).get("/days/2026-10-01").text
    for expected in ("FW-001", "01 Oct 2026", "00:30", "Kitchen", "Spoilage", "Breakfast", "Thrown away",
                     "Demo Kitchen Staff", "1.25 kg", f"/records/{record.id}/edit"):
        assert expected in page


def test_days_start_at_five_and_see_more_adds_older_ones(overview_app):
    app, user_id, ids = overview_app
    newest = datetime(2026, 10, 1, 6, tzinfo=timezone.utc)
    with database(app) as db:
        for days_back in range(40):
            create_waste_record(db, event_at=newest - timedelta(days=days_back), area_id=ids["areas"]["Kitchen"],
                                category_id=1, reason_id=1, quantity_kg=1, user_id=user_id)
    browser = client(app)
    area = f"area_id={ids['areas']['Kitchen']}"

    first = browser.get(f"/?{area}").text
    assert "Showing 5 of 40 days" in first
    assert "01 Oct 2026" in first and "27 Sep 2026" in first and "26 Sep 2026" not in first
    assert "See 20 more days" in first and "35 older days not shown" in first
    assert f'href="/?{area}&amp;show=25#records"' in first
    assert "Show fewer" not in first
    assert "40 records matching filters" in first  # totals cover every record

    more = browser.get(f"/?{area}&show=25").text
    assert "Showing 25 of 40 days" in more
    assert "07 Sep 2026" in more and "06 Sep 2026" not in more
    assert "Show fewer" in more and f'href="/?{area}#records"' in more

    everything = browser.get(f"/?{area}&show=45").text
    assert "23 Aug 2026" in everything and "See " not in everything.split("see-more")[1]
    assert "Showing 40 of 40 days" in everything
    assert "26 Sep 2026" not in browser.get(f"/?{area}&show=abc").text


def test_weights_are_banded_green_amber_red():
    from app.waste_records.common import weight_band

    assert [weight_band(kg) for kg in (0.5, 1.99, 2, 4.99, 5, 12)] == [
        "light", "light", "moderate", "moderate", "heavy", "heavy"]


def test_shortages_stay_out_of_waste_totals_and_go_below_zero_on_the_daily_chart(overview_app):
    from datetime import date

    from app.database.queries import RecordFilters
    from app.waste_records.common import weight_band
    from app.waste_records.overview import build_daily

    app, user_id, ids = overview_app
    with database(app) as db:
        sql(db, "INSERT INTO reasons (name, active) VALUES ('Ran out (shortage)', 1)")
        db.commit()
        short_id = scalar(db, "SELECT id FROM reasons WHERE name = 'Ran out (shortage)'")
    add_record(app, user_id, ids, "2026-10-01T10:00", 4)
    add_record(app, user_id, ids, "2026-10-02T09:00", 2)
    with database(app) as db:
        create_waste_record(db, event_at=datetime(2026, 10, 1, 20, 0, tzinfo=DEMO_TIMEZONE),
                            area_id=ids["areas"]["Kitchen"], category_id=ids["categories"]["Vegetables"],
                            reason_id=short_id, quantity_kg=3, user_id=user_id)
        ensure_price_data(db)               # the prices the app sets up before showing any page
        days = build_daily(db, RecordFilters(), date(2026, 10, 2))

    assert len(days) == 30 and days[0]["date"] == "2026-09-03" and days[-1]["date"] == "2026-10-02"
    assert days[-2] == {"date": "2026-10-01", "waste": 4.0, "short": 3.0, "waste_value": 1400, "short_value": 1050}
    assert days[-1] == {"date": "2026-10-02", "waste": 2.0, "short": 0.0, "waste_value": 700, "short_value": 0}
    assert sum(d["waste"] for d in days) == 6.0

    page = client(app).get("/").text
    assert "6.00" in page and "9.00" not in page           # the 3 kg shortage is not waste
    assert "Waste each day, last 30 days" in page and 'id="daily-waste-root"' in page
    assert "\u22123.00 kg" in page and "weight-short" in page   # the day row shows the shortage
    day = client(app).get("/days/2026-10-01").text
    assert "\u22123 kg" in day and "Ran out of food" in day and "+4 kg" in day
    assert weight_band(3, "Ran out (shortage)") == "short"


def test_each_day_has_its_own_page_and_old_day_links_redirect(overview_app):
    app, user_id, ids = overview_app
    add_record(app, user_id, ids, "2026-10-01T08:00", 2)
    add_record(app, user_id, ids, "2026-10-03T13:00", 3)
    browser = client(app)
    page = browser.get("/days/2026-10-03").text
    assert "<h1>03 Oct 2026</h1>" in page and "Back to waste overview" in page
    assert 'href="/days/2026-10-01"' in page                 # previous day with records
    assert "Lunch" in page and "+3 kg" in page and "Nothing was recorded for breakfast" in page
    old = browser.get("/?day=2026-10-03&area_id=1")
    assert old.status_code == 308 and old.headers["location"] == "/days/2026-10-03?area_id=1"
    assert browser.get("/days/2026-13-40").status_code == 404
