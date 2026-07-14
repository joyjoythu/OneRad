# OneRad Vue + FastAPI 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Gradio UI 完全替换为 Vue 3 + FastAPI，保留 CLI 离线分析能力，并使 AI Agent 审批中断状态持久化。

**Architecture:** FastAPI 托管 Vue 构建产物并提供 REST + SSE API；现有 `Orchestrator` 继续在后台线程运行影像组学流水线；LangGraph Agent 改用 `AsyncSqliteSaver` 并暴露异步 API；SSE 事件缓存到 SQLite 以支持断线续传。

**Tech Stack:** Python 3.11, FastAPI, uvicorn, Vue 3, Vite, TypeScript, Element Plus, Vue Router, Pinia, axios, LangGraph, AsyncSqliteSaver, aiosqlite

---

## 文件结构

### 后端新建/修改

- `app/api/__init__.py` — FastAPI 应用工厂 `create_app()`
- `app/api/deps.py` — 依赖注入：`ProjectStore`、`AsyncSqliteSaver` 单例
- `app/api/sse.py` — SSE 事件缓存（`sse_events` 表）与队列桥接
- `app/api/projects.py` — `/api/projects/*` CRUD
- `app/api/runs.py` — `/api/runs/*` 与流水线 SSE
- `app/api/agent.py` — `/api/agent/*` 与 Agent SSE
- `app/agent/graph.py` — 改为 `AsyncSqliteSaver`
- `app/projects.py` — 扩展 `sse_events` 表、运行幂等检查
- `app/orchestrator.py` — 标准化事件字段（可选）
- `main.py` — 启动 FastAPI 或 CLI
- `requirements.txt` — 移除 gradio，新增 fastapi 等
- `Dockerfile` / `docker-compose.yml` — 增加 Node 构建阶段
- `README.md` — 更新启动方式

### 前端新建

- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`
- `frontend/index.html`
- `frontend/src/main.ts`
- `frontend/src/App.vue`
- `frontend/src/router/index.ts`
- `frontend/src/stores/project.ts`、`run.ts`、`agent.ts`
- `frontend/src/api/projects.ts`、`runs.ts`、`agent.ts`
- `frontend/src/components/ProjectList.vue`、`AnalysisForm.vue`、`LogViewer.vue`、`AgentChat.vue`、`PlanPanel.vue`、`CommandPanel.vue`、`ScriptPanel.vue`
- `frontend/src/views/AnalysisView.vue`、`AgentView.vue`

### 删除

- `app/ui.py`
- `app/ui_agent.py`
- `app/ui_style.py`

---

## Phase 1: 后端基础设施

### Task 1: 安装依赖并验证环境

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 更新 requirements.txt**

```text
# Core
numpy>=1.24.0
pandas>=2.0.0
scikit-learn>=1.3.0
scipy>=1.10.0
matplotlib>=3.7.0

# Medical imaging
SimpleITK>=2.3.0
pyradiomics>=3.0.1

# LLM
openai>=1.0.0

# Report
python-docx>=1.1.0

# API
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
python-multipart>=0.0.17

# Utils
openpyxl>=3.1.0
h5py>=3.8.0
pyyaml>=6.0

# Development
pytest
httpx>=0.27.0

# Agent
langchain-core>=0.3.0
langchain-openai>=0.2.0
langgraph>=0.3.0
langgraph-checkpoint-sqlite>=2.0.0
aiosqlite>=0.20.0
```

- [ ] **Step 2: 安装依赖**

Run:
```bash
source .venv/Scripts/activate
pip install -r requirements.txt
```

Expected: 安装成功，无编译错误。

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add fastapi/uvicorn/langgraph-checkpoint-sqlite/aiosqlite, remove gradio"
```

---

### Task 2: 扩展 ProjectStore 支持 SSE 事件缓存与运行幂等

**Files:**
- Modify: `app/projects.py`

- [ ] **Step 1: 写测试验证新增方法**

Create `tests/test_project_store_extensions.py`:

```python
import pytest
from app.projects import ProjectStore

@pytest.fixture
def store(tmp_path):
    return ProjectStore(db_path=str(tmp_path / "test.db"))


def test_record_sse_event_and_list(store):
    store.record_sse_event("run", "run-1", 1, '{"type":"stage_start"}')
    events = store.list_sse_events("run", "run-1")
    assert len(events) == 1
    assert events[0]["event_id"] == 1


def test_list_sse_events_after_event_id(store):
    for i in range(1, 4):
        store.record_sse_event("run", "run-1", i, f'"event {i}"')
    events = store.list_sse_events("run", "run-1", after_event_id=1)
    assert len(events) == 2
    assert events[0]["event_id"] == 2


def test_has_running_run(store, tmp_path):
    project = store.create_project("p1", str(tmp_path / "p1"))
    store.record_run_start(project["id"], {"image_dir": "", "clinical_path": ""})
    assert store.has_running_run(project["id"]) is True


def test_no_running_run(store, tmp_path):
    project = store.create_project("p1", str(tmp_path / "p1"))
    assert store.has_running_run(project["id"]) is False
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
pytest tests/test_project_store_extensions.py -v
```

Expected: 4 个测试因方法不存在而失败。

- [ ] **Step 3: 扩展 ProjectStore**

Modify `app/projects.py`：

在 `_init_db` 中新增表：

```python
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS sse_events (
        scope TEXT NOT NULL,
        scope_id TEXT NOT NULL,
        event_id INTEGER NOT NULL,
        data TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (scope, scope_id, event_id)
    )
    """
)
```

新增方法：

```python
def record_sse_event(
    self,
    scope: str,
    scope_id: str,
    event_id: int,
    data: str,
) -> None:
    conn = sqlite3.connect(str(self.db_path))
    try:
        conn.execute(
            "INSERT INTO sse_events (scope, scope_id, event_id, data, created_at) VALUES (?, ?, ?, ?, ?)",
            (scope, scope_id, event_id, data, self._now()),
        )
        conn.commit()
    finally:
        conn.close()


def list_sse_events(
    self,
    scope: str,
    scope_id: str,
    after_event_id: int = 0,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(str(self.db_path))
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT scope, scope_id, event_id, data, created_at FROM sse_events WHERE scope = ? AND scope_id = ? AND event_id > ? ORDER BY event_id ASC LIMIT ?",
            (scope, scope_id, after_event_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def has_running_run(self, project_id: str) -> bool:
    conn = sqlite3.connect(str(self.db_path))
    try:
        row = conn.execute(
            "SELECT 1 FROM runs WHERE project_id = ? AND status = 'running' LIMIT 1",
            (project_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
pytest tests/test_project_store_extensions.py -v
```

Expected: 4 个测试全部通过。

- [ ] **Step 5: Commit**

```bash
git add app/projects.py tests/test_project_store_extensions.py
git commit -m "feat(store): add sse_events cache and running-run idempotency"
```

---

### Task 3: 创建 SSE 事件桥接模块

**Files:**
- Create: `app/api/sse.py`

- [ ] **Step 1: 编写测试**

Create `tests/test_sse_bridge.py`:

```python
import asyncio
import pytest
from app.api.sse import EventBridge


@pytest.fixture
def bridge(tmp_path):
    return EventBridge(db_path=str(tmp_path / "sse.db"))


def test_next_event_id_starts_at_one(bridge):
    assert bridge.next_event_id("run", "r1") == 1


def test_next_event_id_increments(bridge):
    bridge.publish("run", "r1", '{"msg":"a"}')
    assert bridge.next_event_id("run", "r1") == 2


@pytest.mark.asyncio
async def test_subscribe_receives_published_event(bridge):
    bridge.publish("run", "r1", '{"msg":"a"}')
    queue = bridge.subscribe("run", "r1", last_event_id=0)
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["id"] == 1
    assert event["data"] == '{"msg":"a"}'
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
pytest tests/test_sse_bridge.py -v
```

Expected: 3 个测试失败（`EventBridge` 不存在）。

- [ ] **Step 3: 实现 EventBridge**

Create `app/api/sse.py`:

