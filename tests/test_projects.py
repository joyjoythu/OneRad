import pytest
import tempfile
import shutil
from pathlib import Path

from app.projects import ProjectStore


@pytest.fixture
def temp_db():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.db"
    store = ProjectStore(str(db_path))
    yield store, Path(tmp)
    shutil.rmtree(tmp)


def test_create_project_writes_files_and_record(temp_db):
    store, root = temp_db
    project_path = root / "ZHY-ESWA"
    project = store.create_project("ZHY-ESWA", str(project_path), "测试项目")
    assert project["name"] == "ZHY-ESWA"
    assert Path(project["path"]).exists()
    assert (Path(project["path"]) / "project.yaml").exists()
    assert (Path(project["path"]) / "Params_labels.yaml").exists()
    projects = store.list_projects()
    assert len(projects) == 1


def test_list_projects_sorted_by_updated_at(temp_db):
    store, root = temp_db
    p1 = store.create_project("A", str(root / "a"), "")
    p2 = store.create_project("B", str(root / "b"), "")
    projects = store.list_projects()
    assert projects[0]["id"] == p2["id"]
    assert projects[1]["id"] == p1["id"]


def test_delete_project_keeps_directory(temp_db):
    store, root = temp_db
    p = store.create_project("A", str(root / "a"), "")
    store.delete_project(p["id"])
    assert store.load_project(p["id"]) is None
    assert (root / "a").exists()


def test_duplicate_name_raises(temp_db):
    store, root = temp_db
    store.create_project("A", str(root / "a"), "")
    with pytest.raises(ValueError):
        store.create_project("A", str(root / "b"), "")
