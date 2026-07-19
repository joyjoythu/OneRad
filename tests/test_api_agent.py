import asyncio
import json
import time
import uuid
from contextlib import suppress
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app.api import create_app
from app.agent import build_initial_state, create_agent_graph
from app.api.agent import (
    get_agent_graph,
    _unanswered_tool_call_ids,
    _agent_config,
    _make_message,
    _render_messages,
    _ensure_message_timestamps,
    _stream_agent,
)
from app.constants import DEEPSEEK_MODEL


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


def _create_thread(client, project_id, api_key="test-key", auto_approve=False):
    settings_response = client.put("/api/settings", json={"api_key": api_key})
    assert settings_response.status_code == 200, settings_response.text
    response = client.post(
        f"/api/agent/threads?project_id={project_id}",
        json={"auto_approve": auto_approve},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_thread(client, app):
    project = _create_project(client)
    data = _create_thread(client, project['id'])
    assert "thread_id" in data
    meta = app.state.project_store.get_thread_meta(data["thread_id"])
    assert meta["llm_model"] == DEEPSEEK_MODEL

    snapshot = asyncio.run(
        app.state.agent_graph.aget_state(
            asyncio.run(_agent_config(data["thread_id"], app))
        )
    )
    assert "api_key" not in snapshot.values


def test_create_thread_requires_general_api_key(client):
    project = _create_project(client)
    response = client.post(
        f"/api/agent/threads?project_id={project['id']}",
        json={},
    )
    assert response.status_code == 400
    assert "DeepSeek API 密钥" in response.json()["detail"]


def test_create_thread_rejects_llm_model_parameter(client):
    project = _create_project(client)
    response = client.post(
        f"/api/agent/threads?project_id={project['id']}",
        json={"llm_model": "gpt-4"},
    )
    assert response.status_code == 422, response.text


def test_create_thread_rejects_legacy_api_key_parameter(client):
    project = _create_project(client)
    response = client.post(
        f"/api/agent/threads?project_id={project['id']}",
        json={"api_key": "legacy-key"},
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
    assert "llm_model" not in threads_a[0]
    assert len(threads_b) == 1
    assert threads_b[0]["id"] == t_b


def test_list_threads_marks_running(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    threads = _list_threads(client, project["id"])
    assert threads[0]["running"] is False

    app.state.active_agent_streams.add(thread_id)
    try:
        threads = _list_threads(client, project["id"])
        assert threads[0]["running"] is True
    finally:
        app.state.active_agent_streams.discard(thread_id)


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
    assert "llm_model" not in response.json()["thread"]


def test_resume_thread(client):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    response = client.post(
        f"/api/agent/threads/{thread_id}/resume",
        json={},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["thread_id"] == thread_id
    assert data["messages"] == []


def test_resume_thread_rejects_llm_model_parameter(client):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    response = client.post(
        f"/api/agent/threads/{thread_id}/resume",
        json={"llm_model": "deepseek-v4-pro"},
    )
    assert response.status_code == 422, response.text


def test_resume_thread_rejects_legacy_api_key_parameter(client):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]
    response = client.post(
        f"/api/agent/threads/{thread_id}/resume",
        json={"api_key": "legacy-key"},
    )
    assert response.status_code == 422, response.text


def test_thread_title_set_on_first_message(client, app, monkeypatch):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    class FailingLLM:
        def __init__(self, api_key=None, base_url=None, model=None):
            pass

        def call(self, system, user, temperature=0.1, max_tokens=1500):
            raise RuntimeError("offline")

    monkeypatch.setattr("app.api.agent.LLMClient", FailingLLM)

    threads = _list_threads(client, project["id"])
    assert threads[0]["title"] == ""

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "hello world this is a test"},
    )
    assert response.status_code == 202, response.text

    _wait_for_title_tasks(app)
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


def _publish_two_run_events(client, app, thread_id):
    """通过 mock graph 让后台流式任务发布两个 SSE 事件（operation_log 递增）。"""
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
    # 等待后台任务发布完事件并退出。
    time.sleep(0.5)


def test_events_stream_defaults_to_live_only(client, app):
    """新订阅默认不回放历史快照：当前完整状态已由 resume/get 接口返回，
    全量回放会让前端把过期中间状态逐个重放（长历史时界面从头滚动加载）。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]
    _publish_two_run_events(client, app, thread_id)

    with client.stream("GET", f"/api/agent/threads/{thread_id}/events") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: agent\n" not in body
    assert "event: agent_end" in body


def test_events_stream_replays_with_explicit_last_event_id(client, app):
    """显式传 last_event_id 时仍回放其后的历史事件（断线续传场景）。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]
    _publish_two_run_events(client, app, thread_id)

    with client.stream(
        "GET", f"/api/agent/threads/{thread_id}/events?last_event_id=1"
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert body.count("event: agent\n") == 1
    assert '"done"' in body


def test_events_stream_replays_with_last_event_id_header(client, app):
    """EventSource 自动重连通过 Last-Event-ID 头续传历史事件。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]
    _publish_two_run_events(client, app, thread_id)

    with client.stream(
        "GET",
        f"/api/agent/threads/{thread_id}/events",
        headers={"Last-Event-ID": "1"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert body.count("event: agent\n") == 1
    assert '"done"' in body


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


def test_other_resumes_with_instruction(client, app):
    """other 动作以 action=other + 用户指令恢复挂起的 interrupt。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    captured = {}

    async def fake_astream(input_value=None, config=None, stream_mode=None):
        captured["input"] = input_value
        yield {
            "messages": [],
            "interrupt_type": None,
            "operation_log": ["done"],
        }

    mock_graph = AsyncMock()
    mock_graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(values={"interrupt_type": "file_plan"})
    )
    mock_graph.astream = fake_astream
    app.dependency_overrides[get_agent_graph] = lambda: mock_graph

    response = client.post(
        f"/api/agent/threads/{thread_id}/other",
        json={"instruction": "  改成只处理 T1 序列  "},
    )
    assert response.status_code == 202, response.text

    # 等待后台流式任务消费恢复指令。
    time.sleep(0.5)
    resume = captured["input"].resume
    assert resume["action"] == "other"
    assert resume["instruction"] == "改成只处理 T1 序列"