```python
import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

from app.projects import ProjectStore


class EventBridge:
    """Publish/subscribe bridge for SSE with SQLite-backed replay."""

    def __init__(self, db_path: Optional[str] = None):
        self.store = ProjectStore(db_path=db_path)
        self._queues: Dict[str, Dict[str, asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    def _key(self, scope: str, scope_id: str) -> str:
        return f"{scope}:{scope_id}"

    def next_event_id(self, scope: str, scope_id: str) -> int:
        events = self.store.list_sse_events(scope, scope_id, limit=1)
        if events:
            return events[0]["event_id"] + 1
        return 1

    def publish(self, scope: str, scope_id: str, data: Any) -> int:
        event_id = self.next_event_id(scope, scope_id)
        payload = json.dumps(data, ensure_ascii=False)
        self.store.record_sse_event(scope, scope_id, event_id, payload)
        key = self._key(scope, scope_id)
        queues = self._queues.get(key, {})
        for queue in queues.values():
            queue.put_nowait({"id": event_id, "data": payload})
        return event_id

    async def subscribe(
        self,
        scope: str,
        scope_id: str,
        last_event_id: int = 0,
    ) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        key = self._key(scope, scope_id)
        async with self._lock:
            if key not in self._queues:
                self._queues[key] = {}
            queue_id = id(queue)
            self._queues[key][queue_id] = queue

        # Replay historical events
        for row in self.store.list_sse_events(scope, scope_id, after_event_id=last_event_id):
            await queue.put({"id": row["event_id"], "data": row["data"]})
        return queue

    async def unsubscribe(self, scope: str, scope_id: str, queue: asyncio.Queue) -> None:
        key = self._key(scope, scope_id)
        async with self._lock:
            queues = self._queues.get(key, {})
            queues.pop(id(queue), None)
            if not queues:
                self._queues.pop(key, None)
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
pytest tests/test_sse_bridge.py -v
```

Expected: 3 个测试全部通过。

- [ ] **Step 5: Commit**

```bash
git add app/api/sse.py tests/test_sse_bridge.py
git commit -m "feat(api): add EventBridge for SSE publish/subscribe and replay"
```

---

## Phase 2: FastAPI 后端 API

### Task 4: 创建 FastAPI 应用工厂与依赖

**Files:**
- Create: `app/api/__init__.py`
- Create: `app/api/deps.py`

- [ ] **Step 1: 创建依赖模块**

Create `app/api/deps.py`:

```python
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.projects import ProjectStore


@lru_cache()
def get_project_store() -> ProjectStore:
    db_dir = Path.home() / ".onerad"
    db_dir.mkdir(parents=True, exist_ok=True)
    return ProjectStore(db_path=str(db_dir / "projects.db"))


@lru_cache()
def get_checkpointer() -> AsyncSqliteSaver:
    db_dir = Path.home() / ".onerad"
    db_dir.mkdir(parents=True, exist_ok=True)
    return AsyncSqliteSaver.from_conn_string(str(db_dir / "checkpoints.db"))
```

- [ ] **Step 2: 创建应用工厂**

Create `app/api/__init__.py`:

```python
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.api import agent, projects, runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing required for sync store; checkpointer is created lazily.
    yield
    # Shutdown: cleanup if needed


def create_app() -> FastAPI:
    app = FastAPI(title="OneRad API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
    app.include_router(agent.router, prefix="/api/agent", tags=["agent"])

    dist_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist_dir.exists():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            index = dist_dir / "index.html"
            if index.exists():
                return FileResponse(index)
            return {"detail": "frontend not built"}

    return app
```

- [ ] **Step 3: 写启动测试**

Create `tests/test_api_factory.py`:

```python
from fastapi.testclient import TestClient
from app.api import create_app


def test_api_routers_registered():
    app = create_app()
    client = TestClient(app)
    response = client.get("/api/projects")
    assert response.status_code in (200, 401)  # 401 if we add auth later
```

- [ ] **Step 4: 运行测试**

Run:
```bash
pytest tests/test_api_factory.py -v
```

Expected: 通过。

- [ ] **Step 5: Commit**

```bash
git add app/api/__init__.py app/api/deps.py tests/test_api_factory.py
git commit -m "feat(api): add FastAPI app factory and dependency injection"
```

---

### Task 5: 实现项目 CRUD API

**Files:**
- Create: `app/api/projects.py`

- [ ] **Step 1: 写测试**

Create `tests/test_api_projects.py`:

```python
import pytest
from fastapi.testclient import TestClient
from app.api import create_app
from app.api.deps import get_project_store
from app.projects import ProjectStore


@pytest.fixture
def client(tmp_path):
    store = ProjectStore(db_path=str(tmp_path / "api.db"))

    def override_store():
        return store

    app = create_app()
    app.dependency_overrides[get_project_store] = override_store
    return TestClient(app)


def test_create_and_list_project(client):
    resp = client.post("/api/projects", json={"name": "p1", "path": "./tmp/p1", "description": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "p1"

    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_project(client):
    resp = client.post("/api/projects", json={"name": "p1", "path": "./tmp/p1", "description": ""})
    pid = resp.json()["id"]
    resp = client.get(f"/api/projects/{pid}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "p1"


def test_update_config(client):
    resp = client.post("/api/projects", json={"name": "p1", "path": "./tmp/p1", "description": ""})
    pid = resp.json()["id"]
    resp = client.put(
        f"/api/projects/{pid}/config",
        json={"image_dir": "/data/images", "clinical_path": "/data/clinical.csv"},
    )
    assert resp.status_code == 200
    assert resp.json()["analysis"]["image_dir"] == "/data/images"


def test_delete_project(client):
    resp = client.post("/api/projects", json={"name": "p1", "path": "./tmp/p1", "description": ""})
    pid = resp.json()["id"]
    resp = client.delete(f"/api/projects/{pid}")
    assert resp.status_code == 204
    resp = client.get(f"/api/projects/{pid}")
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
pytest tests/test_api_projects.py -v
```

Expected: 4 个测试失败（路由未实现或 404）。

- [ ] **Step 3: 实现路由**

Create `app/api/projects.py`:

```python
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_project_store
from app.projects import ProjectStore


router = APIRouter()


class CreateProjectRequest(BaseModel):
    name: str
    path: str
    description: str = ""


class UpdateConfigRequest(BaseModel):
    image_dir: Optional[str] = ""
    clinical_path: Optional[str] = ""
    output_dir: Optional[str] = "./outputs"
    modality: Optional[str] = "auto"
    covariates: Optional[str] = ""
    model: Optional[str] = "deepseek-v4-pro"
    api_key: Optional[str] = ""
    max_lasso_features: Optional[int] = 100
    n_splits: Optional[int] = 5


@router.get("", response_model=List[Dict[str, Any]])
def list_projects(store: ProjectStore = Depends(get_project_store)):
    return store.list_projects()


@router.post("", response_model=Dict[str, Any])
def create_project(req: CreateProjectRequest, store: ProjectStore = Depends(get_project_store)):
    try:
        return store.create_project(req.name, req.path, req.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{project_id}", response_model=Dict[str, Any])
def get_project(project_id: str, store: ProjectStore = Depends(get_project_store)):
    project = store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.put("/{project_id}/config", response_model=Dict[str, Any])
def update_config(
    project_id: str,
    req: UpdateConfigRequest,
    store: ProjectStore = Depends(get_project_store),
):
    try:
        return store.save_project_config(project_id, req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, store: ProjectStore = Depends(get_project_store)):
    store.delete_project(project_id)


@router.get("/{project_id}/runs", response_model=List[Dict[str, Any]])
def list_runs(project_id: str, store: ProjectStore = Depends(get_project_store)):
    return store.list_runs(project_id)
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
pytest tests/test_api_projects.py -v
```

Expected: 4 个测试通过。

- [ ] **Step 5: Commit**

```bash
git add app/api/projects.py tests/test_api_projects.py
git commit -m "feat(api): add project CRUD endpoints"
```

---

### Task 6: 实现流水线运行 API 与 SSE

**Files:**
- Create: `app/api/runs.py`
- Modify: `app/orchestrator.py`（可选：标准化事件字段）

- [ ] **Step 1: 写测试**

Create `tests/test_api_runs.py`:

```python
import pytest
from fastapi.testclient import TestClient
from app.api import create_app
from app.api.deps import get_project_store
from app.projects import ProjectStore


@pytest.fixture
def client(tmp_path):
    store = ProjectStore(db_path=str(tmp_path / "runs.db"))

    def override_store():
        return store

    app = create_app()
    app.dependency_overrides[get_project_store] = override_store
    return TestClient(app)


def test_start_run_idempotency(client):
    resp = client.post("/api/projects", json={"name": "p1", "path": "./tmp/p1", "description": ""})
    pid = resp.json()["id"]
    resp = client.post(f"/api/projects/{pid}/runs", json={})
    assert resp.status_code == 200
    resp = client.post(f"/api/projects/{pid}/runs", json={})
    assert resp.status_code == 409


def test_get_run_events_sse(client):
    resp = client.post("/api/projects", json={"name": "p1", "path": "./tmp/p1", "description": ""})
    pid = resp.json()["id"]
    resp = client.post(f"/api/projects/{pid}/runs", json={})
    run_id = resp.json()["run_id"]
    resp = client.get(f"/api/runs/{run_id}/events")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
pytest tests/test_api_runs.py -v
```

Expected: 2 个测试失败。

- [ ] **Step 3: 实现 runs.py**

Create `app/api/runs.py`:

