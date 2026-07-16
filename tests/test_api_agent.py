import asyncio
import json
import time
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.api import create_app
from app.api.agent import get_agent_graph, _unanswered_tool_call_ids


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
    suffix = uuid.uuid4().hex[:8]
    response = client.post(
        "/api/projects",
        json={"name": f"AgentTest-{suffix}", "path": f"agent-test-{suffix}", "description": ""},
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


def test_create_thread_rejects_invalid_llm_model(client):
    project = _create_project(client)
    response = client.post(
        f"/api/agent/threads?project_id={project['id']}",
        json={"api_key": "", "llm_model": "gpt-4"},
    )
    assert response.status_code == 422, response.text


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


def _list_threads(client, project_id):
    response = client.get(f"/api/agent/threads?project_id={project_id}")
    assert response.status_code == 200, response.text
    return response.json()["threads"]


def test_list_threads_by_project(client):
    project_a = _create_project(client)
    project_b = _create_project(client)
    t_a = _create_thread(client, project_a["id"])["thread_id"]
    t_b = _create_thread(client, project_b["id"])["thread_id"]

    threads_a = _list_threads(client, project_a["id"])
    threads_b = _list_threads(client, project_b["id"])

    assert len(threads_a) == 1
    assert threads_a[0]["id"] == t_a
    assert len(threads_b) == 1
    assert threads_b[0]["id"] == t_b


def test_delete_thread(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    response = client.delete(f"/api/agent/threads/{thread_id}")
    assert response.status_code == 204, response.text

    assert _list_threads(client, project["id"]) == []

    response = client.get(f"/api/agent/threads/{thread_id}")
    assert response.status_code == 404


def test_delete_thread_cleans_checkpoints(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    mock_adelete = AsyncMock()
    app.state.checkpointer.adelete_thread = mock_adelete

    response = client.delete(f"/api/agent/threads/{thread_id}")
    assert response.status_code == 204, response.text

    mock_adelete.assert_awaited_once_with(thread_id)
    assert _list_threads(client, project["id"]) == []


def test_rename_thread(client):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    response = client.patch(
        f"/api/agent/threads/{thread_id}", json={"title": "Renamed chat"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["thread"]["title"] == "Renamed chat"


def test_resume_thread(client):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    response = client.post(
        f"/api/agent/threads/{thread_id}/resume",
        json={"api_key": "key123", "llm_model": "deepseek-v4-flash"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["thread_id"] == thread_id
    assert data["messages"] == []


def test_thread_title_set_on_first_message(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    threads = _list_threads(client, project["id"])
    assert threads[0]["title"] == ""

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "hello world this is a test"},
    )
    assert response.status_code == 202, response.text

    threads = _list_threads(client, project["id"])
    assert threads[0]["title"] == "hello world this is a test"[:30]


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
    mock_graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(values={"interrupt_type": None})
    )
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
    assert payload["running"] is True


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


def test_send_message_conflict_while_streaming(client, app):
    """流式运行进行中发送新消息应返回 409，避免并发运行破坏消息历史。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    app.state.active_agent_streams.add(thread_id)
    try:
        response = client.post(
            f"/api/agent/threads/{thread_id}/messages",
            json={"role": "user", "content": "second message"},
        )
        assert response.status_code == 409, response.text
    finally:
        app.state.active_agent_streams.discard(thread_id)


def test_send_message_conflict_when_interrupt_pending(client, app):
    """线程停在待确认中断时发送新消息应返回 409，提示先确认或取消。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    mock_graph = AsyncMock()
    mock_graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(values={"interrupt_type": "file_plan"})
    )
    app.dependency_overrides[get_agent_graph] = lambda: mock_graph

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "hello during interrupt"},
    )
    assert response.status_code == 409, response.text
    mock_graph.astream.assert_not_called()


def test_confirm_conflict_while_streaming(client, app):
    """流式运行进行中发起确认应返回 409，防止同一线程上的并发运行。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    app.state.active_agent_streams.add(thread_id)
    try:
        response = client.post(f"/api/agent/threads/{thread_id}/confirm")
        assert response.status_code == 409, response.text
    finally:
        app.state.active_agent_streams.discard(thread_id)


def test_unanswered_tool_call_ids_all_answered():
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "list_directory", "args": {}}],
        ),
        ToolMessage(content="{}", tool_call_id="call_1"),
    ]
    assert _unanswered_tool_call_ids(messages) == []


def test_unanswered_tool_call_ids_partial():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"id": "call_1", "name": "a", "args": {}},
                {"id": "call_2", "name": "b", "args": {}},
            ],
        ),
        ToolMessage(content="{}", tool_call_id="call_1"),
    ]
    assert _unanswered_tool_call_ids(messages) == ["call_2"]


def test_unanswered_tool_call_ids_without_tool_calls():
    assert _unanswered_tool_call_ids([HumanMessage(content="hi")]) == []


def test_unanswered_tool_call_ids_empty_history():
    assert _unanswered_tool_call_ids([]) == []


def test_stream_task_registered_and_cleaned_up(client, app):
    """流式运行期间任务应登记在 agent_stream_tasks，结束后清理。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    async def fake_astream(input_value=None, config=None, stream_mode=None):
        yield {
            "messages": [],
            "interrupt_type": None,
            "operation_log": ["started"],
        }

    mock_graph = AsyncMock()
    mock_graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(values={"interrupt_type": None})
    )
    mock_graph.astream = fake_astream
    app.dependency_overrides[get_agent_graph] = lambda: mock_graph

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "hello"},
    )
    assert response.status_code == 202, response.text

    # 等待后台流式任务完成
    deadline = time.time() + 2
    while time.time() < deadline and thread_id in app.state.active_agent_streams:
        time.sleep(0.05)
    assert thread_id not in app.state.active_agent_streams
    assert thread_id not in app.state.agent_stream_tasks