def test_other_conflict_without_pending_interrupt(client, app):
    """无挂起 interrupt 时 other 应返回 409。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    response = client.post(
        f"/api/agent/threads/{thread_id}/other",
        json={"instruction": "换个思路"},
    )
    assert response.status_code == 409, response.text


@pytest.mark.parametrize("instruction", ["", "   \n\t  "])
def test_other_rejects_blank_instruction(client, app, instruction):
    """空或纯空白 instruction 应返回 400。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    response = client.post(
        f"/api/agent/threads/{thread_id}/other",
        json={"instruction": instruction},
    )
    assert response.status_code == 400, response.text


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
        SimpleNamespace(values={"messages": []}),          # 流式 finally 补打时间戳读取
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

    # 等首个流式事件落库后再 stop：取消瞬间 publish 的线程池写入可能被弃置，
    # 晚于 stop 的最终事件完成会造成事件乱序（既有竞态）
    deadline = time.time() + 2
    while (
        time.time() < deadline
        and not app.state.event_bridge.store.list_sse_events("agent", thread_id)
    ):
        time.sleep(0.05)
    assert app.state.event_bridge.store.list_sse_events("agent", thread_id)

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
        # ③ 流式 finally 补打时间戳读取
        SimpleNamespace(values={"messages": dangling_messages}),
        # ④ 取消后读取：末条为未应答 tool_calls
        SimpleNamespace(values={"messages": dangling_messages}),
        # ⑤ 修复后补打时间戳读取
        SimpleNamespace(values={"messages": repaired_messages}),
        # ⑥ 修复后读取：用于发布最终状态
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

    # 等首个流式事件落库后再 stop：取消瞬间 publish 的线程池写入可能被弃置，
    # 晚于 stop 的最终事件完成会造成事件乱序（既有竞态）
    deadline = time.time() + 2
    while (
        time.time() < deadline
        and not app.state.event_bridge.store.list_sse_events("agent", thread_id)
    ):
        time.sleep(0.05)
    assert app.state.event_bridge.store.list_sse_events("agent", thread_id)

    response = client.post(f"/api/agent/threads/{thread_id}/stop")
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "stopped"

    # 历史修复：补了一条 cancelled ToolMessage，并记录操作日志
    # 收尾补打时间戳也会调用 aupdate_state，按 operation_log 定位修复调用
    repair_calls = [
        call
        for call in mock_graph.aupdate_state.await_args_list
        if "operation_log" in call.args[1]
    ]
    assert len(repair_calls) == 1
    updates = repair_calls[0].args[1]
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