```python
import asyncio
import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_project_store
from app.api.sse import EventBridge
from app.orchestrator import Orchestrator, register_default_handlers
from app.projects import ProjectStore
from app.utils import parse_covariates


router = APIRouter()

# Module-level bridge; in production could be a singleton dependency.
_bridge = None


def _get_bridge(store: ProjectStore) -> EventBridge:
    global _bridge
    if _bridge is None:
        _bridge = EventBridge(db_path=str(store.db_path))
    return _bridge


class RunConfig(BaseModel):
    image_dir: str = ""
    clinical_path: str = ""
    output_dir: str = "./outputs"
    modality: str = "auto"
    covariates: str = ""
    model: str = "deepseek-v4-pro"
    api_key: str = ""
    max_lasso_features: int = 100
    n_splits: int = 5


def _run_pipeline(
    project_id: str,
    run_id: str,
    config: Dict[str, Any],
    bridge: EventBridge,
    store: ProjectStore,
):
    from pathlib import Path

    project = store.load_project(project_id)
    yaml_path = str(Path(project["path"]) / "Params_labels.yaml")

    orch = Orchestrator(
        image_dir=config.get("image_dir") or "",
        clinical_path=config.get("clinical_path") or "",
        output_dir=config.get("output_dir") or "./outputs",
        modality=config.get("modality") or "auto",
        covariates=parse_covariates(config.get("covariates") or ""),
        api_key=config.get("api_key"),
        model=config.get("model") or "deepseek-v4-pro",
        yaml_path=yaml_path,
        max_lasso_features=int(config.get("max_lasso_features", 100)),
        n_splits=int(config.get("n_splits", 5)),
    )
    register_default_handlers(orch)

    def emit(event: Dict[str, Any]):
        bridge.publish("run", run_id, event)

    orch.set_sse_emitter(emit)

    report_path = ""
    try:
        for _ in orch.run():
            pass
        report_path = orch.state.get("report", {}).get("report_path", "")
        status = "success" if report_path else "failed"
        logs = ""
    except Exception as e:
        status = "failed"
        logs = str(e)
        bridge.publish("run", run_id, {"type": "error", "message": str(e)})
    finally:
        store.record_run_end(run_id, status, logs, report_path or "")


@router.post("/projects/{project_id}/runs")
def start_run(
    project_id: str,
    req: RunConfig,
    store: ProjectStore = Depends(get_project_store),
):
    if store.has_running_run(project_id):
        raise HTTPException(status_code=409, detail="该项目已有正在运行的分析")

    config = req.model_dump()
    run_id = store.record_run_start(project_id, config)
    bridge = _get_bridge(store)

    # Start pipeline in background thread.
    asyncio.create_task(
        run_in_threadpool(_run_pipeline, project_id, run_id, config, bridge, store)
    )
    return {"run_id": run_id}


@router.get("/{run_id}")
def get_run(run_id: str, store: ProjectStore = Depends(get_project_store)):
    runs = store.list_runs("")
    for run in runs:
        if run["id"] == run_id:
            return run
    raise HTTPException(status_code=404, detail="运行记录不存在")


@router.get("/{run_id}/events")
async def run_events(
    run_id: str,
    last_event_id: int = 0,
    store: ProjectStore = Depends(get_project_store),
):
    bridge = _get_bridge(store)

    async def event_generator():
        queue = await bridge.subscribe("run", run_id, last_event_id=last_event_id)
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"id: {event['id']}\nevent: pipeline\ndata: {event['data']}\n\n"
        except asyncio.TimeoutError:
            yield f"event: keepalive\ndata: {{}}\n\n"
        finally:
            await bridge.unsubscribe("run", run_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
```

注意：`get_run` 中的 `store.list_runs("")` 是错误占位；后续会修正。

- [ ] **Step 4: 修正 get_run 需要按 run_id 查询**

在 `app/projects.py` 中新增方法：

```python
def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(str(self.db_path))
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
```

修改 `app/api/runs.py` 中 `get_run`：

```python
@router.get("/{run_id}")
def get_run(run_id: str, store: ProjectStore = Depends(get_project_store)):
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run
```

- [ ] **Step 5: 运行测试确认通过**

Run:
```bash
pytest tests/test_api_runs.py -v
```

Expected: 2 个测试通过。

- [ ] **Step 6: Commit**

```bash
git add app/api/runs.py app/projects.py tests/test_api_runs.py
git commit -m "feat(api): add pipeline run trigger and SSE endpoint"
```

---

### Task 7: 实现 AI Agent API 与异步 SSE

**Files:**
- Create: `app/api/agent.py`
- Modify: `app/agent/graph.py`
- Create: `tests/test_api_agent.py`

- [ ] **Step 1: 修改 LangGraph 使用 AsyncSqliteSaver**

Modify `app/agent/graph.py`:

```python
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState
from app.agent.nodes import (
    call_llm,
    process_tool_calls,
    human_review,
    execute_confirmed,
    should_continue,
    route_after_process,
)


def create_agent_graph(checkpointer=None):
    builder = StateGraph(AgentState)
    builder.add_node("call_llm", call_llm)
    builder.add_node("process_tool_calls", process_tool_calls)
    builder.add_node("human_review", human_review)
    builder.add_node("execute_confirmed", execute_confirmed)

    builder.add_edge(START, "call_llm")
    builder.add_conditional_edges("call_llm", should_continue, {"process_tool_calls": "process_tool_calls", "__end__": END})
    builder.add_conditional_edges("process_tool_calls", route_after_process, {"human_review": "human_review", "call_llm": "call_llm"})
    builder.add_edge("human_review", "execute_confirmed")
    builder.add_edge("execute_confirmed", "call_llm")

    return builder.compile(checkpointer=checkpointer)
```

- [ ] **Step 2: 更新 agent/__init__.py 接受 checkpointer**

Modify `app/agent/__init__.py`:

```python
from app.agent.state import AgentState


def create_agent_graph(checkpointer=None):
    from app.agent.graph import create_agent_graph as _create_agent_graph
    return _create_agent_graph(checkpointer=checkpointer)


def build_initial_state(project: dict) -> AgentState:
    analysis = project.get("analysis", {})
    return {
        "messages": [],
        "project_path": project["path"],
        "api_key": analysis.get("api_key", ""),
        "base_url": "https://api.deepseek.com/v1",
        "model": analysis.get("model", "deepseek-v4-pro"),
        "interrupt_type": None,
        "pending_plan": None,
        "pending_command": None,
        "pending_script": None,
        "script_risk_level": None,
        "confirmed": None,
        "tool_outputs": [],
        "operation_log": [],
    }
```

- [ ] **Step 3: 写 Agent API 测试**

Create `tests/test_api_agent.py`:

```python
import pytest
from fastapi.testclient import TestClient
from app.api import create_app
from app.api.deps import get_checkpointer, get_project_store
from app.projects import ProjectStore


@pytest.fixture
def client(tmp_path):
    store = ProjectStore(db_path=str(tmp_path / "agent.db"))

    async def override_checkpointer():
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        return AsyncSqliteSaver.from_conn_string(str(tmp_path / "agent_checkpoints.db"))

    def override_store():
        return store

    app = create_app()
    app.dependency_overrides[get_project_store] = override_store
    app.dependency_overrides[get_checkpointer] = override_checkpointer
    return TestClient(app)


def test_create_thread(client):
    resp = client.post("/api/projects", json={"name": "p1", "path": "./tmp/p1", "description": ""})
    pid = resp.json()["id"]
    resp = client.post("/api/agent/threads", params={"project_id": pid})
    assert resp.status_code == 200
    assert "thread_id" in resp.json()
```

- [ ] **Step 4: 运行测试确认失败**

Run:
```bash
pytest tests/test_api_agent.py -v
```

Expected: 1 个测试失败。

- [ ] **Step 5: 实现 agent.py**

Create `app/api/agent.py`:

```python
import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.api.deps import get_checkpointer, get_project_store
from app.api.sse import EventBridge
from app.agent import build_initial_state, create_agent_graph
from app.projects import ProjectStore


router = APIRouter()
_bridge = None


def _get_agent_bridge(store: ProjectStore) -> EventBridge:
    global _bridge
    if _bridge is None:
        _bridge = EventBridge(db_path=str(store.db_path))
    return _bridge


def _render_messages(values: Dict[str, Any]) -> List[Dict[str, str]]:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    history = []
    for msg in values.get("messages", []):
        if isinstance(msg, HumanMessage):
            history.append({"role": "user", "content": str(msg.content)})
        elif isinstance(msg, AIMessage):
            history.append({"role": "assistant", "content": str(msg.content)})
        elif isinstance(msg, ToolMessage):
            if history and history[-1]["role"] == "assistant":
                history[-1]["content"] += f"\n\n[工具结果]\n{msg.content}"
            else:
                history.append({"role": "assistant", "content": f"[工具结果]\n{msg.content}"})
    return history


def _sync_payload(values: Dict[str, Any]) -> Dict[str, Any]:
    interrupt_type = values.get("interrupt_type")
    payload = {
        "messages": _render_messages(values),
        "interrupt_type": interrupt_type,
        "operation_log": list(values.get("operation_log", [])),
    }
    if interrupt_type == "file_plan":
        payload["pending_plan"] = values.get("pending_plan", {})
    elif interrupt_type == "system_command":
        payload["pending_command"] = values.get("pending_command")
    elif interrupt_type == "python_script":
        payload["pending_script"] = values.get("pending_script")
    return payload


@router.post("/threads")
async def create_thread(
    project_id: str = Query(...),
    store: ProjectStore = Depends(get_project_store),
    checkpointer=Depends(get_checkpointer),
):
    project = store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    graph = create_agent_graph(checkpointer=checkpointer)
    init_state = build_initial_state(project)
    await graph.aupdate_state(config, init_state)
    return {"thread_id": thread_id}


@router.get("/threads/{thread_id}")
async def get_thread(
    thread_id: str,
    checkpointer=Depends(get_checkpointer),
):
    graph = create_agent_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    try:
        snapshot = await graph.aget_state(config)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    values = getattr(snapshot, "values", {}) or {}
    return _sync_payload(values)


@router.post("/threads/{thread_id}/messages")
async def send_message(
    thread_id: str,
    payload: Dict[str, Any],
    store: ProjectStore = Depends(get_project_store),
    checkpointer=Depends(get_checkpointer),
):
    content = payload.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    graph = create_agent_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    bridge = _get_agent_bridge(store)

    async def stream_and_publish():
        try:
            async for chunk in graph.astream(
                {"messages": [HumanMessage(content=content)]},
                config,
                stream_mode="values",
            ):
                bridge.publish("agent_thread", thread_id, _sync_payload(chunk))
        except Exception as e:
            bridge.publish("agent_thread", thread_id, {"type": "error", "message": str(e)})

    asyncio.create_task(stream_and_publish())
    return {"status": "streaming"}


@router.put("/threads/{thread_id}/plan")
async def update_plan(
    thread_id: str,
    payload: Dict[str, Any],
    checkpointer=Depends(get_checkpointer),
):
    graph = create_agent_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph.aget_state(config)
    values = getattr(snapshot, "values", {}) or {}
    pending_plan = values.get("pending_plan") or {}
    pending_plan["plan"] = payload.get("plan", [])
    await graph.aupdate_state(config, {"pending_plan": pending_plan})
    return {"status": "updated"}


@router.post("/threads/{thread_id}/confirm")
async def confirm(
    thread_id: str,
    store: ProjectStore = Depends(get_project_store),
    checkpointer=Depends(get_checkpointer),
):
    return await _resume(thread_id, "confirm", store, checkpointer)


@router.post("/threads/{thread_id}/cancel")
async def cancel(
    thread_id: str,
    store: ProjectStore = Depends(get_project_store),
    checkpointer=Depends(get_checkpointer),
):
    return await _resume(thread_id, "cancel", store, checkpointer)


async def _resume(
    thread_id: str,
    action: str,
    store: ProjectStore,
    checkpointer,
):
    graph = create_agent_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    bridge = _get_agent_bridge(store)

    async def stream_and_publish():
        try:
            async for chunk in graph.astream(
                Command(resume={"action": action}),
                config,
                stream_mode="values",
            ):
                bridge.publish("agent_thread", thread_id, _sync_payload(chunk))
        except Exception as e:
            bridge.publish("agent_thread", thread_id, {"type": "error", "message": str(e)})

    asyncio.create_task(stream_and_publish())
    return {"status": "resumed"}


@router.get("/threads/{thread_id}/events")
async def agent_events(
    thread_id: str,
    last_event_id: int = 0,
    store: ProjectStore = Depends(get_project_store),
):
    bridge = _get_agent_bridge(store)

    async def event_generator():
        queue = await bridge.subscribe("agent_thread", thread_id, last_event_id=last_event_id)
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"id: {event['id']}\nevent: agent\ndata: {event['data']}\n\n"
        except asyncio.TimeoutError:
            yield f"event: keepalive\ndata: {{}}\n\n"
        finally:
            await bridge.unsubscribe("agent_thread", thread_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
```

- [ ] **Step 6: 运行测试确认通过**

Run:
```bash
pytest tests/test_api_agent.py -v
```

Expected: 1 个测试通过。

- [ ] **Step 7: Commit**

```bash
git add app/api/agent.py app/agent/graph.py app/agent/__init__.py tests/test_api_agent.py
git commit -m "feat(api): add async LangGraph Agent endpoints with AsyncSqliteSaver"
```

---

## Phase 3: 入口与清理

### Task 8: 重写 main.py 启动 FastAPI 或 CLI

**Files:**
- Modify: `main.py`

- [ ] **Step 1: 修改 main.py**

Replace the UI branch with FastAPI launch:

```python
import argparse
import logging
import os
import sys
import traceback

import pandas as pd
import uvicorn

from app.direct_analysis import run_direct_analysis
from app.utils import parse_covariates, parse_float_tuple


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="AutoRadiomics Agent")
    parser.add_argument("--image-dir", default=None)
    parser.add_argument("--clinical", default=None)
    parser.add_argument("--feature-csv", default=None)
    parser.add_argument("--label-col", default=None)
    parser.add_argument("--output-dir", default="./output")
    parser.add_argument("--modality", default="auto")
    parser.add_argument("--covariates", default="")
    parser.add_argument("--max-lasso-features", type=int, default=100)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--resampled-pixel-spacing", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default="https://api.deepseek.com/v1")
    parser.add_argument("--model", default="deepseek-v4-pro")
    parser.add_argument("--host", default="0.0.0.0", help="FastAPI 监听地址")
    parser.add_argument("--port", type=int, default=8000, help="FastAPI 监听端口")
    return parser.parse_args(argv)


def _run_direct_analysis(args) -> str:
    return run_direct_analysis(
        feature_csv=args.feature_csv,
        clinical=args.clinical,
        output_dir=args.output_dir,
        label_col=args.label_col,
        modality=args.modality,
        covariates=parse_covariates(args.covariates),
        max_lasso_features=args.max_lasso_features,
        n_splits=args.n_splits,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )


def _should_run_server(args) -> bool:
    """当用户未提供离线分析参数时启动 Web UI。"""
    return args.image_dir is None and args.feature_csv is None


def main():
    args = _parse_args()

    if _should_run_server(args):
        from app.api import create_app
        app = create_app()
        uvicorn.run(app, host=args.host, port=args.port)
        return

    if args.feature_csv:
        if not args.clinical:
            print("错误: --feature-csv 模式必须同时提供 --clinical", file=sys.stderr)
            sys.exit(1)
        try:
            report_path = _run_direct_analysis(args)
            print(f"Report: {report_path}")
        except Exception as e:
            print(f"直接分析失败: {e}", file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)
        return

    if args.clinical is None:
        print("错误: 必须提供 --clinical", file=sys.stderr)
        sys.exit(1)

    import os
    cached_feature_csv = os.path.join(args.output_dir, "radiomics_features.csv")
    if os.path.exists(cached_feature_csv) and args.image_dir:
        print(f"检测到已存在的特征文件，直接用于分析: {cached_feature_csv}")
        print("如需重新提取特征，请删除该文件或更换 --output-dir")
        args.feature_csv = cached_feature_csv
        try:
            report_path = _run_direct_analysis(args)
            print(f"Report: {report_path}")
        except Exception as e:
            print(f"直接分析失败: {e}", file=sys.stderr)
            traceback.print_exc()
            sys.exit(1)
        return

    from app.orchestrator import Orchestrator, register_default_handlers
    orch = Orchestrator(
        image_dir=args.image_dir,
        clinical_path=args.clinical,
        output_dir=args.output_dir,
        modality=args.modality,
        covariates=parse_covariates(args.covariates),
        max_lasso_features=args.max_lasso_features,
        n_splits=args.n_splits,
        resampled_pixel_spacing=parse_float_tuple(args.resampled_pixel_spacing),
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )
    register_default_handlers(orch)
    try:
        for event in orch.run():
            print(event)
    except Exception as e:
        print(f"流水线执行失败: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    _save_extracted_features(orch.state, args.output_dir)
    print(f"Report: {orch.state.get('report', {}).get('report_path')}")


def _save_extracted_features(state: dict, output_dir: str) -> None:
    feature_state = state.get("feature")
    if not isinstance(feature_state, dict):
        return
    feature_df = feature_state.get("feature_df")
    if not isinstance(feature_df, pd.DataFrame) or feature_df.empty:
        return
    try:
        os.makedirs(output_dir, exist_ok=True)
        cache_path = os.path.join(output_dir, "radiomics_features.csv")
        feature_df.reset_index().to_csv(cache_path, index=False)
        print(f"特征矩阵已缓存: {cache_path}")
    except Exception as e:
        logging.warning(f"特征矩阵缓存失败: {e}", exc_info=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 测试入口分支**

Run:
```bash
python main.py --help
```

Expected: 帮助信息包含 `--host` 和 `--port`，不再包含 `--ui`。

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(entry): launch FastAPI server when no CLI args, keep offline CLI mode"
```

