import pytest

from app.database.seed import seed_demo_data
from conftest import client, database, make_app


@pytest.mark.parametrize(
    ("path", "heading", "current_path"),
    [
        ("/", "Food waste dashboard", 'href="/" aria-current="page"'),
        ("/records", "Waste records", 'href="/records" aria-current="page"'),
        ("/records/new", "Add waste record", 'href="/records/new" aria-current="page"'),
        ("/forecast", "Meal demand forecast", 'href="/forecast" aria-current="page"'),
        ("/food-prediction", "Food image prediction", 'href="/food-prediction" aria-current="page"'),
        ("/food-counting", "Food counting", 'href="/food-counting" aria-current="page"'),
    ],
)
def test_main_pages_and_navigation(path, heading, current_path, tmp_path):
    app = make_app(tmp_path)
    with database(app) as db:
        seed_demo_data(db)
    response = client(app).get(path)

    assert response.status_code == 200
    html = response.text
    assert f"<h1>{heading}</h1>" in html
    assert current_path in html
    assert 'href="/"' in html
    assert 'href="/records"' in html
    assert 'href="/records/new"' in html
    assert html.count('aria-current="page"') == 1
    assert 'href="/static/styles.css"' in html


def test_static_files_and_api_docs_are_served(tmp_path):
    browser = client(make_app(tmp_path))
    assert browser.get("/static/styles.css").status_code == 200
    assert browser.get("/static/react/forecast.js").status_code == 200
    schema = browser.get("/openapi.json").json()
    assert set(schema["paths"]) == {
        "/api/predict-meal", "/api/forecast-history", "/api/food-predict", "/api/food-count",
    }
    assert browser.get("/docs").status_code == 200


def test_unknown_pages_and_oversized_uploads(tmp_path):
    browser = client(make_app(tmp_path))
    missing = browser.get("/no-such-page")
    assert missing.status_code == 404
    assert "Page not found" in missing.text
    assert browser.get("/api/no-such-api").json() == {"error": "Not Found"}

    too_big = browser.post("/api/food-count", content=b"x" * (10 * 1024 * 1024),
                           headers={"content-type": "application/octet-stream"})
    assert too_big.status_code == 413
    assert "smaller than 8 MB" in too_big.json()["error"]
