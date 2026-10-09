import pytest

from app import create_app
from app.db import get_db, init_db
from app.seed import seed_demo_data


@pytest.mark.parametrize(
    ("path", "heading", "current_path"),
    [
        ("/", "Food waste dashboard", 'href="/" aria-current="page"'),
        ("/records", "Waste records", 'href="/records" aria-current="page"'),
        ("/records/new", "Add waste record", 'href="/records/new" aria-current="page"'),
    ],
)
def test_main_pages_and_navigation(path, heading, current_path, tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite3")})
    with app.app_context():
        init_db()
        seed_demo_data(get_db())
    client = app.test_client()
    response = client.get(path)

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert f"<h1>{heading}</h1>" in html
    assert current_path in html
    assert 'href="/"' in html
    assert 'href="/records"' in html
    assert 'href="/records/new"' in html
