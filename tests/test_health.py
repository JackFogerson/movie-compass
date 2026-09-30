from importlib import import_module

from app.main import app
from fastapi.testclient import TestClient


def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_tmdb_status_actively_checks_configured_connection(monkeypatch) -> None:
    main_module = import_module("app.main")

    class ConnectedClient:
        def __init__(self, key):
            assert key == "test-key"

        def check_connection(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(main_module.settings, "tmdb_api_key", "test-key")
    monkeypatch.setattr(main_module, "TmdbClient", ConnectedClient)

    result = main_module.tmdb_status()

    assert result["live"] is True
    assert result["fallback_available"] is True


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