def test_create_thread_with_auto_approve(client, app):
    project = _create_project(client)
    thread_id = _create_thread(
        client, project["id"], auto_approve=True
    )["thread_id"]
    assert app.state.agent_auto_approve[thread_id] is True


def test_thread_auto_approve_defaults_false(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]
    assert app.state.agent_auto_approve[thread_id] is False


def test_resume_thread_updates_auto_approve(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    response = client.post(
        f"/api/agent/threads/{thread_id}/resume",
        json={"auto_approve": True},
    )
    assert response.status_code == 200, response.text
    assert app.state.agent_auto_approve[thread_id] is True


def test_set_auto_approve(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]

    response = client.put(
        f"/api/agent/threads/{thread_id}/auto-approve", json={"enabled": True}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"auto_approve": True}
    assert app.state.agent_auto_approve[thread_id] is True

    response = client.put(
        f"/api/agent/threads/{thread_id}/auto-approve", json={"enabled": False}
    )
    assert response.status_code == 200, response.text
    assert app.state.agent_auto_approve[thread_id] is False


def test_set_auto_approve_thread_not_found(client):
    response = client.put(
        "/api/agent/threads/nonexistent/auto-approve", json={"enabled": True}
    )
    assert response.status_code == 404, response.text


def test_agent_config_carries_auto_approve(client, app):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"])["thread_id"]
    client.put(f"/api/agent/threads/{thread_id}/auto-approve", json={"enabled": True})

    config = asyncio.run(_agent_config(thread_id, app))

    assert config["configurable"]["auto_approve"] is True
    assert "llm_model" not in config["configurable"]


def test_make_message_stamps_timestamp():
    msg = _make_message("user", "hello")
    ts = msg.additional_kwargs.get("timestamp")
    assert ts
    # 合法 ISO 8601，解析不抛异常
    datetime.fromisoformat(ts)
    assert datetime.fromisoformat(ts).tzinfo is not None


@pytest.mark.parametrize(
    "msg",
    [
        HumanMessage(content="hi"),
        AIMessage(content="hi"),
        ToolMessage(content="res", tool_call_id="c1"),
    ],
)
def test_render_messages_includes_timestamp(msg):
    ts = "2026-07-17T04:00:00+00:00"
    msg.additional_kwargs["timestamp"] = ts
    rendered = _render_messages({"messages": [msg]})
    assert rendered[0]["timestamp"] == ts


def test_render_messages_omits_missing_timestamp():
    rendered = _render_messages({"messages": [HumanMessage(content="hi")]})
    assert "timestamp" not in rendered[0]


@pytest.mark.anyio
async def test_ensure_message_timestamps_stamps_missing_and_preserves_existing():
    graph = create_agent_graph()
    config = {"configurable": {"thread_id": f"ts-test-{uuid.uuid4().hex[:8]}"}}
    old_ts = "2026-01-01T00:00:00+00:00"
    stamped = AIMessage(content="old", additional_kwargs={"timestamp": old_ts})
    unstamped = ToolMessage(content="res", tool_call_id="call-1")
    await graph.aupdate_state(config, {"messages": [stamped, unstamped]})

    await _ensure_message_timestamps(graph, config)

    messages = (await graph.aget_state(config)).values["messages"]
    assert messages[0].additional_kwargs["timestamp"] == old_ts
    ts = messages[1].additional_kwargs.get("timestamp")
    assert ts
    datetime.fromisoformat(ts)


async def _run_interrupt_then_resume(tmp_path, action):
    """真实图经 _stream_agent 跑到 human_review 中断（收尾补打在途），再按 action 恢复。

    返回 (graph, config, 中断时的 snapshot)。mock 模式同 test_agent_graph.py。
    """
    project = {"path": str(tmp_path), "analysis": {"api_key": "fake", "model": "deepseek-v4-pro"}}
    state = build_initial_state(project)
    state["messages"] = [HumanMessage(content="list files")]

    graph = create_agent_graph()
    thread_id = f"ts-resume-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id, "api_key": "fake"}}
    bridge = SimpleNamespace(publish=AsyncMock())
    app = SimpleNamespace(
        state=SimpleNamespace(
            pipeline_tasks=set(),
            active_agent_streams=set(),
            agent_stream_tasks={},
        )
    )

    with patch("app.agent.nodes._stream_chat_completion") as mock_stream:
        mock_stream.side_effect = [
            AIMessage(
                content="",
                tool_calls=[{"name": "list_directory", "args": {"path": "."}, "id": "call_list"}],
            ),
            AIMessage(content="Done"),
        ]

        await _stream_agent(thread_id, graph, config, bridge, app, state)
        interrupted = await graph.aget_state(config)
        # 模拟生产 confirm/cancel 端点：Command(resume=...) 恢复同一线程
        await _stream_agent(
            thread_id, graph, config, bridge, app, Command(resume={"action": action})
        )

    return graph, config, interrupted


@pytest.mark.anyio
async def test_stream_backfill_preserves_interrupt_resume(tmp_path):
    """收尾补打时间戳不得破坏中断后的 confirm 恢复语义（真实 checkpoint）。"""
    graph, config, interrupted = await _run_interrupt_then_resume(tmp_path, "confirm")

    # 中断于 human_review，且收尾补打已为运行产生的消息盖上时间戳
    assert interrupted.values.get("interrupt_type") == "system_command"
    assert interrupted.values["messages"]
    for msg in interrupted.values["messages"]:
        assert msg.additional_kwargs.get("timestamp")

    # confirm 后运行真正恢复并完成：中断清除、工具结果补齐
    final = await graph.aget_state(config)
    assert final.values.get("interrupt_type") is None
    tool_msgs = [
        m
        for m in final.values["messages"]
        if isinstance(m, ToolMessage) and m.tool_call_id == "call_list"
    ]
    assert tool_msgs, "confirm 后应补齐 list_directory 的执行结果"
    parsed = json.loads(tool_msgs[-1].content)
    assert parsed.get("tool") == "list_directory"
    assert "result" in parsed
    for msg in final.values["messages"]:
        assert msg.additional_kwargs.get("timestamp")


@pytest.mark.anyio
async def test_stream_backfill_preserves_interrupt_resume_cancel(tmp_path):
    """收尾补打时间戳不得破坏中断后的 cancel 恢复语义（真实 checkpoint）。"""
    graph, config, interrupted = await _run_interrupt_then_resume(tmp_path, "cancel")

    assert interrupted.values.get("interrupt_type") == "system_command"

    final = await graph.aget_state(config)
    assert final.values.get("interrupt_type") is None
    tool_msgs = [
        m
        for m in final.values["messages"]
        if isinstance(m, ToolMessage) and m.tool_call_id == "call_list"
    ]
    assert tool_msgs, "cancel 后应补齐已取消的 ToolMessage"
    parsed = json.loads(tool_msgs[-1].content)
    assert parsed.get("cancelled") is True


@pytest.mark.anyio
async def test_stream_cleanup_runs_when_backfill_cancelled():
    """补打挂起期间任务被再次取消（CancelledError 不受 suppress(Exception) 拦截），
    清理也必须无条件执行，否则线程永远占住 active_agent_streams，后续发送全 409。
    """
    backfill_started = asyncio.Event()

    async def empty_astream(input_value=None, config=None, stream_mode=None):
        if False:
            yield {}

    async def blocking_aget_state(config):
        backfill_started.set()
        await asyncio.Event().wait()  # 永不就绪，模拟补打在读取 checkpoint 处挂起

    graph = SimpleNamespace(astream=empty_astream, aget_state=blocking_aget_state)
    thread_id = f"ts-cancel-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": thread_id}}
    bridge = SimpleNamespace(publish=AsyncMock())
    app = SimpleNamespace(
        state=SimpleNamespace(
            pipeline_tasks=set(),
            active_agent_streams={thread_id},
            agent_stream_tasks={},
        )
    )

    task = asyncio.create_task(
        _stream_agent(thread_id, graph, config, bridge, app, {"messages": []})
    )
    # 等任务确实挂进补打的 aget_state 再取消，避免时序猜测
    await asyncio.wait_for(backfill_started.wait(), timeout=2)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    assert task.done()
    assert thread_id not in app.state.active_agent_streams
    assert not app.state.pipeline_tasks
    assert thread_id not in app.state.agent_stream_tasks


