import json
import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.api.agent import get_agent_graph


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


def _create_project(client):
    response = client.post(
        "/api/projects",
        json={"name": "AgentTest", "path": "agent-test", "description": ""},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_thread(client, project_id, api_key="", llm_model="deepseek-v4-pro"):
    response = client.post(
        f"/api/agent/threads?project_id={project_id}",
        json={"api_key": api_key, "llm_model": llm_model},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_thread(client):
    project = _create_project(client)
    data = _create_thread(client, project['id'])
    assert "thread_id" in data


def test_get_thread(client):
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    response = client.get(f"/api/agent/threads/{thread_id}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["thread_id"] == thread_id
    assert data["interrupt_type"] is None
    assert data["messages"] == []
    assert data["operation_log"] == []


def test_send_message_publishes_events(client, app):
    """Mock the graph to verify message sending stores events for SSE replay."""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    async def fake_astream(input_value=None, config=None, stream_mode=None):
        yield {
            "messages": [],
            "interrupt_type": None,
            "operation_log": ["started"],
        }
        yield {
            "messages": [],
            "interrupt_type": None,
            "operation_log": ["started", "done"],
        }

    mock_graph = AsyncMock()
    mock_graph.astream = fake_astream
    app.dependency_overrides[get_agent_graph] = lambda: mock_graph

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "hello"},
    )
    assert response.status_code == 202, response.text

    # Wait for the background streaming task to publish events.
    time.sleep(0.5)

    events = app.state.event_bridge.store.list_sse_events("agent", thread_id)
    assert len(events) >= 1
    payload = json.loads(events[0]["data"])
    assert payload["interrupt_type"] is None
    assert payload["operation_log"] == ["started"]


@pytest.mark.anyio
async def test_sse_bridge_receives_agent_events(app, client):
    """Verify the EventBridge can replay agent-scoped events for the SSE feed."""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    bridge = app.state.event_bridge
    await bridge.publish("agent", thread_id, {"hello": "world"})

    queue = await bridge.subscribe("agent", thread_id, last_event_id=0)
    import asyncio

    item = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert item["data"] == {"hello": "world"}
