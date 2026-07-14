# 按项目历史对话检索与重新加载功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每个项目实现可列出、加载、新建、删除（带二次确认）的历史 Agent 会话功能，并能在加载时恢复完整对话状态。

**Architecture:** 后端在 `projects.db` 新增 `threads` 元数据表，会话状态继续由 `AsyncSqliteSaver` 持久化；前端在 `/agent` 视图左侧新增 `ThreadList` 面板，通过新增 API 管理会话生命周期。

**Tech Stack:** Python 3.11、FastAPI、LangGraph、AsyncSqliteSaver、Vue 3、Pinia、Element Plus、Vitest

---

## 文件结构

| 文件 | 用途 |
|------|------|
| `app/projects.py` | 新增 `threads` 表及 CRUD 方法 |
| `app/api/agent.py` | 新增会话列表/删除/重命名/恢复端点；改造创建、发送消息逻辑 |
| `frontend/src/api/agent.ts` | 新增 `ThreadSummary`、`LoadThreadRequest` 及 API 函数 |
| `frontend/src/stores/agent.ts` | 新增 `threads`、`currentThread` 状态及管理方法 |
| `frontend/src/components/ThreadList.vue` | 新增会话列表面板组件 |
| `frontend/src/views/AgentView.vue` | 集成 `ThreadList`，处理项目切换自动加载 |
| `tests/test_api_agent.py` | 新增后端接口测试 |
| `frontend/src/components/__tests__/ThreadList.spec.ts` | 新增前端组件测试 |
| `frontend/src/stores/__tests__/agent.spec.ts` | 更新 store 测试 |

---

## Task 1: ProjectStore 支持 threads 表

**Files:**
- Modify: `app/projects.py`
- Test: `tests/test_projects.py`

- [ ] **Step 1: 在 `_init_db` 中新增 `threads` 表**

在 `app/projects.py` 的 `_init_db` 方法里，在 `sse_events` 表创建之后新增：

```python
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT,
                    llm_model TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                )
                """
            )
```

- [ ] **Step 2: 新增 threads 相关操作方法**

在 `ProjectStore` 类中新增以下方法（放在 `delete_project` 之后即可）：

```python
    def record_thread(
        self, project_id: str, thread_id: str, title: str, llm_model: str
    ) -> Dict[str, Any]:
        now = self._now()
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """
                INSERT INTO threads (id, project_id, title, llm_model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (thread_id, project_id, title or "", llm_model, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_thread_meta(thread_id)

    def list_threads(self, project_id: str) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, project_id, title, llm_model, created_at, updated_at
                FROM threads WHERE project_id = ? ORDER BY updated_at DESC
                """,
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_thread_meta(self, thread_id: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, project_id, title, llm_model, created_at, updated_at
                FROM threads WHERE id = ?
                """,
                (thread_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_thread_title(self, thread_id: str, title: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("UPDATE threads SET title = ? WHERE id = ?", (title, thread_id))
            conn.commit()
        finally:
            conn.close()
        return self.get_thread_meta(thread_id)

    def update_thread_timestamp(self, thread_id: str) -> None:
        now = self._now()
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id)
            )
            conn.commit()
        finally:
            conn.close()

    def delete_thread(self, thread_id: str) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
            conn.execute(
                "DELETE FROM sse_events WHERE scope = ? AND scope_id = ?",
                ("agent", thread_id),
            )
            conn.commit()
        finally:
            conn.close()
```

- [ ] **Step 3: 编写 ProjectStore 单元测试**

在 `tests/test_projects.py` 新增：

```python
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
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_projects.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/projects.py tests/test_projects.py
git commit -m "feat(store): add threads table and CRUD methods"
```

---

## Task 2: 后端新增会话列表/删除/重命名/恢复端点

**Files:**
- Modify: `app/api/agent.py`
- Test: `tests/test_api_agent.py`

- [ ] **Step 1: 新增请求模型与 imports**

在 `app/api/agent.py` 顶部 `UpdatePlanRequest` 之后新增：

