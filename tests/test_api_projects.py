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
def client(temp_db, monkeypatch):
    store, root = temp_db
    app = create_app()

    def override_store():
        return store

    app.dependency_overrides[get_project_store] = override_store

    # 相对项目路径必须落在临时数据目录下：通过环境变量切换数据目录
    # （app.api.projects 每次调用现读该变量，monkeypatch 因此生效）。
    monkeypatch.setenv("ONERAD_DATA_DIR", str(root))

    with TestClient(app) as test_client:
        yield test_client


def test_create_and_list_project(client, temp_db):
    _store, root = temp_db
    project_path = root / "new-project"
    response = client.post(
        "/api/projects",
        json={"name": "new-project", "path": str(project_path), "description": "test"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "new-project"
    assert data["description"] == "test"

    response = client.get("/api/projects")
    assert response.status_code == 200
    projects = response.json()
    assert len(projects) == 1
    assert projects[0]["name"] == "new-project"


def test_list_projects_includes_analysis_config(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    store.save_project_config(
        project["id"],
        {
            "image_dir": "/data/images",
            "clinical_path": "/data/clinical.csv",
            "output_dir": "./out",
            "modality": "CT",
            "covariates": "age,gender",
            "model": "random_forest",
            "analysis_model": "random_forest",
        },
    )

    response = client.get("/api/projects")
    assert response.status_code == 200
    projects = response.json()
    assert len(projects) == 1
    assert "analysis" in projects[0]
    assert projects[0]["analysis"]["modality"] == "CT"
    assert projects[0]["analysis"]["covariates"] == "age,gender"
    assert projects[0]["analysis"]["analysis_model"] == "random_forest"


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
            "model": "logistic",
            "analysis_model": "logistic",
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


def test_delete_missing_project_returns_404(client, temp_db):
    response = client.delete("/api/projects/non-existent-id")
    assert response.status_code == 404


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


def test_create_project_rejects_path_traversal(client, temp_db):
    response = client.post(
        "/api/projects",
        json={"name": "evil", "path": "../evil", "description": "test"},
    )
    assert response.status_code == 400
    assert "Invalid project path" in response.json()["detail"]


def test_create_project_accepts_absolute_path(client, temp_db):
    _store, root = temp_db
    # Use a directory outside ONERAD_DATA_DIR to prove absolute paths are accepted.
    absolute_path = root.parent / "abs-project"
    response = client.post(
        "/api/projects",
        json={"name": "abs-project", "path": str(absolute_path), "description": "test"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "abs-project"
    assert Path(data["path"]).resolve() == absolute_path.resolve()


def test_create_project_rejects_duplicate_name(client, temp_db):
    _store, root = temp_db
    project_path = root / "dup-project"
    response = client.post(
        "/api/projects",
        json={"name": "dup-project", "path": str(project_path), "description": "first"},
    )
    assert response.status_code == 201

    response = client.post(
        "/api/projects",
        json={
            "name": "dup-project",
            "path": str(root / "dup-project-2"),
            "description": "second",
        },
    )
    assert response.status_code == 400


def test_get_missing_project_returns_404(client, temp_db):
    response = client.get("/api/projects/non-existent-id")
    assert response.status_code == 404


def test_update_config_rejects_project_scoped_api_key(client, temp_db):
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
            "model": "logistic",
            "analysis_model": "logistic",
            "api_key": "super-secret",
        },
    )
    assert response.status_code == 422


def test_update_config_unifies_model_and_analysis_model(client, temp_db):
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
            "model": "logistic",
            "analysis_model": "random_forest",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["analysis"]["analysis_model"] == "random_forest"
    assert data["analysis"]["model"] == "random_forest"

    # Verify fallback to `model` when `analysis_model` is empty.
    response = client.put(
        f"/api/projects/{project['id']}/config",
        json={
            "image_dir": "/data/images",
            "clinical_path": "/data/clinical.csv",
            "output_dir": "./out",
            "modality": "CT",
            "covariates": "age,gender",
            "model": "xgboost",
            "analysis_model": "",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["analysis"]["analysis_model"] == "xgboost"
    assert data["analysis"]["model"] == "xgboost"


def test_relative_project_path_resolves_against_env_data_dir(client, temp_db):
    """相对项目路径必须基于（可被 monkeypatch 的）环境变量数据目录解析，
    而不是 import 时固化的真实 ~/.onerad——否则测试会在真实数据目录建目录。"""
    _store, root = temp_db
    response = client.post(
        "/api/projects",
        json={"name": "rel-path", "path": "rel-check", "description": ""},
    )
    assert response.status_code == 201, response.text
    resolved = Path(response.json()["path"])
    assert root in resolved.parents
    assert (root / "rel-check").is_dir()


def test_rename_project(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    response = client.patch(f"/api/projects/{project['id']}", json={"name": "B"})
    assert response.status_code == 200
    assert response.json()["name"] == "B"

    response = client.get(f"/api/projects/{project['id']}")
    assert response.json()["name"] == "B"


def test_rename_project_not_found(client):
    response = client.patch("/api/projects/non-existent-id", json={"name": "B"})
    assert response.status_code == 404


def test_rename_project_empty_name(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    response = client.patch(f"/api/projects/{project['id']}", json={"name": "   "})
    assert response.status_code == 400


def test_rename_project_duplicate_name(client, temp_db):
    store, root = temp_db
    store.create_project("A", str(root / "a"), "")
    p2 = store.create_project("B", str(root / "b"), "")
    response = client.patch(f"/api/projects/{p2['id']}", json={"name": "A"})
    assert response.status_code == 400


def test_list_project_files_returns_relative_paths(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    proj_root = Path(project["path"])
    (proj_root / "data").mkdir()
    (proj_root / "data" / "image.nii.gz").write_text("x")
    (proj_root / "notes.txt").write_text("x")

    response = client.get(f"/api/projects/{project['id']}/files")
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert "data/" in entries  # 目录以 / 结尾
    assert "data/image.nii.gz" in entries
    assert "notes.txt" in entries
    # 相对路径必须使用 POSIX 分隔符（Windows 下也不能出现反斜杠）
    assert all("\\" not in e for e in entries)


def test_list_project_files_includes_nested_dirs(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    proj_root = Path(project["path"])
    (proj_root / "data" / "raw").mkdir(parents=True)
    (proj_root / "data" / "raw" / "img.nii.gz").write_text("x")

    response = client.get(f"/api/projects/{project['id']}/files")
    entries = response.json()["entries"]
    assert "data/" in entries
    assert "data/raw/" in entries
    assert "data/raw/img.nii.gz" in entries


def test_list_project_files_excludes_noise_dirs(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    proj_root = Path(project["path"])
    for noise in (".git", "__pycache__", "node_modules", ".venv"):
        (proj_root / noise).mkdir()
        (proj_root / noise / "junk.py").write_text("x")
    (proj_root / "real.py").write_text("x")

    response = client.get(f"/api/projects/{project['id']}/files")
    entries = response.json()["entries"]
    assert "real.py" in entries
    # 噪音目录既不列出也不递归进入
    assert not any(
        e.startswith((".git", "__pycache__", "node_modules", ".venv")) for e in entries
    )


def test_list_project_files_query_filter(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    proj_root = Path(project["path"])
    (proj_root / "data").mkdir()
    (proj_root / "data" / "image.nii.gz").write_text("x")
    (proj_root / "notes.txt").write_text("x")

    response = client.get(f"/api/projects/{project['id']}/files", params={"q": "IMAGE"})
    entries = response.json()["entries"]
    assert entries == ["data/image.nii.gz"]

    # 目录名同样参与过滤
    response = client.get(f"/api/projects/{project['id']}/files", params={"q": "dat"})
    entries = response.json()["entries"]
    assert "data/" in entries
    assert "data/image.nii.gz" in entries
    assert "notes.txt" not in entries


def test_list_project_files_limit(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    proj_root = Path(project["path"])
    for i in range(10):
        (proj_root / f"f{i:02d}.txt").write_text("x")

    response = client.get(f"/api/projects/{project['id']}/files", params={"limit": 3})
    entries = response.json()["entries"]
    assert len(entries) == 3
    assert entries == sorted(entries)


def test_list_project_files_missing_dir_returns_empty(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    shutil.rmtree(project["path"])

    response = client.get(f"/api/projects/{project['id']}/files")
    assert response.status_code == 200
    assert response.json()["entries"] == []


def test_list_project_files_not_found(client):
    response = client.get("/api/projects/non-existent-id/files")
    assert response.status_code == 404
