import pytest
from fastapi.testclient import TestClient

from app.api import create_app


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("ONERAD_DATA_DIR", str(tmp_path))
    _app = create_app()
    yield _app
    _app.dependency_overrides.clear()


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def folder_tree(tmp_path):
    """构造目录树：root/{alpha,beta/gamma,.hidden} 和一个文件。"""
    root = tmp_path / "root"
    (root / "alpha").mkdir(parents=True)
    (root / "beta" / "gamma").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "file.txt").write_text("x")
    return root


def test_list_directory_returns_subdirs_only(client, folder_tree):
    response = client.get("/api/fs/list", params={"path": str(folder_tree)})
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["path"] == str(folder_tree.resolve())
    names = [d["name"] for d in data["dirs"]]
    # 只含非隐藏子目录：文件和 .hidden 都被过滤
    assert names == ["alpha", "beta"]
    assert data["parent"] == str(folder_tree.parent)
    assert isinstance(data["drives"], list)


def test_list_directory_navigates_into_subdir(client, folder_tree):
    beta = folder_tree / "beta"
    response = client.get("/api/fs/list", params={"path": str(beta)})
    assert response.status_code == 200, response.text
    data = response.json()

    assert [d["name"] for d in data["dirs"]] == ["gamma"]
    assert data["parent"] == str(folder_tree.resolve())


def test_list_directory_defaults_to_home(client):
    response = client.get("/api/fs/list")
    assert response.status_code == 200, response.text
    assert response.json()["path"]


def test_list_directory_rejects_relative_path(client):
    response = client.get("/api/fs/list", params={"path": "some/relative"})
    assert response.status_code == 400


def test_list_directory_rejects_missing_path(client, tmp_path):
    response = client.get("/api/fs/list", params={"path": str(tmp_path / "nope")})
    assert response.status_code == 404


def test_list_directory_rejects_file(client, folder_tree):
    response = client.get(
        "/api/fs/list", params={"path": str(folder_tree / "file.txt")}
    )
    assert response.status_code == 400