---

### Task 9: 删除 Gradio UI 文件并清理依赖引用

**Files:**
- Delete: `app/ui.py`, `app/ui_agent.py`, `app/ui_style.py`
- Modify: any test referencing these modules

- [ ] **Step 1: 查找引用**

Run:
```bash
grep -r "app.ui" tests/ app/ --include="*.py" | grep -v __pycache__
```

Expected: 引用主要出现在 `tests/test_ui*.py` 等旧测试文件中。

- [ ] **Step 2: 删除 UI 文件**

Run:
```bash
rm app/ui.py app/ui_agent.py app/ui_style.py
```

- [ ] **Step 3: 移除或重写 Gradio 相关测试**

若 `tests/test_ui.py` 等文件存在，删除或改为测试 API：

```bash
rm tests/test_ui.py tests/test_ui_agent.py 2>/dev/null || true
```

- [ ] **Step 4: 运行测试套件确认无残留**

Run:
```bash
pytest tests/ -v
```

Expected: 无 `ModuleNotFoundError: app.ui` 错误。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove Gradio UI modules and related tests"
```

---

## Phase 4: Vue 前端

### Task 10: 初始化前端脚手架

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/index.html`

- [ ] **Step 1: 创建 package.json**

Create `frontend/package.json`:

```json
{
  "name": "onerad-frontend",
  "private": true,
  "version": "2.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest"
  },
  "dependencies": {
    "@element-plus/icons-vue": "^2.3.1",
    "axios": "^1.7.0",
    "element-plus": "^2.8.0",
    "pinia": "^2.2.0",
    "vue": "^3.5.0",
    "vue-router": "^4.4.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.1.0",
    "@vue/test-utils": "^2.4.0",
    "jsdom": "^25.0.0",
    "typescript": "^5.6.0",
    "vite": "^5.4.0",
    "vitest": "^2.1.0",
    "vue-tsc": "^2.1.0"
  }
}
```

- [ ] **Step 2: 创建 Vite 配置**

Create `frontend/vite.config.ts`:

```typescript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
```

- [ ] **Step 3: 创建 tsconfig**

Create `frontend/tsconfig.json`:

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ]
}
```

Create `frontend/tsconfig.app.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",
    "target": "ES2020",
    "useDefineForClassFields": true,
    "module": "ESNext",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "preserve",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  },
  "include": ["src/**/*.ts", "src/**/*.tsx", "src/**/*.vue"]
}
```

Create `frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.node.tsbuildinfo",
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "noEmit": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 4: 创建入口 HTML**

Create `frontend/index.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>OneRad</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 5: 安装前端依赖**

Run:
```bash
cd frontend
npm install
```

Expected: `node_modules` 生成，无报错。

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/vite.config.ts frontend/tsconfig*.json frontend/index.html
git commit -m "feat(frontend): add Vue 3 + Vite + TypeScript scaffold"
```

---

### Task 11: 创建 Pinia Store 和 API 客户端

**Files:**
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/api/projects.ts`
- Create: `frontend/src/api/runs.ts`
- Create: `frontend/src/api/agent.ts`
- Create: `frontend/src/stores/project.ts`
- Create: `frontend/src/stores/run.ts`
- Create: `frontend/src/stores/agent.ts`

- [ ] **Step 1: 创建 axios 实例**

Create `frontend/src/api/client.ts`:

```typescript
import axios from 'axios'
import { ElMessage } from 'element-plus'

const client = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    ElMessage.error(msg)
    return Promise.reject(err)
  }
)

export default client
```

- [ ] **Step 2: 创建 API 模块**

Create `frontend/src/api/projects.ts`:

```typescript
import client from './client'

export interface Project {
  id: string
  name: string
  path: string
  description: string
  created_at: string
  updated_at: string
  analysis: AnalysisConfig
}

export interface AnalysisConfig {
  image_dir: string
  clinical_path: string
  output_dir: string
  modality: string
  covariates: string
  model: string
  api_key: string
  max_lasso_features: number
  n_splits: number
}

export const listProjects = () => client.get('/projects').then((r) => r.data as Project[])

export const createProject = (payload: { name: string; path: string; description?: string }) =>
  client.post('/projects', payload).then((r) => r.data as Project)

export const getProject = (id: string) => client.get(`/projects/${id}`).then((r) => r.data as Project)

export const updateConfig = (id: string, config: Partial<AnalysisConfig>) =>
  client.put(`/projects/${id}/config`, config).then((r) => r.data as Project)

export const deleteProject = (id: string) => client.delete(`/projects/${id}`)

export const listRuns = (id: string) => client.get(`/projects/${id}/runs`).then((r) => r.data)
```

Create `frontend/src/api/runs.ts`:

```typescript
import client from './client'
import type { AnalysisConfig } from './projects'

export const startRun = (projectId: string, config: AnalysisConfig) =>
  client.post(`/projects/${projectId}/runs`, config).then((r) => r.data as { run_id: string })

export const getRun = (runId: string) => client.get(`/runs/${runId}`).then((r) => r.data)

export function connectRunEvents(runId: string, onEvent: (data: any) => void, lastEventId = 0) {
  const url = `/runs/${runId}/events?last_event_id=${lastEventId}`
  const es = new EventSource(url)
  es.onmessage = (e) => {
    if (e.lastEventId) {
      localStorage.setItem(`onerad_run_${runId}_last_id`, e.lastEventId)
    }
    const data = JSON.parse(e.data)
    onEvent(data)
  }
  es.onerror = () => {
    // Auto-reconnect is built into EventSource; caller can close if needed.
  }
  return es
}
```

Create `frontend/src/api/agent.ts`:

```typescript
import client from './client'

export const createThread = (projectId: string) =>
  client.post('/agent/threads', null, { params: { project_id: projectId } }).then((r) => r.data as { thread_id: string })

export const getThread = (threadId: string) => client.get(`/agent/threads/${threadId}`).then((r) => r.data)

export const sendMessage = (threadId: string, content: string) =>
  client.post(`/agent/threads/${threadId}/messages`, { content }).then((r) => r.data)

export const updatePlan = (threadId: string, plan: any[]) =>
  client.put(`/agent/threads/${threadId}/plan`, { plan }).then((r) => r.data)

export const confirm = (threadId: string) => client.post(`/agent/threads/${threadId}/confirm`).then((r) => r.data)

export const cancel = (threadId: string) => client.post(`/agent/threads/${threadId}/cancel`).then((r) => r.data)

export function connectAgentEvents(threadId: string, onEvent: (data: any) => void, lastEventId = 0) {
  const url = `/agent/threads/${threadId}/events?last_event_id=${lastEventId}`
  const es = new EventSource(url)
  es.onmessage = (e) => {
    if (e.lastEventId) {
      localStorage.setItem(`onerad_agent_${threadId}_last_id`, e.lastEventId)
    }
    const data = JSON.parse(e.data)
    onEvent(data)
  }
  return es
}
```

- [ ] **Step 3: 创建 Pinia stores**

Create `frontend/src/stores/project.ts`:

```typescript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '@/api/projects'
import type { Project, AnalysisConfig } from '@/api/projects'