```python
class ThreadPatchRequest(BaseModel):
    """Request body for renaming a thread."""

    title: str


class LoadThreadRequest(BaseModel):
    """Request body for resuming an existing thread."""

    api_key: str = ""
    llm_model: Literal["deepseek-v4-pro", "deepseek-v4-flash"] = "deepseek-v4-pro"
```

- [ ] **Step 2: 改造 `_agent_config` 支持模型回退**

把现有的 `_agent_config` 替换为：

```python
def _agent_config(thread_id: str, app) -> Dict[str, Any]:
    """Build the RunnableConfig for a thread.

    api_key and llm_model are normally set when the thread is created or
    resumed. If the server has restarted, fall back to the model stored in the
    threads table.
    """
    api_key = getattr(app.state, "agent_api_keys", {}).get(thread_id, "")
    llm_model = getattr(app.state, "agent_llm_models", {}).get(
        thread_id, ""
    )
    if not llm_model:
        store = getattr(app.state, "project_store", None)
        if store is not None:
            meta = store.get_thread_meta(thread_id)
            llm_model = meta.get("llm_model", "deepseek-v4-pro") if meta else "deepseek-v4-pro"
    return {
        "configurable": {
            "thread_id": thread_id,
            "api_key": api_key,
            "llm_model": llm_model,
        }
    }
```

- [ ] **Step 3: 新增列表、删除、重命名端点**

在 `get_thread` 之后、`send_message` 之前新增：

```python
@router.get("/threads", response_model=Dict[str, Any])
async def list_threads(
    project_id: str = Query(..., description="Project to list threads for"),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Return all threads belonging to a project."""
    return {"threads": store.list_threads(project_id)}


@router.delete(
    "/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_thread(
    thread_id: str,
    request: Request,
    graph=Depends(get_agent_graph),
    store: ProjectStore = Depends(get_project_store),
) -> None:
    """Delete a thread and all associated checkpoints/events."""
    if store.get_thread_meta(thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    checkpointer = request.app.state.checkpointer
    await checkpointer.adelete_thread(thread_id)
    store.delete_thread(thread_id)
    request.app.state.agent_api_keys.pop(thread_id, None)
    request.app.state.agent_llm_models.pop(thread_id, None)
    return None


@router.patch("/threads/{thread_id}", response_model=Dict[str, Any])
async def patch_thread(
    thread_id: str,
    payload: ThreadPatchRequest,
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Rename a thread."""
    if store.get_thread_meta(thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    updated = store.update_thread_title(thread_id, payload.title)
    return {"thread": updated}
```

- [ ] **Step 4: 新增恢复端点**

在 `patch_thread` 之后、`send_message` 之前新增：

```python
@router.post("/threads/{thread_id}/resume", response_model=Dict[str, Any])
async def resume_thread(
    request: Request,
    thread_id: str,
    payload: LoadThreadRequest,
    graph=Depends(get_agent_graph),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Resume an existing thread, refreshing api_key/llm_model in memory."""
    if store.get_thread_meta(thread_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )
    request.app.state.agent_api_keys[thread_id] = payload.api_key
    request.app.state.agent_llm_models[thread_id] = payload.llm_model
    snapshot = await graph.aget_state(_agent_config(thread_id, request.app))
    payload_out = _sync_payload(snapshot.values)
    payload_out["thread_id"] = thread_id
    return payload_out
```

- [ ] **Step 5: 编写接口测试**

在 `tests/test_api_agent.py` 新增辅助函数与测试：

```python
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
```

- [ ] **Step 6: 运行测试**

Run: `pytest tests/test_api_agent.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/api/agent.py tests/test_api_agent.py
git commit -m "feat(api): add thread list, delete, rename and resume endpoints"
```

---

## Task 3: 改造创建线程和发送消息，写入/更新 threads 元数据

**Files:**
- Modify: `app/api/agent.py`
- Test: `tests/test_api_agent.py`

- [ ] **Step 1: `create_thread` 写入 threads 表**

把 `create_thread` 函数签名和 body 改为接收 `store` 依赖，并在创建后记录：

