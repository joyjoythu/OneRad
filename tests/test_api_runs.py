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


@pytest.fixture
def temp_db():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.db"
    store = ProjectStore(str(db_path))
    yield store, Path(tmp)
    shutil.rmtree(tmp)


@pytest.fixture
def client(temp_db):
    store, root = temp_db
    app = create_app()

    def override_store():
        return store

    app.dependency_overrides[get_project_store] = override_store

    import app.api.projects as projects_module

    original_data_dir = projects_module.ONERAD_DATA_DIR
    projects_module.ONERAD_DATA_DIR = root
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        projects_module.ONERAD_DATA_DIR = original_data_dir


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
    if "llm_model" in data:
        assert data["llm_model"] == "deepseek-v4-pro"

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


def test_cancel_run_records_cancelled_status(client, temp_db, monkeypatch):
    store, root = temp_db
    project = store.create_project("Cancel", str(root / "cancel"), "")

    def slow_pipeline(project_id, run_id, config, bridge, store_arg, loop):
        time.sleep(1)

    monkeypatch.setattr("app.api.runner.run_pipeline", slow_pipeline)

    start = client.post(f"/api/projects/{project['id']}/runs", json=_run_config())
    assert start.status_code == 202
    run_id = start.json()["run_id"]

    # Stream events in a background thread so we can capture the cancelled event.
    event_lines = []

    def collect_events():
        with client.stream("GET", f"/api/runs/{run_id}/events") as response:
            for line in response.iter_lines():
                event_lines.append(line)
                if "pipeline_cancelled" in line:
                    break

    event_thread = threading.Thread(target=collect_events, daemon=True)
    event_thread.start()
    time.sleep(0.2)  # Let the SSE subscription start.

    task = client.app.state.pipeline_task_map.get(run_id)
    assert task is not None
    task.cancel()

    deadline = time.time() + 2
    run = None
    while time.time() < deadline:
        run = store.get_run(run_id)
        if run["status"] == "cancelled":
            break
        time.sleep(0.1)

    event_thread.join(timeout=2)

    assert run is not None
    assert run["status"] == "cancelled"
    assert any("pipeline_cancelled" in line for line in event_lines)
