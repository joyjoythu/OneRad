import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.api.deps import get_project_store
from app.projects import ProjectStore


@pytest.fixture
def temp_db():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.db"
    store = ProjectStore(str(db_path))
    yield store, Path(tmp)
    shutil.rmtree(tmp)


@pytest.fixture
def client(temp_db):
    store, _root = temp_db
    app = create_app()

    def override_store():
        return store

    app.dependency_overrides[get_project_store] = override_store
    with TestClient(app) as test_client:
        yield test_client


def test_create_and_list_project(client, temp_db):
    _store, root = temp_db
    project_path = root / "new-project"
    response = client.post(
        "/api/projects/",
        json={"name": "new-project", "path": str(project_path), "description": "test"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "new-project"
    assert data["description"] == "test"

    response = client.get("/api/projects/")
    assert response.status_code == 200
    projects = response.json()
    assert len(projects) == 1
    assert projects[0]["name"] == "new-project"


def test_get_project(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    response = client.get(f"/api/projects/{project['id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == project["id"]
    assert data["name"] == "A"
    assert "analysis" in data

    response = client.get("/api/projects/non-existent-id")
    assert response.status_code == 404


def test_update_config(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    response = client.put(
        f"/api/projects/{project['id']}/config",
        json={
            "image_dir": "/data/images",
            "clinical_path": "/data/clinical.csv",
            "output_dir": "./out",
            "modality": "CT",
            "covariates": "age,gender",
            "model": "deepseek-v4-pro",
            "api_key": "secret",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["analysis"]["modality"] == "CT"
    assert data["analysis"]["covariates"] == "age,gender"


def test_delete_project(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    response = client.delete(f"/api/projects/{project['id']}")
    assert response.status_code == 204
    assert store.load_project(project["id"]) is None


def test_list_runs(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    run_id = store.record_run_start(project["id"], {"image_dir": "/img", "clinical_path": "/clin.csv"})
    store.record_run_end(run_id, "success", "完成", "/report.docx")

    response = client.get(f"/api/projects/{project['id']}/runs")
    assert response.status_code == 200
    runs = response.json()
    assert len(runs) == 1
    assert runs[0]["status"] == "success"
    assert runs[0]["report_path"] == "/report.docx"