```python
@router.post("/threads", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
async def create_thread(
    request: Request,
    payload: Optional[CreateThreadRequest] = None,
    project_id: str = Query(..., description="Project to associate with the new thread"),
    graph=Depends(get_agent_graph),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Create a new agent thread and seed it with the project's initial state."""
    project = store.load_project(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在"
        )

    payload = payload or CreateThreadRequest()
    thread_id = str(uuid.uuid4())
    api_key = payload.api_key
    llm_model = payload.llm_model
    request.app.state.agent_api_keys[thread_id] = api_key
    request.app.state.agent_llm_models[thread_id] = llm_model
    initial_state = build_initial_state(project, api_key=api_key, llm_model=llm_model)
    await graph.aupdate_state(_agent_config(thread_id, request.app), initial_state)
    store.record_thread(project_id, thread_id, title="", llm_model=llm_model)
    return {"thread_id": thread_id}
```

- [ ] **Step 2: `send_message` 更新元数据并回填标题**

把 `send_message` 函数签名改为接收 `store` 依赖，并在发送消息后更新：

```python
@router.post(
    "/threads/{thread_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Dict[str, Any],
)
async def send_message(
    thread_id: str,
    payload: MessageRequest,
    request: Request,
    graph=Depends(get_agent_graph),
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Append a user message to a thread and start streaming the agent response."""
    config = _agent_config(thread_id, request.app)
    try:
        await graph.aget_state(config)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="thread not found"
        )

    message = _make_message(payload.role, payload.content)
    store.update_thread_timestamp(thread_id)
    if payload.role == "user":
        meta = store.get_thread_meta(thread_id)
        if meta and not meta.get("title"):
            title = payload.content[:30] if payload.content else ""
            store.update_thread_title(thread_id, title)

    bridge = get_bridge(request)
    _start_stream(
        thread_id,
        graph,
        bridge,
        request.app,
        {"messages": [message]},
    )
    return {"thread_id": thread_id}
```

- [ ] **Step 3: 编写测试验证标题回填与时间戳更新**

在 `tests/test_api_agent.py` 新增：

```python
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
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/test_api_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/agent.py tests/test_api_agent.py
git commit -m "feat(api): record thread metadata on create and update on message"
```

---

## Task 4: 前端 API 层新增类型与函数

**Files:**
- Modify: `frontend/src/api/agent.ts`

- [ ] **Step 1: 新增类型定义**

在 `AgentEventCallbacks` 之前新增：

```typescript
export interface ThreadSummary {
  id: string
  project_id: string
  title: string
  llm_model: string
  created_at: string
  updated_at: string
}

export interface LoadThreadRequest {
  api_key: string
  llm_model: string
}
```

- [ ] **Step 2: 新增 API 函数**

在文件末尾 `connectAgentEvents` 之前新增：

```typescript
export const listThreads = async (
  projectId: string
): Promise<{ threads: ThreadSummary[] }> => {
  const res = await client.get('/agent/threads', {
    params: { project_id: projectId },
  })
  return res.data
}

export const deleteThread = async (threadId: string): Promise<void> => {
  await client.delete(`/agent/threads/${encodeURIComponent(threadId)}`)
}

export const renameThread = async (
  threadId: string,
  title: string
): Promise<{ thread: ThreadSummary }> => {
  const res = await client.patch(
    `/agent/threads/${encodeURIComponent(threadId)}`,
    { title }
  )
  return res.data
}

export const resumeThread = async (
  threadId: string,
  payload: LoadThreadRequest
): Promise<AgentState & { thread_id: string }> => {
  const res = await client.post(
    `/agent/threads/${encodeURIComponent(threadId)}/resume`,
    payload
  )
  return res.data
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/agent.ts
git commit -m "feat(api-client): add thread management endpoints"
```

---

## Task 5: 前端 agent store 增加会话管理

**Files:**
- Modify: `frontend/src/stores/agent.ts`

- [ ] **Step 1: 新增状态与 helper**

