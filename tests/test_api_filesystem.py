import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import create_app
from app.api import filesystem as filesystem_api


def test_filesystem_roots_and_entries(monkeypatch, tmp_path):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path / "data"))
    folder = tmp_path / "images"
    folder.mkdir()
    (folder / "nested").mkdir()
    (folder / "clinical.csv").write_text("id,label\n1,0\n", encoding="utf-8")

    with TestClient(create_app()) as client:
        roots_response = client.get("/api/filesystem/roots")
        entries_response = client.get(
            "/api/filesystem/entries", params={"path": str(folder)}
        )

    assert roots_response.status_code == 200
    assert roots_response.json()["roots"]
    assert entries_response.status_code == 200
    payload = entries_response.json()
    assert payload["path"] == str(folder.resolve())
    assert payload["parent"] == str(folder.parent.resolve())
    assert [item["name"] for item in payload["entries"]] == [
        "nested",
        "clinical.csv",
    ]
    assert payload["entries"][0]["is_dir"] is True


def test_filesystem_entries_rejects_missing_and_file_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path / "data"))
    file_path = tmp_path / "clinical.csv"
    file_path.write_text("id,label\n", encoding="utf-8")

    with TestClient(create_app()) as client:
        missing = client.get(
            "/api/filesystem/entries", params={"path": str(tmp_path / "missing")}
        )
        not_directory = client.get(
            "/api/filesystem/entries", params={"path": str(file_path)}
        )

    assert missing.status_code == 404
    assert not_directory.status_code == 400


def test_filesystem_rejects_non_loopback_client(monkeypatch, tmp_path):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(filesystem_api, "_is_loopback", lambda _host: False)

    with TestClient(create_app()) as client:
        response = client.get("/api/filesystem/roots")

    assert response.status_code == 403


def test_filesystem_rejects_empty_path(monkeypatch, tmp_path):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path / "data"))
    with TestClient(create_app()) as client:
        response = client.get("/api/filesystem/entries", params={"path": ""})
    assert response.status_code == 422


def test_filesystem_maps_permission_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path / "data"))

    def denied(_path: Path):
        raise PermissionError("access denied")

    monkeypatch.setattr(filesystem_api, "_list_directory", denied)
    with TestClient(create_app()) as client:
        response = client.get(
            "/api/filesystem/entries", params={"path": str(tmp_path)}
        )

    assert response.status_code == 403
    assert str(tmp_path.resolve()) in response.json()["detail"]


def test_filesystem_maps_slow_directories_to_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path / "data"))

    async def slow_to_thread(*_args, **_kwargs):
        await asyncio.sleep(0.02)
        return {}

    monkeypatch.setattr(filesystem_api.asyncio, "to_thread", slow_to_thread)
    monkeypatch.setattr(filesystem_api, "_LIST_TIMEOUT_SECONDS", 0.001)
    with TestClient(create_app()) as client:
        response = client.get(
            "/api/filesystem/entries", params={"path": str(tmp_path)}
        )

    assert response.status_code == 504
