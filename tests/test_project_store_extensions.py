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


def test_record_sse_event_idempotent(store, project):
    store.record_sse_event("run", project["id"], 1, "hello")
    store.record_sse_event("run", project["id"], 1, "hello")

    events = store.list_sse_events("run", project["id"])

    assert len(events) == 1


def test_list_sse_events_after_event_id(store, project):
    for event_id, data in [(1, "a"), (2, "b"), (3, "c")]:
        store.record_sse_event("run", project["id"], event_id, data)

    events = store.list_sse_events("run", project["id"], after_event_id=1)

    assert len(events) == 2
    assert events[0]["event_id"] == 2
    assert events[1]["event_id"] == 3


def test_delete_sse_events(store, project):
    store.record_sse_event("run", project["id"], 1, "hello")
    store.record_sse_event("run", project["id"], 2, "world")
    store.delete_sse_events("run", project["id"])

    events = store.list_sse_events("run", project["id"])
    assert len(events) == 0


def test_delete_sse_events_only_affects_matching_scope(store, project):
    store.record_sse_event("run", project["id"], 1, "hello")
    store.record_sse_event("other", project["id"], 1, "world")
    store.delete_sse_events("run", project["id"])

    assert len(store.list_sse_events("run", project["id"])) == 0
    assert len(store.list_sse_events("other", project["id"])) == 1


def test_has_running_run(store, project):
    store.record_run_start(project["id"], {})

    assert store.has_running_run(project["id"]) is True


def test_no_running_run(store, project):
    run_id = store.record_run_start(project["id"], {})
    store.record_run_end(run_id, "completed")

    assert store.has_running_run(project["id"]) is False


def test_stale_running_run_is_not_running(store, project):
    from datetime import datetime, timedelta, timezone

    old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    store._now = lambda: old_time
    store.record_run_start(project["id"], {})
    del store._now

    assert store.has_running_run(project["id"]) is False

    runs = store.list_runs(project["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