export const useProjectStore = defineStore('project', () => {
  const projects = ref<Project[]>([])
  const currentProject = ref<Project | null>(null)
  const loading = ref(false)

  const currentConfig = computed<AnalysisConfig>(() => {
    return (
      currentProject.value?.analysis || {
        image_dir: '',
        clinical_path: '',
        output_dir: './outputs',
        modality: 'auto',
        covariates: '',
        model: 'deepseek-v4-pro',
        api_key: '',
        max_lasso_features: 100,
        n_splits: 5,
      }
    )
  })

  async function loadProjects() {
    loading.value = true
    projects.value = await api.listProjects()
    loading.value = false
  }

  async function selectProject(id: string) {
    currentProject.value = await api.getProject(id)
  }

  async function createProject(payload: { name: string; path: string; description?: string }) {
    const project = await api.createProject(payload)
    await loadProjects()
    await selectProject(project.id)
    return project
  }

  async function deleteProject(id: string) {
    await api.deleteProject(id)
    if (currentProject.value?.id === id) {
      currentProject.value = null
    }
    await loadProjects()
  }

  async function saveConfig(config: Partial<AnalysisConfig>) {
    if (!currentProject.value) return
    currentProject.value = await api.updateConfig(currentProject.value.id, config)
  }

  return {
    projects,
    currentProject,
    currentConfig,
    loading,
    loadProjects,
    selectProject,
    createProject,
    deleteProject,
    saveConfig,
  }
})
```

Create `frontend/src/stores/run.ts`:

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '@/api/runs'

export const useRunStore = defineStore('run', () => {
  const currentRun = ref<any>(null)
  const logs = ref<string>('')
  const running = ref(false)
  const reportUrl = ref<string>('')
  let es: EventSource | null = null

  function appendLog(event: any) {
    const line = `[${event.stage || '-'}] ${event.type}: ${event.message}`
    logs.value += line + '\n'
  }

  async function startRun(projectId: string, config: any) {
    if (running.value) return
    running.value = true
    logs.value = ''
    reportUrl.value = ''

    try {
      const { run_id } = await api.startRun(projectId, config)
      currentRun.value = { id: run_id }
      const lastId = parseInt(localStorage.getItem(`onerad_run_${run_id}_last_id`) || '0', 10)
      es = api.connectRunEvents(run_id, (event) => {
        appendLog(event)
        if (event.type === 'pipeline_complete') {
          running.value = false
          api.getRun(run_id).then((run) => {
            if (run.report_path) {
              reportUrl.value = `/api/runs/${run_id}/report?path=${encodeURIComponent(run.report_path)}`
            }
          })
        }
        if (event.type === 'error') {
          running.value = false
        }
      }, lastId)
    } catch (e) {
      running.value = false
      throw e
    }
  }

  function disconnect() {
    es?.close()
    es = null
  }

  return {
    currentRun,
    logs,
    running,
    reportUrl,
    startRun,
    disconnect,
  }
})
```

Create `frontend/src/stores/agent.ts`:

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '@/api/agent'

export interface AgentMessage {
  role: 'user' | 'assistant'
  content: string
}

export const useAgentStore = defineStore('agent', () => {
  const threadId = ref<string | null>(null)
  const messages = ref<AgentMessage[]>([])
  const interrupt = ref<any>(null)
  const operationLog = ref<string[]>([])
  let es: EventSource | null = null

  function handleEvent(event: any) {
    if (event.messages) {
      messages.value = event.messages
    }
    if (event.operation_log) {
      operationLog.value = event.operation_log
    }
    if (event.interrupt_type) {
      interrupt.value = event
    } else {
      interrupt.value = null
    }
  }

  async function ensureThread(projectId: string) {
    if (threadId.value) return
    const data = await api.createThread(projectId)
    threadId.value = data.thread_id
    const lastId = parseInt(localStorage.getItem(`onerad_agent_${data.thread_id}_last_id`) || '0', 10)
    es = api.connectAgentEvents(data.thread_id, handleEvent, lastId)
  }

  async function sendMessage(projectId: string, content: string) {
    await ensureThread(projectId)
    if (!threadId.value) return
    messages.value.push({ role: 'user', content })
    await api.sendMessage(threadId.value, content)
  }

  async function updatePlan(plan: any[]) {
    if (!threadId.value) return
    await api.updatePlan(threadId.value, plan)
  }

  async function confirm() {
    if (!threadId.value) return
    await api.confirm(threadId.value)
    interrupt.value = null
  }

  async function cancel() {
    if (!threadId.value) return
    await api.cancel(threadId.value)
    interrupt.value = null
  }

  function disconnect() {
    es?.close()
    es = null
    threadId.value = null
  }

  return {
    threadId,
    messages,
    interrupt,
    operationLog,
    ensureThread,
    sendMessage,
    updatePlan,
    confirm,
    cancel,
    disconnect,
  }
})
```

- [ ] **Step 4: 创建路由与入口**

Create `frontend/src/router/index.ts`:

```typescript
import { createRouter, createWebHistory } from 'vue-router'
import AnalysisView from '@/views/AnalysisView.vue'
import AgentView from '@/views/AgentView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'analysis', component: AnalysisView },
    { path: '/agent', name: 'agent', component: AgentView },
  ],
})

export default router
```

Create `frontend/src/main.ts`:

```typescript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'

import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.mount('#app')
```

Create `frontend/src/App.vue`:

```vue
<template>
  <div class="onerad-app">
    <header class="onerad-header">
      <div class="onerad-header-left">
        <span class="onerad-logo">OneRad</span>
        <span class="onerad-subtitle">医学影像智能分析平台</span>
      </div>
      <nav class="onerad-nav">
        <el-button text @click="$router.push('/')">影像组学分析</el-button>
        <el-button text @click="$router.push('/agent')">AI Agent</el-button>
      </nav>
    </header>
    <div class="onerad-body">
      <ProjectList class="onerad-sidebar" />
      <main class="onerad-main">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import ProjectList from '@/components/ProjectList.vue'
</script>