def test_update_plan_on_fresh_thread(client):
    """回归：全新会话（尚未运行）更新计划不应 500。

    新鲜 checkpoint 未经任何节点执行（input-only），裸 aupdate_state 会抛
    InvalidUpdateError；修复后走回退路径正常写入。
    """
    project = _create_project(client)
    thread_id = _create_thread(client, project['id'])["thread_id"]

    plan = {"steps": [{"title": "步骤1", "description": "测试计划"}]}
    response = client.put(
        f"/api/agent/threads/{thread_id}/plan",
        json={"plan": plan},
    )
    assert response.status_code == 200, response.text
    assert response.json()["pending_plan"] == plan


def _wait_for_title_tasks(app, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(t.done() for t in app.state.agent_title_tasks):
            return
        time.sleep(0.05)
    raise AssertionError("title generation tasks did not finish in time")


def _mock_idle_graph(app):
    mock_graph = AsyncMock()
    mock_graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(values={"interrupt_type": None})
    )

    async def fake_astream(input_value=None, config=None, stream_mode=None):
        if False:
            yield

    mock_graph.astream = fake_astream
    app.dependency_overrides[get_agent_graph] = lambda: mock_graph


def test_thread_title_generated_via_llm(client, app, monkeypatch):
    """有 API key 时，首条用户消息触发后台 LLM 摘要命名。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"], api_key="sk-test")["thread_id"]

    class FakeLLM:
        def __init__(self, api_key=None, base_url=None, model=None):
            pass

        def call(self, system, user, temperature=0.1, max_tokens=1500):
            return "影像组学特征提取"

    monkeypatch.setattr("app.api.agent.LLMClient", FakeLLM)
    _mock_idle_graph(app)

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "帮我提取这批病例的影像组学特征"},
    )
    assert response.status_code == 202, response.text

    _wait_for_title_tasks(app)
    threads = _list_threads(client, project["id"])
    assert threads[0]["title"] == "影像组学特征提取"


def test_missing_thread_title_skill_returns_explicit_error(
    client, app, monkeypatch, tmp_path
):
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"], api_key="sk-test")["thread_id"]
    monkeypatch.setattr("app.skills.SKILLS_DIR", tmp_path / "missing-skills")

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "分析这批病例"},
    )

    assert response.status_code == 500
    assert "thread-title" in response.json()["detail"]
    assert "SKILL.md" in response.json()["detail"]


def test_thread_title_falls_back_to_truncation_on_llm_failure(client, app, monkeypatch):
    """LLM 调用失败时回退为首句截断命名。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"], api_key="sk-test")["thread_id"]

    class FailingLLM:
        def __init__(self, api_key=None, base_url=None, model=None):
            pass

        def call(self, system, user, temperature=0.1, max_tokens=1500):
            raise RuntimeError("api down")

    monkeypatch.setattr("app.api.agent.LLMClient", FailingLLM)
    _mock_idle_graph(app)

    content = "hello world this is a test"
    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": content},
    )
    assert response.status_code == 202, response.text

    _wait_for_title_tasks(app)
    threads = _list_threads(client, project["id"])
    assert threads[0]["title"] == content[:30]