在 `useAgentStore` 内部，把现有 `let es: EventSource | null = null` 之前的状态扩展为：

```typescript
  const threads = ref<ThreadSummary[]>([])
  const currentThread = ref<ThreadSummary | null>(null)
```

并在 `applyState` 之后新增一个内部 helper：

```typescript
  function resetInternalState(): void {
    disconnect()
    threadId.value = null
    messages.value = []
    interrupt.value = null
    operationLog.value = []
    pendingPlan.value = null
    pendingCommand.value = null
    pendingScript.value = null
    currentThread.value = null
  }
```

- [ ] **Step 2: 改造 `ensureThread` 并新增线程管理方法**

把现有 `ensureThread` 替换为：

```typescript
  async function ensureThread(
    projectId: string,
    apiKey: string,
    llmModel: string
  ): Promise<string> {
    if (threadId.value) {
      return threadId.value
    }
    const { thread_id } = await api.createThread(projectId, {
      api_key: apiKey,
      llm_model: llmModel,
    })
    threadId.value = thread_id
    currentThread.value = {
      id: thread_id,
      project_id: projectId,
      title: '',
      llm_model: llmModel,
      created_at: '',
      updated_at: '',
    }
    await syncThread()
    await listThreads(projectId)
    connect()
    return thread_id
  }
```

在 `syncThread` 之后新增：

```typescript
  async function listThreads(projectId: string): Promise<void> {
    const data = await api.listThreads(projectId)
    threads.value = data.threads
  }

  async function loadThread(
    threadIdToLoad: string,
    apiKey: string,
    llmModel: string
  ): Promise<void> {
    resetInternalState()
    const state = await api.resumeThread(threadIdToLoad, {
      api_key: apiKey,
      llm_model: llmModel,
    })
    threadId.value = state.thread_id
    currentThread.value =
      threads.value.find((t) => t.id === threadIdToLoad) || null
    applyState(state)
    connect()
  }

  async function createThread(
    projectId: string,
    apiKey: string,
    llmModel: string
  ): Promise<string> {
    resetInternalState()
    const { thread_id } = await api.createThread(projectId, {
      api_key: apiKey,
      llm_model: llmModel,
    })
    threadId.value = thread_id
    currentThread.value = {
      id: thread_id,
      project_id: projectId,
      title: '',
      llm_model: llmModel,
      created_at: '',
      updated_at: '',
    }
    await listThreads(projectId)
    connect()
    return thread_id
  }

  async function deleteThread(
    threadIdToDelete: string,
    projectId: string
  ): Promise<void> {
    await api.deleteThread(threadIdToDelete)
    if (currentThread.value?.id === threadIdToDelete) {
      resetInternalState()
    }
    await listThreads(projectId)
  }

  async function renameThread(
    threadIdToRename: string,
    title: string,
    projectId: string
  ): Promise<void> {
    await api.renameThread(threadIdToRename, title)
    await listThreads(projectId)
    if (currentThread.value?.id === threadIdToRename) {
      currentThread.value.title = title
    }
  }
```

- [ ] **Step 3: 改造 `resetThread` 并导出新增状态/方法**

把 `resetThread` 替换为：

```typescript
  function resetThread(): void {
    resetInternalState()
    threads.value = []
  }
```

并把返回对象扩展为：

```typescript
  return {
    threadId,
    messages,
    interrupt,
    operationLog,
    pendingPlan,
    pendingCommand,
    pendingScript,
    threads,
    currentThread,
    ensureThread,
    reconnect,
    sendMessage,
    updatePlan,
    confirm,
    cancel,
    disconnect,
    resetThread,
    listThreads,
    loadThread,
    createThread,
    deleteThread,
    renameThread,
  }
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/agent.ts
git commit -m "feat(store): add thread list/load/create/delete/rename state"
```

---

## Task 6: 新建 ThreadList 组件

**Files:**
- Create: `frontend/src/components/ThreadList.vue`

- [ ] **Step 1: 创建组件文件**