<style scoped>
.onerad-app { display: flex; flex-direction: column; height: 100vh; background: #f5f6f8; }
.onerad-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 24px; background: #fff; border-bottom: 1px solid #e5e7eb; }
.onerad-header-left { display: flex; align-items: center; gap: 12px; }
.onerad-logo { font-size: 20px; font-weight: 700; color: #1f2937; }
.onerad-subtitle { font-size: 13px; color: #6b7280; }
.onerad-nav { display: flex; gap: 8px; }
.onerad-body { display: flex; flex: 1; overflow: hidden; }
.onerad-sidebar { width: 320px; flex-shrink: 0; background: #fff; border-right: 1px solid #e5e7eb; padding: 16px; overflow-y: auto; }
.onerad-main { flex: 1; padding: 20px; overflow-y: auto; }
</style>
```

- [ ] **Step 5: 运行类型检查**

Run:
```bash
cd frontend
npx vue-tsc --noEmit
```

Expected: 无类型错误。

- [ ] **Step 6: Commit**

```bash
git add frontend/src
# .gitignore node_modules if not already ignored
git commit -m "feat(frontend): add Pinia stores, API client, router and App shell"
```

---

### Task 12: 实现项目列表组件

**Files:**
- Create: `frontend/src/components/ProjectList.vue`
- Create: `frontend/src/stores/__tests__/project.spec.ts`

- [ ] **Step 1: 写 store 单元测试**

Create `frontend/src/stores/__tests__/project.spec.ts`:

```typescript
import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useProjectStore } from '../project'
import * as api from '@/api/projects'

vi.mock('@/api/projects')

describe('project store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('loads projects', async () => {
    vi.mocked(api.listProjects).mockResolvedValue([{ id: '1', name: 'p1', path: '/p1' } as any])
    const store = useProjectStore()
    await store.loadProjects()
    expect(store.projects).toHaveLength(1)
    expect(store.projects[0].name).toBe('p1')
  })

  it('selects project and updates currentConfig', async () => {
    vi.mocked(api.getProject).mockResolvedValue({
      id: '1',
      name: 'p1',
      analysis: { image_dir: '/img', clinical_path: '/clin.csv' },
    } as any)
    const store = useProjectStore()
    await store.selectProject('1')
    expect(store.currentConfig.image_dir).toBe('/img')
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

Run:
```bash
cd frontend
npx vitest run src/stores/__tests__/project.spec.ts
```

Expected: 测试失败，因为 `vitest` 配置尚未创建。

- [ ] **Step 3: 创建 Vitest 配置**

Create `frontend/vitest.config.ts`:

```typescript
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'jsdom',
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
})
```

Add test script if not present in `package.json`:
```json
"test": "vitest"
```

- [ ] **Step 4: 实现 ProjectList.vue**

Create `frontend/src/components/ProjectList.vue`:

```vue
<template>
  <div class="project-list">
    <div class="project-list-header">
      <span>项目</span>
      <el-button size="small" @click="showCreate = true">+ 新建项目</el-button>
    </div>

    <el-dialog v-model="showCreate" title="新建项目" width="400px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="newName" />
        </el-form-item>
        <el-form-item label="目录路径">
          <el-input v-model="newPath" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="newDescription" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-empty v-if="!projectStore.projects.length" description="暂无项目" />
    <div
      v-for="p in projectStore.projects"
      :key="p.id"
      class="project-item"
      :class="{ active: projectStore.currentProject?.id === p.id }"
      @click="projectStore.selectProject(p.id)"
    >
      <span class="project-name">{{ p.name }}</span>
      <el-button link type="danger" size="small" @click.stop="projectStore.deleteProject(p.id)">删除</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useProjectStore } from '@/stores/project'

const projectStore = useProjectStore()

const showCreate = ref(false)
const newName = ref('')
const newPath = ref('')
const newDescription = ref('')

async function handleCreate() {
  await projectStore.createProject({
    name: newName.value,
    path: newPath.value,
    description: newDescription.value,
  })
  showCreate.value = false
  newName.value = ''
  newPath.value = ''
  newDescription.value = ''
}

onMounted(() => {
  projectStore.loadProjects()
})
</script>

<style scoped>
.project-list-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; font-weight: 600; }
.project-item { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 6px; background: #f9fafb; }
.project-item:hover { background: #f3f4f6; }
.project-item.active { background: #2563eb; color: #fff; }
.project-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
```

- [ ] **Step 5: 运行测试**

Run:
```bash
cd frontend
npx vitest run src/stores/__tests__/project.spec.ts
```

Expected: 2 个测试通过。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ProjectList.vue frontend/src/stores/__tests__/project.spec.ts frontend/vitest.config.ts frontend/package.json
git commit -m "feat(frontend): add ProjectList component and project store tests"
```

---

### Task 13: 实现影像组学分析视图

**Files:**
- Create: `frontend/src/components/AnalysisForm.vue`
- Create: `frontend/src/components/LogViewer.vue`
- Create: `frontend/src/views/AnalysisView.vue`

- [ ] **Step 1: 创建 AnalysisForm.vue**

Create `frontend/src/components/AnalysisForm.vue`:

```vue
<template>
  <el-form :model="config" label-width="120px" class="analysis-form">
    <div class="section-title">数据源</div>
    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="影像文件夹">
          <el-input v-model="config.image_dir" placeholder="/path/to/images" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="临床表格">
          <el-input v-model="config.clinical_path" placeholder="/path/to/clinical.csv" />
        </el-form-item>
      </el-col>
    </el-row>

    <div class="section-title">分析配置</div>
    <el-row :gutter="16">
      <el-col :span="8">
        <el-form-item label="输出目录">
          <el-input v-model="config.output_dir" />
        </el-form-item>
      </el-col>
      <el-col :span="8">
        <el-form-item label="模态">
          <el-select v-model="config.modality">
            <el-option label="自动" value="auto" />
            <el-option label="CT" value="CT" />
            <el-option label="MRI" value="MRI" />
          </el-select>
        </el-form-item>
      </el-col>
      <el-col :span="8">
        <el-form-item label="协变量">
          <el-input v-model="config.covariates" placeholder="age,sex" />
        </el-form-item>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="LASSO 最大特征">
          <el-input-number v-model="config.max_lasso_features" :min="1" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="交叉验证折数">
          <el-input-number v-model="config.n_splits" :min="2" />
        </el-form-item>
      </el-col>
    </el-row>

    <div class="section-title">AI 模型配置</div>
    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="API Key">
          <el-input v-model="config.api_key" type="password" show-password />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="模型">
          <el-select v-model="config.model">
            <el-option label="deepseek-v4-pro" value="deepseek-v4-pro" />
            <el-option label="deepseek-v4-flash" value="deepseek-v4-flash" />
          </el-select>
        </el-form-item>
      </el-col>
    </el-row>

    <el-form-item>
      <el-button @click="emit('save')">保存配置</el-button>
      <el-button type="primary" :loading="running" @click="emit('run')">运行分析</el-button>
    </el-form-item>
  </el-form>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AnalysisConfig } from '@/api/projects'

const props = defineProps<{
  modelValue: AnalysisConfig
  running: boolean
}>()

const emit = defineEmits<['update:modelValue', 'save', 'run']>()

const config = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})
</script>

<style scoped>
.section-title { font-weight: 700; margin: 20px 0 12px; color: #1f2937; }
</style>
```

- [ ] **Step 2: 创建 LogViewer.vue**

Create `frontend/src/components/LogViewer.vue`:

```vue
<template>
  <div class="log-viewer">
    <div class="section-title">运行日志</div>
    <pre class="log-content">{{ logs }}</pre>
    <div v-if="reportUrl" class="report-link">
      <a :href="reportUrl" target="_blank">下载报告</a>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  logs: string
  reportUrl?: string
}>()
</script>

<style scoped>
.log-content { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; min-height: 200px; max-height: 400px; overflow-y: auto; font-family: monospace; font-size: 13px; white-space: pre-wrap; }
.report-link { margin-top: 12px; }
</style>
```

- [ ] **Step 3: 创建 AnalysisView.vue**

Create `frontend/src/views/AnalysisView.vue`:

```vue
<template>
  <div class="analysis-view">
    <h2>当前项目: {{ projectStore.currentProject?.name || '未选择' }}</h2>
    <AnalysisForm
      v-model="config"
      :running="runStore.running"
      @save="handleSave"
      @run="handleRun"
    />
    <LogViewer :logs="runStore.logs" :report-url="runStore.reportUrl" />
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useProjectStore } from '@/stores/project'
import { useRunStore } from '@/stores/run'
import AnalysisForm from '@/components/AnalysisForm.vue'
import LogViewer from '@/components/LogViewer.vue'
import type { AnalysisConfig } from '@/api/projects'

const projectStore = useProjectStore()
const runStore = useRunStore()

const config = ref<AnalysisConfig>(projectStore.currentConfig)

watch(
  () => projectStore.currentConfig,
  (v) => {
    config.value = { ...v }
  },
  { deep: true }
)

async function handleSave() {
  await projectStore.saveConfig(config.value)
}

async function handleRun() {
  if (!projectStore.currentProject) return
  await projectStore.saveConfig(config.value)
  await runStore.startRun(projectStore.currentProject.id, config.value)
}
</script>

<style scoped>
.analysis-view { max-width: 1200px; }
</style>
```

- [ ] **Step 4: 类型检查**

Run:
```bash
cd frontend
npx vue-tsc --noEmit
```

Expected: 无错误。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AnalysisForm.vue frontend/src/components/LogViewer.vue frontend/src/views/AnalysisView.vue
git commit -m "feat(frontend): add analysis form, log viewer and view"
```

---

### Task 14: 实现 AI Agent 视图

**Files:**
- Create: `frontend/src/components/AgentChat.vue`
- Create: `frontend/src/components/PlanPanel.vue`
- Create: `frontend/src/components/CommandPanel.vue`
- Create: `frontend/src/components/ScriptPanel.vue`
- Create: `frontend/src/views/AgentView.vue`

- [ ] **Step 1: 创建 PlanPanel.vue**

Create `frontend/src/components/PlanPanel.vue`:

```vue
<template>
  <el-card class="interrupt-panel">
    <template #header>
      <span>待确认的文件操作计划</span>
    </template>
    <el-table :data="localPlan" border style="width: 100%">
      <el-table-column prop="action" label="action">
        <template #default="{ row }">
          <el-input v-model="row.action" />
        </template>
      </el-table-column>
      <el-table-column prop="source" label="source">
        <template #default="{ row }">
          <el-input v-model="row.source" />
        </template>
      </el-table-column>
      <el-table-column prop="target" label="target">
        <template #default="{ row }">
          <el-input v-model="row.target" />
        </template>
      </el-table-column>
      <el-table-column prop="reason" label="reason">
        <template #default="{ row }">
          <el-input v-model="row.reason" />
        </template>
      </el-table-column>
    </el-table>
    <div class="panel-actions">
      <el-button type="primary" @click="emit('confirm', localPlan)">确认执行</el-button>
      <el-button @click="emit('cancel')">取消</el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  plan: any[]
}>()

const emit = defineEmits<['confirm', 'cancel']>()

const localPlan = ref<any[]>([])

watch(
  () => props.plan,
  (v) => {
    localPlan.value = v.map((item) => ({ ...item }))
  },
  { immediate: true, deep: true }
)
</script>

<style scoped>
.interrupt-panel { margin-top: 16px; }
.panel-actions { margin-top: 12px; display: flex; gap: 8px; }
</style>
```

- [ ] **Step 2: 创建 CommandPanel.vue**

Create `frontend/src/components/CommandPanel.vue`:

```vue
<template>
  <el-card class="interrupt-panel">
    <template #header>
      <span>待确认的系统命令</span>
    </template>
    <pre class="code-block">{{ JSON.stringify(command, null, 2) }}</pre>
    <div class="panel-actions">
      <el-button type="primary" @click="emit('confirm')">确认</el-button>
      <el-button @click="emit('cancel')">取消</el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  command: any
}>()

const emit = defineEmits<['confirm', 'cancel']>()
</script>

<style scoped>
.code-block { background: #f9fafb; padding: 12px; border-radius: 8px; font-family: monospace; }
</style>
```

- [ ] **Step 3: 创建 ScriptPanel.vue**

Create `frontend/src/components/ScriptPanel.vue`:

```vue
<template>
  <el-card class="interrupt-panel">
    <template #header>
      <span>待确认的 Python 脚本</span>
    </template>
    <pre class="code-block">{{ script?.code || script?.script_path || '无内容' }}</pre>
    <div class="panel-actions">
      <el-button type="primary" @click="emit('confirm')">确认执行</el-button>
      <el-button @click="emit('cancel')">取消</el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
defineProps<{
  script: any
}>()

const emit = defineEmits<['confirm', 'cancel']>()
</script>
```

- [ ] **Step 4: 创建 AgentChat.vue**