def test_stop_conflict_when_not_running(client, app):
    """空闲线程上没有正在运行的任务，stop 应返回 409。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    response = client.post(f"/api/agent/threads/{thread_id}/stop")
    assert response.status_code == 409, response.text


def test_stop_requests_cooperative_cancel(client, app, monkeypatch):
    """stop 应先置位运行时上下文的取消事件，让耗时任务协作式退出。"""
    from app.agent import runtime

    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    snapshots = [
        SimpleNamespace(values={"interrupt_type": None}),  # send_message 前检查
        SimpleNamespace(values={"interrupt_type": None}),  # stop 存在性检查
        SimpleNamespace(values={"messages": []}),          # 取消后读取
    ]

    async def blocking_astream(input_value=None, config=None, stream_mode=None):
        yield {"messages": [], "interrupt_type": None, "operation_log": []}
        await asyncio.sleep(3600)

    mock_graph = AsyncMock()
    mock_graph.aget_state = AsyncMock(side_effect=snapshots)
    mock_graph.astream = blocking_astream
    app.dependency_overrides[get_agent_graph] = lambda: mock_graph

    cancelled_threads = []
    original = runtime.request_cancel
    monkeypatch.setattr(
        runtime,
        "request_cancel",
        lambda tid: cancelled_threads.append(tid) or original(tid),
    )

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "hi"},
    )
    assert response.status_code == 202, response.text

    deadline = time.time() + 2
    while time.time() < deadline and thread_id not in app.state.agent_stream_tasks:
        time.sleep(0.05)
    assert thread_id in app.state.agent_stream_tasks

    response = client.post(f"/api/agent/threads/{thread_id}/stop")
    assert response.status_code == 202, response.text
    assert cancelled_threads == [thread_id]


def test_stop_cancels_stream_and_repairs_history(client, app):
    """stop 应取消活动流，并为未应答的 tool_calls 补「已停止」ToolMessage。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    dangling_messages = [
        HumanMessage(content="hi"),
        AIMessage(
            content="",
            tool_calls=[{"id": "call_1", "name": "list_directory", "args": {}}],
        ),
    ]
    repaired_messages = dangling_messages + [
        ToolMessage(
            content=json.dumps(
                {"cancelled": True, "reason": "用户停止了操作"}, ensure_ascii=False
            ),
            tool_call_id="call_1",
        )
    ]
    snapshots = [
        # ① send_message 发送前检查
        SimpleNamespace(values={"interrupt_type": None}),
        # ② stop 存在性检查
        SimpleNamespace(values={"interrupt_type": None}),
        # ③ 取消后读取：末条为未应答 tool_calls
        SimpleNamespace(values={"messages": dangling_messages}),
        # ④ 修复后读取：用于发布最终状态
        SimpleNamespace(
            values={
                "messages": repaired_messages,
                "operation_log": ["用户停止了当前任务"],
            }
        ),
    ]

    async def blocking_astream(input_value=None, config=None, stream_mode=None):
        yield {
            "messages": [],
            "interrupt_type": None,
            "operation_log": ["started"],
        }
        await asyncio.sleep(3600)

    mock_graph = AsyncMock()
    mock_graph.aget_state = AsyncMock(side_effect=snapshots)
    mock_graph.astream = blocking_astream
    app.dependency_overrides[get_agent_graph] = lambda: mock_graph

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "hi"},
    )
    assert response.status_code == 202, response.text

    deadline = time.time() + 2
    while time.time() < deadline and thread_id not in app.state.agent_stream_tasks:
        time.sleep(0.05)
    assert thread_id in app.state.agent_stream_tasks

    response = client.post(f"/api/agent/threads/{thread_id}/stop")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "stopped"

    # 历史修复：补了一条 cancelled ToolMessage，并记录操作日志
    mock_graph.aupdate_state.assert_awaited_once()
    updates = mock_graph.aupdate_state.await_args.args[1]
    assert len(updates["messages"]) == 1
    tool_msg = updates["messages"][0]
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.tool_call_id == "call_1"
    assert json.loads(tool_msg.content)["cancelled"] is True
    assert updates["operation_log"] == ["用户停止了当前任务"]

    # 任务收尾：线程离开 active 集合，映射清理
    assert thread_id not in app.state.active_agent_streams
    assert thread_id not in app.state.agent_stream_tasks

    # 最终状态已通过 SSE 桥发布
    events = app.state.event_bridge.store.list_sse_events("agent", thread_id)
    last_payload = json.loads(events[-1]["data"])
    assert last_payload["operation_log"] == ["用户停止了当前任务"]
    assert last_payload["messages"][-1]["role"] == "tool"
    assert last_payload["running"] is False