```vue
<template>
  <div class="thread-list">
    <div class="thread-list-header">
      <span class="thread-list-title">历史会话</span>
      <el-button
        type="primary"
        size="small"
        :icon="Plus"
        @click="handleCreate"
      >
        新建对话
      </el-button>
    </div>

    <div v-if="threads.length === 0" class="thread-list-empty">
      <el-empty description="暂无历史会话" :image-size="60" />
    </div>

    <ul v-else class="thread-list-items">
      <li
        v-for="thread in threads"
        :key="thread.id"
        :class="['thread-item', { 'thread-item--active': currentThreadId === thread.id }]"
        @click="handleSelect(thread.id)"
      >
        <div class="thread-item-content">
          <el-icon class="thread-item-icon"><ChatDotRound /></el-icon>
          <span class="thread-item-title">{{ thread.title || '未命名会话' }}</span>
        </div>
        <div class="thread-item-actions">
          <el-button
            link
            size="small"
            :icon="Edit"
            @click.stop="handleRename(thread)"
          />
          <el-button
            link
            size="small"
            type="danger"
            :icon="Delete"
            @click.stop="handleDelete(thread)"
          />
        </div>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { Plus, Edit, Delete, ChatDotRound } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import type { ThreadSummary } from '@/api/agent'

const props = defineProps<{
  threads: ThreadSummary[]
  currentThreadId: string | null
}>()

const emit = defineEmits<{
  select: [threadId: string]
  create: []
  rename: [threadId: string, title: string]
  delete: [threadId: string]
}>()

function handleSelect(threadId: string): void {
  emit('select', threadId)
}

function handleCreate(): void {
  emit('create')
}

async function handleRename(thread: ThreadSummary): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('请输入新标题', '重命名会话', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: thread.title || '未命名会话',
      inputValidator: (value) => {
        if (!value || value.trim() === '') {
          return '标题不能为空'
        }
        return true
      },
    })
    emit('rename', thread.id, value.trim())
  } catch {
    // user cancelled
  }
}

async function handleDelete(thread: ThreadSummary): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定要删除会话 "${thread.title || '未命名会话'}" 吗？删除后无法恢复。`,
      '删除会话',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    emit('delete', thread.id)
  } catch {
    // user cancelled
  }
}
</script>

<style scoped>
.thread-list {
  display: flex;
  flex-direction: column;
  width: 240px;
  height: 100%;
  border-right: 1px solid #e4e7ed;
  background-color: #f5f7fa;
}

.thread-list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e4e7ed;
}

.thread-list-title {
  font-weight: 600;
  color: #303133;
}

.thread-list-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.thread-list-items {
  flex: 1;
  overflow-y: auto;
  list-style: none;
  margin: 0;
  padding: 0.5rem 0;
}

.thread-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  margin: 0 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.thread-item:hover,
.thread-item--active {
  background-color: #e6f2ff;
}

.thread-item-content {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  overflow: hidden;
}

.thread-item-icon {
  flex-shrink: 0;
  color: #909399;
}

.thread-item-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #303133;
  font-size: 0.875rem;
}

.thread-item-actions {
  display: flex;
  gap: 0.25rem;
  opacity: 0;
  transition: opacity 0.2s;
}

.thread-item:hover .thread-item-actions {
  opacity: 1;
}
</style>
```

注意：列表渲染顺序直接使用后端按 `updated_at` 倒序返回的数组。

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ThreadList.vue
git commit -m "feat(ui): add ThreadList component with rename and confirm delete"
```

---

## Task 7: 在 AgentView 中集成 ThreadList

**Files:**
- Modify: `frontend/src/views/AgentView.vue`

- [ ] **Step 1: 引入 ThreadList 并调整布局**

`<script setup>` 中新增 import：

```typescript
import ThreadList from '@/components/ThreadList.vue'
```

`<template>` 中把 `agent-workspace` 内容改为：