Create `frontend/src/components/AgentChat.vue`:

```vue
<template>
  <div class="agent-chat">
    <div class="messages">
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        class="message"
        :class="msg.role"
      >
        <div class="bubble">{{ msg.content }}</div>
      </div>
    </div>
    <div class="input-row">
      <el-input
        v-model="input"
        type="textarea"
        :rows="2"
        placeholder="输入需求，按 Enter 发送"
        @keydown.enter.exact.prevent="send"
      />
      <el-button type="primary" @click="send">发送</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { AgentMessage } from '@/stores/agent'

const props = defineProps<{
  messages: AgentMessage[]
}>()

const emit = defineEmits<['send']>()

const input = ref('')

function send() {
  if (!input.value.trim()) return
  emit('send', input.value.trim())
  input.value = ''
}
</script>

<style scoped>
.agent-chat { display: flex; flex-direction: column; height: 100%; }
.messages { flex: 1; overflow-y: auto; padding: 12px; background: #f9fafb; border-radius: 8px; }
.message { margin-bottom: 12px; display: flex; }
.message.user { justify-content: flex-end; }
.bubble { max-width: 70%; padding: 10px 14px; border-radius: 12px; background: #fff; border: 1px solid #e5e7eb; }
.message.user .bubble { background: #2563eb; color: #fff; }
.input-row { display: flex; gap: 8px; margin-top: 12px; }
</style>
```

- [ ] **Step 5: 创建 AgentView.vue**

Create `frontend/src/views/AgentView.vue`:

```vue
<template>
  <div class="agent-view">
    <h2>AI Agent</h2>
    <AgentChat :messages="agentStore.messages" @send="handleSend" />
    <PlanPanel
      v-if="agentStore.interrupt?.interrupt_type === 'file_plan'"
      :plan="agentStore.interrupt.pending_plan?.plan || []"
      @confirm="handleConfirmPlan"
      @cancel="agentStore.cancel"
    />
    <CommandPanel
      v-else-if="agentStore.interrupt?.interrupt_type === 'system_command'"
      :command="agentStore.interrupt.pending_command"
      @confirm="agentStore.confirm"
      @cancel="agentStore.cancel"
    />
    <ScriptPanel
      v-else-if="agentStore.interrupt?.interrupt_type === 'python_script'"
      :script="agentStore.interrupt.pending_script"
      @confirm="agentStore.confirm"
      @cancel="agentStore.cancel"
    />
    <div v-if="agentStore.operationLog.length" class="operation-log">
      <div class="section-title">操作日志</div>
      <pre>{{ agentStore.operationLog.join('\n') }}</pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useProjectStore } from '@/stores/project'
import { useAgentStore } from '@/stores/agent'
import AgentChat from '@/components/AgentChat.vue'
import PlanPanel from '@/components/PlanPanel.vue'
import CommandPanel from '@/components/CommandPanel.vue'
import ScriptPanel from '@/components/ScriptPanel.vue'

const projectStore = useProjectStore()
const agentStore = useAgentStore()

async function handleSend(content: string) {
  if (!projectStore.currentProject) return
  await agentStore.sendMessage(projectStore.currentProject.id, content)
}

async function handleConfirmPlan(plan: any[]) {
  await agentStore.updatePlan(plan)
  await agentStore.confirm()
}
</script>

<style scoped>
.agent-view { display: flex; flex-direction: column; height: 100%; max-width: 1200px; }
.operation-log { margin-top: 16px; }
.operation-log pre { background: #f9fafb; padding: 12px; border-radius: 8px; font-family: monospace; }
</style>
```

- [ ] **Step 6: 类型检查与构建**

Run:
```bash
cd frontend
npx vue-tsc --noEmit
npm run build
```

Expected: 构建成功，生成 `frontend/dist`。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/AgentChat.vue frontend/src/components/PlanPanel.vue frontend/src/components/CommandPanel.vue frontend/src/components/ScriptPanel.vue frontend/src/views/AgentView.vue
git commit -m "feat(frontend): add AI Agent chat and approval panels"
```

---

## Phase 5: Docker、文档与集成测试

### Task 15: 更新 Dockerfile 与 docker-compose

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`

- [ ] **Step 1: 更新 Dockerfile**

Create/overwrite `Dockerfile`:

```dockerfile
# ---------- Build frontend ----------
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# ---------- Python backend ----------
FROM python:3.11-slim AS backend

WORKDIR /app

# Install build dependencies for pyradiomics
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy pyradiomics source if present
COPY pyradiomics-master/ ./pyradiomics-master/
RUN if [ -d "pyradiomics-master/pyradiomics-master" ]; then \
      pip install ./pyradiomics-master/pyradiomics-master --no-cache-dir; \
    fi

COPY requirements.txt ./
RUN pip install -r requirements.txt --no-cache-dir

COPY app/ ./app/
COPY main.py ./
COPY config/ ./config/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: 更新 docker-compose.yml**

Create/overwrite `docker-compose.yml`:

```yaml
version: '3.8'

services:
  onerad:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - BASE_URL=${BASE_URL:-https://api.deepseek.com/v1}
      - MODEL=${MODEL:-deepseek-v4-pro}
    volumes:
      - ./data:/data
      - ./output:/app/output
```

- [ ] **Step 3: 本地构建验证**

Run:
```bash
docker build -t onerad:test .
```

Expected: 构建成功。

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "build: add Node build stage and serve Vue via FastAPI in Docker"
```

---

### Task 16: 更新 README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 修改运行说明**

替换 UI 启动部分为：

```markdown
### Web UI

```bash
python main.py
```

启动后访问 http://localhost:8000。

开发模式（前后端热更新）：

```bash
# 终端 1
python main.py --port 8000

# 终端 2
cd frontend
npm run dev
```

前端 dev server 默认代理 `/api` 到 `http://localhost:8000`。

### Docker

```bash
export DEEPSEEK_API_KEY=your_key
docker-compose up --build
```

访问 http://localhost:8000。
```

- [ ] **Step 2: 更新测试说明**

替换测试部分为：

```markdown
## 测试

```bash
# 后端
pytest tests/

# 前端
cd frontend
npm test
```
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for Vue + FastAPI startup"
```

---

### Task 17: 端到端冒烟测试

**Files:**
- None（手动验证）

- [ ] **Step 1: 启动后端**

Run:
```bash
python main.py --port 8000
```

Expected: uvicorn 启动，监听 `0.0.0.0:8000`。

- [ ] **Step 2: 验证前端构建产物可被托管**

确保 `frontend/dist` 已生成。访问 http://localhost:8000/ 。

Expected: 看到 OneRad 页面（项目侧边栏 + 分析视图）。

- [ ] **Step 3: 验证项目 CRUD**

通过 UI 创建项目，然后调用 API：

```bash
curl http://localhost:8000/api/projects
```

Expected: 返回创建的项目列表。

- [ ] **Step 4: 验证 SSE 流水线（可选，需要真实数据）**

选择一个有影像和临床数据的项目，点击运行分析，观察日志区是否有事件推送。

- [ ] **Step 5: 验证 Agent 聊天**

进入 AI Agent 页，发送消息，确认能收到回复或中断面板。

---

## 自我审查

### 1. Spec 覆盖检查

| Spec 章节 | 对应任务 |
| --- | --- |
| 架构/目录结构 | Task 4, 10 |
| 项目 CRUD API | Task 5 |
| 运行/SSE | Task 2, 3, 6 |
| Agent API + AsyncSqliteSaver | Task 7 |
| 前端路由/store | Task 10, 11 |
| 前端组件 | Task 12, 13, 14 |
| main.py 启动 | Task 8 |
| 删除 Gradio | Task 9 |
| Docker/README | Task 15, 16 |
| 测试 | 各 Task 中的测试步骤 |

### 2. Placeholder 扫描

- 无 TBD/TODO。
- 所有 API 路由、文件路径、函数签名已明确。
- 前端组件代码为完整可运行示例。

### 3. 类型一致性检查

- `AnalysisConfig` 在 `frontend/src/api/projects.ts` 定义，被 `project.ts`、`run.ts`、`AnalysisForm.vue`、`AnalysisView.vue` 复用。
- `ProjectStore.get_run` 在 Task 6 添加，与 `app/api/runs.py` 调用一致。
- `AsyncSqliteSaver` 依赖注入在 `deps.py` 和 `agent.py` 中一致使用。

### 4. 风险缓解

- 同步流水线通过 `run_in_threadpool` 运行，不阻塞事件循环。
- SSE 队列在连接断开时通过 `unsubscribe` 清理。
- `AsyncSqliteSaver` 使用 `aiosqlite`，避免同步 sqlite3 在 ASGI 中锁竞争。
- 运行按钮前端 disabled + 后端 409 双重幂等。

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-09-onerad-vue-fastapi-refactor-plan.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach would you like?
