import pytest
import tempfile
import shutil
import time
from pathlib import Path

import yaml

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


def test_save_project_config_updates_yaml(temp_db):
    store, root = temp_db
    p = store.create_project("A", str(root / "a"), "")
    updated = store.save_project_config(p["id"], {
        "image_dir": "/data/images",
        "clinical_path": "/data/clinical.csv",
        "output_dir": "./out",
        "modality": "CT",
        "covariates": "age,gender",
        "model": "logistic",
        "analysis_model": "logistic",
    })
    assert updated["analysis"]["modality"] == "CT"
    yaml_path = Path(p["path"]) / "project.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["analysis"]["covariates"] == "age,gender"


def test_run_history(temp_db):
    store, root = temp_db
    p = store.create_project("A", str(root / "a"), "")
    run_id = store.record_run_start(p["id"], {"image_dir": "/img", "clinical_path": "/clin.csv"})
    store.record_run_end(run_id, "success", "完成", "/report.docx")
    runs = store.list_runs(p["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "success"
    assert runs[0]["report_path"] == "/report.docx"


def test_load_project_returns_default_analysis_for_missing_yaml(temp_db):
    store, root = temp_db
    p = store.create_project("A", str(root / "a"), "")
    (Path(p["path"]) / "project.yaml").unlink()
    loaded = store.load_project(p["id"])
    assert loaded["analysis"]["modality"] == "auto"


def test_record_and_list_threads(tmp_path):
    store = ProjectStore(db_path=str(tmp_path / "projects.db"))
    store.create_project(name="P1", path=str(tmp_path / "p1"))
    project = store.list_projects()[0]
    store.record_thread(project["id"], "t1", "First chat", "deepseek-v4-pro")
    store.record_thread(project["id"], "t2", "Second chat", "deepseek-v4-flash")
    threads = store.list_threads(project["id"])
    assert len(threads) == 2
    assert threads[0]["id"] == "t2"
    assert threads[1]["title"] == "First chat"


def test_delete_thread_removes_sse_events(tmp_path):
    store = ProjectStore(db_path=str(tmp_path / "projects.db"))
    store.create_project(name="P1", path=str(tmp_path / "p1"))
    project = store.list_projects()[0]
    store.record_thread(project["id"], "t1", "Chat", "deepseek-v4-pro")
    store.record_sse_event("agent", "t1", 1, "{}")
    store.delete_thread("t1")
    assert store.get_thread_meta("t1") is None
    assert store.list_sse_events("agent", "t1") == []


def test_thread_meta_update_and_timestamp(tmp_path):
    store = ProjectStore(db_path=str(tmp_path / "projects.db"))
    store.create_project(name="P1", path=str(tmp_path / "p1"))
    project = store.list_projects()[0]
    store.record_thread(project["id"], "t1", "Chat", "deepseek-v4-pro")
    store.record_thread(project["id"], "t2", "Another", "deepseek-v4-flash")

    meta = store.get_thread_meta("t1")
    assert meta is not None
    assert meta["title"] == "Chat"
    assert meta["llm_model"] == "deepseek-v4-pro"
    assert store.get_thread_meta("missing") is None

    old_updated_at = meta["updated_at"]
    store.update_thread_title("t1", "Renamed chat")
    updated = store.get_thread_meta("t1")
    assert updated["title"] == "Renamed chat"
    assert updated["updated_at"] > old_updated_at

    threads = store.list_threads(project["id"])
    assert [t["id"] for t in threads] == ["t1", "t2"]

    store.update_thread_timestamp("t2")
    threads = store.list_threads(project["id"])
    assert [t["id"] for t in threads] == ["t2", "t1"]


def test_delete_project_cleans_thread_sse_events(tmp_path):
    store = ProjectStore(db_path=str(tmp_path / "projects.db"))
    store.create_project(name="P1", path=str(tmp_path / "p1"))
    project = store.list_projects()[0]
    store.record_thread(project["id"], "t1", "Chat", "deepseek-v4-pro")
    store.record_sse_event("agent", "t1", 1, "{}")
    store.delete_project(project["id"])
    assert store.get_thread_meta("t1") is None
    assert store.list_sse_events("agent", "t1") == []


def test_load_project_degrades_when_config_read_stalls(temp_db, monkeypatch):
    """网络路径不可达导致配置读取阻塞时，超时降级为默认配置而不是卡死。"""
    import app.projects as projects_module

    store, _root = temp_db
    p = store.create_project("slow", str(_root / "slow"), "")
    # 项目目录里放一个有效 project.yaml：若读取成功就不会返回默认值，
    # 以此证明返回默认值确实是因为超时而非文件缺失。
    store.save_project_config(p["id"], {**store._default_analysis(), "modality": "ct"})

    def stall(_self, _path):
        time.sleep(30)
        return store._default_analysis()

    monkeypatch.setattr(projects_module.ProjectStore, "_read_analysis_file", stall)
    monkeypatch.setattr(projects_module, "_CONFIG_READ_TIMEOUT", 0.2)
    t0 = time.time()
    loaded = store.load_project(p["id"])
    elapsed = time.time() - t0
    assert loaded["analysis"] == store._default_analysis()
    assert elapsed < 5
