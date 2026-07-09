import pytest

from app.projects import ProjectStore


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "projects.db"
    return ProjectStore(str(db_path))


@pytest.fixture
def project(store, tmp_path):
    project_path = tmp_path / "project"
    return store.create_project("test-project", str(project_path))


def test_record_sse_event_and_list(store, project):
    store.record_sse_event("run", project["id"], 1, "hello")
    store.record_sse_event("run", project["id"], 2, "world")

    events = store.list_sse_events("run", project["id"])

    assert len(events) == 2
    assert events[0]["event_id"] == 1
    assert events[0]["data"] == "hello"
    assert events[1]["event_id"] == 2
    assert events[1]["data"] == "world"
    assert events[0]["scope"] == "run"
    assert events[0]["scope_id"] == project["id"]
    assert "created_at" in events[0]


def test_list_sse_events_after_event_id(store, project):
    for event_id, data in [(1, "a"), (2, "b"), (3, "c")]:
        store.record_sse_event("run", project["id"], event_id, data)

    events = store.list_sse_events("run", project["id"], after_event_id=1)

    assert len(events) == 2
    assert events[0]["event_id"] == 2
    assert events[1]["event_id"] == 3


def test_has_running_run(store, project):
    store.record_run_start(project["id"], {})

    assert store.has_running_run(project["id"]) is True


def test_no_running_run(store, project):
    run_id = store.record_run_start(project["id"], {})
    store.record_run_end(run_id, "completed")

    assert store.has_running_run(project["id"]) is False
