from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.api import create_app
from app.projects import ProjectStore


def test_general_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with TestClient(create_app()) as client:
        initial = client.get("/api/settings")
        assert initial.status_code == 200
        assert initial.json() == {
            "api_key": "",
            "api_key_configured": False,
            "api_key_source": "none",
        }

        saved = client.put("/api/settings", json={"api_key": " sk-general "})
        assert saved.status_code == 200
        assert saved.json()["api_key"] == "sk-general"
        assert saved.json()["api_key_source"] == "settings"

    payload = yaml.safe_load((tmp_path / "settings.yaml").read_text(encoding="utf-8"))
    assert payload == {"deepseek": {"api_key": "sk-general"}}


def test_general_settings_uses_environment_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-environment")

    with TestClient(create_app()) as client:
        response = client.get("/api/settings")

    assert response.json() == {
        "api_key": "",
        "api_key_configured": True,
        "api_key_source": "environment",
    }


def test_general_settings_rejects_unknown_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path))
    with TestClient(create_app()) as client:
        response = client.put(
            "/api/settings",
            json={"api_key": "sk-general", "project_id": "legacy"},
        )

    assert response.status_code == 422


def test_legacy_project_key_migrates_once_and_is_hidden(tmp_path, monkeypatch):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    store = ProjectStore(str(tmp_path / "projects.db"))
    project = store.create_project("Legacy", str(tmp_path / "legacy"), "")
    yaml_path = Path(project["path"]) / "project.yaml"
    payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    payload["analysis"]["api_key"] = "sk-legacy"
    yaml_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with TestClient(create_app()) as client:
        settings = client.get("/api/settings")
        project_response = client.get(f"/api/projects/{project['id']}")

    assert settings.json()["api_key"] == "sk-legacy"
    assert settings.json()["api_key_source"] == "settings"
    assert "api_key" not in project_response.json()["analysis"]