def test_thread_title_not_overwritten_after_first_message(client, app, monkeypatch):
    """已有标题的会话不再触发自动命名。"""
    project = _create_project(client)
    thread_id = _create_thread(client, project["id"], api_key="sk-test")["thread_id"]

    class FakeLLM:
        def __init__(self, api_key=None, base_url=None, model=None):
            pass

        def call(self, system, user, temperature=0.1, max_tokens=1500):
            return "影像组学特征提取"

    monkeypatch.setattr("app.api.agent.LLMClient", FakeLLM)
    _mock_idle_graph(app)

    client.patch(f"/api/agent/threads/{thread_id}", json={"title": "手动标题"})

    response = client.post(
        f"/api/agent/threads/{thread_id}/messages",
        json={"role": "user", "content": "你好"},
    )
    assert response.status_code == 202, response.text

    threads = _list_threads(client, project["id"])
    assert threads[0]["title"] == "手动标题"


def test_render_messages_passes_through_reasoning_content():
    """assistant 消息的思考链透传到渲染结果，供历史消息展示。"""
    from app.api.agent import _render_messages

    ai = AIMessage(
        content="答案",
        additional_kwargs={"reasoning_content": "思考过程"},
    )
    rendered = _render_messages({"messages": [ai]})

    assert rendered[0]["role"] == "assistant"
    assert rendered[0]["reasoning_content"] == "思考过程"


def test_render_messages_omits_reasoning_when_absent():
    """无思考链的消息不应携带 reasoning_content 键。"""
    from app.api.agent import _render_messages

    ai = AIMessage(content="答案")
    rendered = _render_messages({"messages": [ai]})

    assert "reasoning_content" not in rendered[0]
