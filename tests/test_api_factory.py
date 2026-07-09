from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.api.deps import get_project_store
from app.projects import ProjectStore


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path))
    _app = create_app()
    yield _app
    _app.dependency_overrides.clear()


def test_stub_routes_return_501(app):
    with TestClient(app) as client:
        for path in ["/api/runs", "/api/agent"]:
            response = client.get(path)
            assert response.status_code == 501, (
                f"{path} expected 501, got {response.status_code}"
            )


def test_spa_fallback_or_404(app):
    with TestClient(app) as client:
        response = client.get("/some-spa-route")
    dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist_dir.exists() and (dist_dir / "index.html").exists():
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
    else:
        assert response.status_code == 404


def test_project_store_dependency_override(app, tmp_path):
    override_db = tmp_path / "override.db"
    store = ProjectStore(str(override_db))
    store.create_project("Override", str(tmp_path / "Override"), "override test")

    app.dependency_overrides[get_project_store] = lambda: store
    with TestClient(app) as client:
        response = client.get("/api/projects")
    assert response.status_code == 200
    projects = response.json()
    assert len(projects) == 1
    assert projects[0]["name"] == "Override"