```vue
    <div class="agent-workspace">
      <ThreadList
        :threads="agentStore.threads"
        :current-thread-id="agentStore.currentThread?.id ?? null"
        @select="handleSelectThread"
        @create="handleCreateThread"
        @rename="handleRenameThread"
        @delete="handleDeleteThread"
      />
      <div class="agent-chat-wrapper">
        <AgentChat
          ref="agentChatRef"
          @update:model="selectedModel = $event"
          @send-message="handleSendMessage"
        />
      </div>
      <div class="agent-side-panel">
        ...
      </div>
    </div>
```

- [ ] **Step 2: 新增事件处理函数**

在 `handleSendMessage` 之后新增：

```typescript
async function handleSelectThread(threadId: string): Promise<void> {
  const projectId = projectStore.currentProject?.id
  const config = projectStore.currentConfig
  if (!projectId || !config) return
  if (threadId === agentStore.currentThread?.id) return
  const thread = agentStore.threads.find((t) => t.id === threadId)
  if (!thread) return
  selectedModel.value = thread.llm_model
  await agentStore.loadThread(threadId, config.api_key, thread.llm_model)
}

async function handleCreateThread(): Promise<void> {
  const projectId = projectStore.currentProject?.id
  const config = projectStore.currentConfig
  if (!projectId || !config) return
  await agentStore.createThread(projectId, config.api_key, selectedModel.value)
  agentChatRef.value?.clearInput()
}

async function handleRenameThread(threadId: string, title: string): Promise<void> {
  const projectId = projectStore.currentProject?.id
  if (!projectId) return
  await agentStore.renameThread(threadId, title, projectId)
}

async function handleDeleteThread(threadId: string): Promise<void> {
  const projectId = projectStore.currentProject?.id
  if (!projectId) return
  await agentStore.deleteThread(threadId, projectId)
}
```

注意：历史会话的 LLM 模型以该会话自身保存的 `llm_model` 为准，并同步更新界面上的模型选择器。

- [ ] **Step 3: 改造项目切换 watcher**

把现有的 `watch` 替换为：

```typescript
watch(
  () => projectStore.currentProject?.id,
  async (newId, oldId) => {
    if (newId !== oldId) {
      agentStore.resetThread()
      if (newId) {
        await agentStore.listThreads(newId)
        if (agentStore.threads.length > 0) {
          const config = projectStore.currentConfig
          if (config) {
            const latest = agentStore.threads[0]
            await agentStore.loadThread(
              latest.id,
              config.api_key,
              latest.llm_model
            )
            selectedModel.value = latest.llm_model
          }
        }
      }
    }
  },
  { immediate: true }
)
```

- [ ] **Step 4: 调整 onMounted/onUnmounted**

把 `onMounted` 改为：

```typescript
onMounted(() => {
  // 项目切换 watcher 已设置 immediate: true，首次加载会自动处理。
})
```

`onUnmounted` 保持：

```typescript
onUnmounted(() => {
  agentStore.disconnect()
})
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/AgentView.vue
git commit -m "feat(ui): integrate ThreadList into AgentView"
```

---

## Task 8: 前端测试

**Files:**
- Create: `frontend/src/components/__tests__/ThreadList.spec.ts`
- Modify: `frontend/src/stores/__tests__/agent.spec.ts`

- [ ] **Step 1: 编写 ThreadList 组件测试**

