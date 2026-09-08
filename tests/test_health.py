from app.main import app
from fastapi.testclient import TestClient


def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_frontend_is_served() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "What should we watch?" in response.text
    assert "Movie night" in response.text
    assert "Profiles" in response.text
    assert "History, stats &amp; settings" in response.text
    assert "Add or edit one movie" in response.text
    assert "Model accuracy" in response.text
    assert 'data-user=""' in response.text
    assert "This copy of Movie Compass has no personal data" in response.text
