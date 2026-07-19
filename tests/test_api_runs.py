import asyncio
import shutil
import tempfile
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.api.deps import get_project_store
from app.projects import ProjectStore


def _rmtree_with_retry(path, attempts=20, delay=0.5):
    """Windows 上被遗弃的后台线程可能仍短暂占用 sqlite 文件句柄，重试等待其释放。"""
    for _ in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            time.sleep(delay)
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def temp_db():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.db"
    store = ProjectStore(str(db_path))
    yield store, Path(tmp)
    _rmtree_with_retry(tmp)


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


def _run_config():
    return {
        "image_dir": "",
        "clinical_path": "",
        "output_dir": "./outputs",
        "modality": "auto",
        "covariates": "",
        "model": "logistic",
        "analysis_model": "logistic",
        "api_key": "",
    }


def test_start_run_idempotency(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    url = f"/api/projects/{project['id']}/runs"

    first = client.post(url, json=_run_config())
    assert first.status_code == 202
    assert "run_id" in first.json()

    second = client.post(url, json=_run_config())
    assert second.status_code == 409


def test_get_run_returns_record(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    start = client.post(f"/api/projects/{project['id']}/runs", json=_run_config())
    run_id = start.json()["run_id"]

    response = client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == run_id
    assert data["project_id"] == project["id"]
    assert "llm_model" not in data

    response = client.get("/api/runs/non-existent-id")
    assert response.status_code == 404


def test_get_run_events_sse(client, temp_db, monkeypatch):
    store, root = temp_db
    project = store.create_project("B", str(root / "b"), "")

    def fake_pipeline(project_id, run_id, config, bridge, store_arg, loop):
        for i in range(3):
            asyncio.run_coroutine_threadsafe(
                bridge.publish("run", run_id, {"type": "test", "index": i}),
                loop,
            ).result(timeout=5)
        store_arg.record_run_end(run_id, "completed", "fake", "")

    monkeypatch.setattr("app.api.runner.run_pipeline", fake_pipeline)

    start = client.post(f"/api/projects/{project['id']}/runs", json=_run_config())
    assert start.status_code == 202
    run_id = start.json()["run_id"]

    # Give the background task a moment to publish events.
    time.sleep(0.2)

    with client.stream("GET", f"/api/runs/{run_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        lines = []
        for line in response.iter_lines():
            lines.append(line)
            if len(lines) >= 12:  # 3 events * 4 lines each
                break

        assert any(line.startswith("data:") for line in lines)
        assert any("pipeline" in line for line in lines)


def test_run_pipeline_preserves_cancelled_status(client, temp_db, monkeypatch):
    store, root = temp_db
    project = store.create_project("Cancel", str(root / "cancel"), "")
    project_id = project["id"]

    def pipeline_that_finishes_after_cancel(
        p_id, run_id, config, bridge, store_arg, loop
    ):
        # Simulate cancellation being recorded first (e.g. by task.cancel()).
        store_arg.record_run_end(run_id, "cancelled", "用户取消", "")
        # Then the worker attempts to record its normal completion.
        # run_pipeline should detect the cancelled status and preserve it.

    monkeypatch.setattr("app.api.runner.run_pipeline", pipeline_that_finishes_after_cancel)

    start = client.post(f"/api/projects/{project_id}/runs", json=_run_config())
    assert start.status_code == 202
    run_id = start.json()["run_id"]

    # Wait for the worker thread to finish.
    time.sleep(0.5)

    run = store.get_run(run_id)
    assert run is not None
    assert run["status"] == "cancelled"
    assert run["log_summary"] == "用户取消"


def test_cancel_missing_run_returns_404(client):
    response = client.post("/api/runs/non-existent-id/cancel")
    assert response.status_code == 404


def test_cancel_completed_run_returns_409(client, temp_db, monkeypatch):
    store, root = temp_db
    project = store.create_project("Done", str(root / "done"), "")

    def fast_pipeline(project_id, run_id, config, bridge, store_arg, loop):
        store_arg.record_run_end(run_id, "completed", "", "")

    monkeypatch.setattr("app.api.runner.run_pipeline", fast_pipeline)

    start = client.post(f"/api/projects/{project['id']}/runs", json=_run_config())
    run_id = start.json()["run_id"]
    time.sleep(0.2)

    response = client.post(f"/api/runs/{run_id}/cancel")
    assert response.status_code == 409


def test_cancel_running_run_returns_202(client, temp_db, monkeypatch):
    store, root = temp_db
    project = store.create_project("Running", str(root / "running"), "")

    stop_event = threading.Event()

    def slow_pipeline(project_id, run_id, config, bridge, store_arg, loop):
        stop_event.wait(timeout=10)

    monkeypatch.setattr("app.api.runner.run_pipeline", slow_pipeline)

    start = client.post(f"/api/projects/{project['id']}/runs", json=_run_config())
    assert start.status_code == 202
    run_id = start.json()["run_id"]

    response = client.post(f"/api/runs/{run_id}/cancel")
    assert response.status_code == 202
    assert response.json()["run_id"] == run_id
    assert response.json()["status"] == "cancelling"

    stop_event.set()