```typescript
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import ThreadList from '@/components/ThreadList.vue'
import { ElMessageBox } from 'element-plus'

vi.mock('element-plus', async () => {
  const actual = await vi.importActual('element-plus')
  return {
    ...actual,
    ElMessageBox: {
      confirm: vi.fn(),
      prompt: vi.fn(),
    },
  }
})

const threads = [
  { id: 't1', project_id: 'p1', title: 'First', llm_model: 'deepseek-v4-pro', created_at: '2026-01-01', updated_at: '2026-01-02' },
  { id: 't2', project_id: 'p1', title: 'Second', llm_model: 'deepseek-v4-flash', created_at: '2026-01-01', updated_at: '2026-01-03' },
]

describe('ThreadList', () => {
  it('renders threads and highlights current', () => {
    const wrapper = mount(ThreadList, {
      props: { threads, currentThreadId: 't2' },
    })
    const items = wrapper.findAll('.thread-item')
    expect(items).toHaveLength(2)
    expect(items[1].classes()).toContain('thread-item--active')
  })

  it('emits select event on click', async () => {
    const wrapper = mount(ThreadList, { props: { threads, currentThreadId: null } })
    await wrapper.findAll('.thread-item')[0].trigger('click')
    expect(wrapper.emitted('select')).toBeTruthy()
    expect(wrapper.emitted('select')![0]).toEqual(['t1'])
  })

  it('emits create event', async () => {
    const wrapper = mount(ThreadList, { props: { threads, currentThreadId: null } })
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('create')).toBeTruthy()
  })

  it('confirms before delete', async () => {
    const wrapper = mount(ThreadList, { props: { threads, currentThreadId: null } })
    ;(ElMessageBox.confirm as any).mockResolvedValueOnce(undefined)
    await wrapper.findAll('.thread-item')[0].findAll('button')[1].trigger('click')
    await nextTick()
    expect(ElMessageBox.confirm).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 更新 agent store 测试**

在 `frontend/src/stores/__tests__/agent.spec.ts` 中，若已有测试对返回值做全等匹配，需要更新。若没有，新增：

```typescript
it('lists threads for a project', async () => {
  const store = useAgentStore()
  vi.mocked(agentApi.listThreads).mockResolvedValueOnce({ threads: [] })
  await store.listThreads('p1')
  expect(store.threads).toEqual([])
})
```

- [ ] **Step 3: 运行前端测试**

Run:
```bash
cd frontend
npm run test:unit
```
Expected: PASS（如果已有测试因新增导出失败，先修复）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/__tests__/ThreadList.spec.ts frontend/src/stores/__tests__/agent.spec.ts
git commit -m "test(frontend): add ThreadList and update agent store tests"
```

---

## Task 9: 全量测试与收尾

- [ ] **Step 1: 运行后端全量测试**

Run: `pytest tests/ -q`
Expected: PASS

- [ ] **Step 2: 运行前端构建**

Run:
```bash
cd frontend
npm run build
```
Expected: 构建成功，无 TypeScript 错误。

- [ ] **Step 3: 手动端到端验证（可选）**

1. 启动后端：`python main.py`
2. 启动前端 dev：`cd frontend && npm run dev`
3. 创建一个项目，进入 `/agent`。
4. 发送一条消息，确认左侧列表出现该会话标题。
5. 切换到分析视图再切回，确认自动恢复最近会话。
6. 点击“新建对话”，确认创建了新会话。
7. 删除会话，确认二次确认弹窗且删除后列表更新。
8. 重命名会话，确认即时生效。

- [ ] **Step 4: Commit（如做了修复）**

```bash
git add .
git commit -m "fix: address review/test issues for thread history"
```

---

## Self-Review

### Spec Coverage

- [x] 每个项目多个历史对话 → Task 1 数据表 + Task 2 list 接口
- [x] 左侧会话列表面板 → Task 6 ThreadList + Task 7 AgentView 集成
- [x] 加载历史恢复完整状态 → Task 2 resume 端点 + Task 5 store.loadThread
- [x] 新建对话 → Task 5 createThread + Task 7 handleCreateThread
- [x] 删除会话二次确认 → Task 6 中 `ElMessageBox.confirm`
- [x] 重命名 → Task 2 patch 端点 + Task 6/7 rename 逻辑
- [x] 标题自动回填 → Task 3 send_message 改造
- [x] 服务端重启后仍能加载模型 → Task 2 `_agent_config` 回退 + resume 端点

### Placeholder Scan

- 无 TBD/TODO
- 所有代码片段均为可直接使用的完整代码
- 所有命令与期望输出明确

### Type Consistency

- `ThreadSummary` 与后端返回字段一致
- `LoadThreadRequest` 与后端 `LoadThreadRequest` 一致
- `AgentState` 类型在 `api/agent.ts` 中已存在，resume 返回类型与其兼容

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-14-per-project-conversation-history-plan.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints

Which approach would you like?