def test_get_thread_reports_running(client, app):
    """get_thread 应报告线程是否有正在运行的流式任务。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    response = client.get(f"/api/agent/threads/{thread_id}")
    assert response.status_code == 200, response.text
    assert response.json()["running"] is False

    app.state.active_agent_streams.add(thread_id)
    try:
        response = client.get(f"/api/agent/threads/{thread_id}")
        assert response.json()["running"] is True
    finally:
        app.state.active_agent_streams.discard(thread_id)


def test_sync_payload_includes_radiomics_pending():
    """_sync_payload 必须返回影像组学待确认字段，否则前端无法渲染确认面板。"""
    from app.api.agent import _sync_payload

    values = {
        "messages": [],
        "interrupt_type": "radiomics_execution",
        "operation_log": [],
        "pending_radiomics_plan": None,
        "pending_radiomics_execution": {
            "tool_call_id": "tc1",
            "pairs": [{"patient_id": "p1", "image_path": "images/p1.nii.gz", "mask_path": "masks/p1.nii.gz"}],
            "n_cases": 1,
            "yaml_path": "Params_labels.yaml",
            "output_dir": "radiomics_features",
        },
    }

    payload = _sync_payload(values, running=False)

    assert payload["interrupt_type"] == "radiomics_execution"
    assert payload["pending_radiomics_plan"] is None
    assert payload["pending_radiomics_execution"]["n_cases"] == 1


def test_sync_payload_includes_pending_radiomics_analysis():
    """_sync_payload 必须返回影像组学分析待确认字段。"""
    from app.api.agent import _sync_payload

    values = {
        "messages": [],
        "interrupt_type": "radiomics_analysis",
        "operation_log": [],
        "pending_radiomics_analysis": {
            "tool_call_id": "tc_analysis_1",
            "feature_csv": "features.csv",
            "clinical_csv": "clinical.csv",
            "target_column": "label",
        },
    }

    payload = _sync_payload(values, running=False)

    assert payload["interrupt_type"] == "radiomics_analysis"
    assert payload["pending_radiomics_analysis"]["tool_call_id"] == "tc_analysis_1"
    assert payload["pending_radiomics_analysis"]["target_column"] == "label"

    payload_missing = _sync_payload({}, running=False)
    assert payload_missing["pending_radiomics_analysis"] is None


def test_sync_payload_includes_context_usage():
    """_sync_payload 必须返回上下文用量与窗口大小，供前端渲染用量指示。"""
    from app.api.agent import _sync_payload

    values = {
        "messages": [],
        "model": "deepseek-v4-pro",
        "context_usage": {"input_tokens": 1234, "output_tokens": 56, "total_tokens": 1290},
    }

    payload = _sync_payload(values, running=False)

    assert payload["context_usage"]["input_tokens"] == 1234
    assert payload["context_window"] == 1_000_000


def test_sync_payload_context_usage_defaults():
    """无用量数据时返回 None；未知模型窗口默认 1M。"""
    from app.api.agent import _sync_payload

    payload = _sync_payload({}, running=False)
    assert payload["context_usage"] is None
    assert payload["context_window"] == 1_000_000

    payload_unknown = _sync_payload({"model": "some-other-model"}, running=False)
    assert payload_unknown["context_usage"] is None
    assert payload_unknown["context_window"] == 1_000_000
