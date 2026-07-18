# 合并项目/对话侧边栏（ProjectTree）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把项目管理和历史对话两个侧边栏合并为一个"项目文件夹嵌套对话"的侧边栏，支持项目和对话重命名，视觉向 Kimi 风格看齐。

**Architecture:** 新增 `ProjectTree.vue` 替换 `ProjectList.vue`（App.vue 层）和 `ThreadList.vue`（AgentView 层）；agent store 的 threads 改为按项目分组缓存并懒加载；后端新增 `PATCH /api/projects/{id}` 改名接口。

**Tech Stack:** Vue 3 + TS + Element Plus + Pinia（前端，vitest 测试）；FastAPI + SQLite（后端，pytest 测试）。

**Spec:** `docs/superpowers/specs/2026-07-18-merged-project-thread-sidebar-design.md`

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `app/projects.py` | `ProjectStore.update_project_name()`：更新 projects 表 name/updated_at |
| `app/api/projects.py` | `PATCH /api/projects/{id}` 路由，body `{name}` |
| `frontend/src/api/projects.ts` | `renameProject(id, name)` API 函数 |
| `frontend/src/stores/project.ts` | `renameProject` action |
| `frontend/src/stores/agent.ts` | `threadsByProject` 缓存、`loadProjectThreads`、`preferredThreadId`、`selectedModel` |
| `frontend/src/components/ProjectTree.vue` | 合并侧边栏组件（项目行 + 嵌套对话行 + 新建/重命名/删除） |
| `frontend/src/styles/tokens.css` | 侧边栏 hover/active 背景令牌（浅色+深色） |
| `frontend/src/App.vue` | ProjectList → ProjectTree |
| `frontend/src/views/AgentView.vue` | 移除 ThreadList；watcher 消费 preferredThreadId；selectedModel 移到 store |

关键交互约定（各任务共用，务必一致）：

- 点击非当前项目行 = 选中该项目 + 展开；点击当前项目行 = 折叠/展开切换。
- 点击对话行：若属于当前项目，直接 `loadThread`；若属于其他项目，设置 `agentStore.preferredThreadId` 后 `selectProject`，由 AgentView 的项目切换 watcher 消费并完成加载（保证只加载一次）。
- `agentStore.listThreads(projectId)` 同步刷新 `threadsByProject[projectId]`，因此 create/rename/delete thread 后缓存自动一致。

---

### Task 1: 后端 `ProjectStore.update_project_name`

**Files:**
- Modify: `app/projects.py`（在 `update_thread_title` 方法附近新增）
- Test: `tests/test_projects.py`（注意：该文件是 CRLF 行尾，追加测试用 append 方式，不要整体重写）

- [ ] **Step 1: 写失败测试**

在 `tests/test_projects.py` 末尾追加：

```python
def test_update_project_name(temp_db):
    store, root = temp_db
    p = store.create_project("A", str(root / "a"), "")
    updated = store.update_project_name(p["id"], "B")
    assert updated["name"] == "B"
    assert store.load_project(p["id"])["name"] == "B"


def test_update_project_name_duplicate_raises(temp_db):
    store, root = temp_db
    store.create_project("A", str(root / "a"), "")
    p2 = store.create_project("B", str(root / "b"), "")
    with pytest.raises(ValueError):
        store.update_project_name(p2["id"], "A")
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_projects.py -k update_project_name -v`
Expected: FAIL（`AttributeError: 'ProjectStore' object has no attribute 'update_project_name'`）

- [ ] **Step 3: 实现**

在 `app/projects.py` 的 `update_thread_title` 方法之后插入：

```python
    def update_project_name(self, project_id: str, name: str) -> Dict[str, Any]:
        now = self._now()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
                (name, now, project_id),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"项目名已存在: {e}")
        finally:
            conn.close()
        project = self.load_project(project_id)
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")
        return project
```

说明：数据库是唯一事实源；`project.yaml` 里的 name 会在下次 `save_project_config` 时按 DB 值重写，无需在此同步。

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_projects.py -v`
Expected: 全部 PASS（含原有用例）

- [ ] **Step 5: Commit**

```bash
git add app/projects.py tests/test_projects.py
git commit -m "feat(projects): add ProjectStore.update_project_name"
```

---

### Task 2: 后端 `PATCH /api/projects/{id}` 路由

**Files:**
- Modify: `app/api/projects.py`
- Test: `tests/test_api_projects.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_api_projects.py` 末尾追加：

```python
def test_rename_project(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    response = client.patch(f"/api/projects/{project['id']}", json={"name": "B"})
    assert response.status_code == 200
    assert response.json()["name"] == "B"

    response = client.get(f"/api/projects/{project['id']}")
    assert response.json()["name"] == "B"


def test_rename_project_not_found(client):
    response = client.patch("/api/projects/non-existent-id", json={"name": "B"})
    assert response.status_code == 404


def test_rename_project_empty_name(client, temp_db):
    store, root = temp_db
    project = store.create_project("A", str(root / "a"), "")
    response = client.patch(f"/api/projects/{project['id']}", json={"name": "   "})
    assert response.status_code == 400


def test_rename_project_duplicate_name(client, temp_db):
    store, root = temp_db
    store.create_project("A", str(root / "a"), "")
    p2 = store.create_project("B", str(root / "b"), "")
    response = client.patch(f"/api/projects/{p2['id']}", json={"name": "A"})
    assert response.status_code == 400
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_api_projects.py -k rename -v`
Expected: FAIL（404/405，路由不存在）

- [ ] **Step 3: 实现**

在 `app/api/projects.py` 中：

1) `UpdateConfigRequest` 之后新增请求模型：

```python
class UpdateProjectRequest(BaseModel):
    """Request body for renaming a project."""

    name: str
```

2) `get_project` 路由之后新增路由：

```python
@router.patch("/{project_id}", response_model=Dict[str, Any])
def update_project(
    project_id: str,
    payload: UpdateProjectRequest,
    store: ProjectStore = Depends(get_project_store),
):
    """Rename a project."""
    if store.load_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="项目名不能为空"
        )
    try:
        return store.update_project_name(project_id, name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_api_projects.py tests/test_projects.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/projects.py tests/test_api_projects.py
git commit -m "feat(api): add PATCH /api/projects/{id} for renaming"
```

---

### Task 3: 前端 API 层与 project store 的 renameProject

**Files:**
- Modify: `frontend/src/api/projects.ts`
- Modify: `frontend/src/stores/project.ts`
- Test: `frontend/src/stores/__tests__/project.spec.ts`

- [ ] **Step 1: 写失败测试**

在 `frontend/src/stores/__tests__/project.spec.ts` 中：

1) 把 mock 改为（加 `renameProject`）：

```ts
vi.mock('@/api/projects', () => ({
  listProjects: vi.fn(),
  getProject: vi.fn(),
  createProject: vi.fn(),
  updateConfig: vi.fn(),
  deleteProject: vi.fn(),
  renameProject: vi.fn(),
}))
```

2) 在 `describe('useProjectStore')` 内追加：

```ts
  it('renames a project and refreshes list and current project', async () => {
    const original = mockProject('1')
    const renamed: Project = { ...original, name: 'Renamed' }
    vi.mocked(api.renameProject).mockResolvedValue(renamed)

    const store = useProjectStore()
    store.projects = [original]
    store.selectProject('1')

    await store.renameProject('1', 'Renamed')

    expect(api.renameProject).toHaveBeenCalledWith('1', 'Renamed')
    expect(store.projects[0].name).toBe('Renamed')
    expect(store.currentProject?.name).toBe('Renamed')
  })

  it('renames a non-current project without touching currentProject', async () => {
    const original = mockProject('2')
    const renamed: Project = { ...original, name: 'Renamed' }
    vi.mocked(api.renameProject).mockResolvedValue(renamed)

    const store = useProjectStore()
    store.projects = [mockProject('1'), original]
    store.selectProject('1')

    await store.renameProject('2', 'Renamed')

    expect(store.projects[1].name).toBe('Renamed')
    expect(store.currentProject?.id).toBe('1')
    expect(store.currentProject?.name).toBe('Project 1')
  })
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/stores/__tests__/project.spec.ts`
Expected: FAIL（`store.renameProject is not a function`）

- [ ] **Step 3: 实现**

1) `frontend/src/api/projects.ts` 末尾追加：

```ts
export const renameProject = async (projectId: string, name: string): Promise<Project> => {
  const res = await client.patch(`/projects/${encodeURIComponent(projectId)}`, { name })
  return res.data
}
```

2) `frontend/src/stores/project.ts`：`saveConfig` 之后新增 action，并在 return 中导出 `renameProject`：

```ts
  async function renameProject(projectId: string, name: string): Promise<Project> {
    const updated = await api.renameProject(projectId, name)
    const idx = projects.value.findIndex((p) => p.id === projectId)
    if (idx >= 0) {
      projects.value[idx] = updated
    }
    if (currentProject.value?.id === projectId) {
      currentProject.value = updated
      currentConfig.value = { ...updated.analysis }
    }
    return updated
  }
```

- [ ] **Step 4: 运行确认通过**

Run: `cd frontend && npx vitest run src/stores/__tests__/project.spec.ts`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/projects.ts frontend/src/stores/project.ts frontend/src/stores/__tests__/project.spec.ts
git commit -m "feat(frontend): add renameProject api and store action"
```

---

### Task 4: agent store — 分组缓存、preferredThreadId、selectedModel

**Files:**
- Modify: `frontend/src/stores/agent.ts`
- Test: `frontend/src/stores/__tests__/agent.spec.ts`

- [ ] **Step 1: 写失败测试**

在 `frontend/src/stores/__tests__/agent.spec.ts` 的 `'lists threads for a project'` 用例之后追加：

```ts
  it('listThreads also syncs the per-project cache', async () => {
    const store = useAgentStore()
    const thread = {
      id: 't1',
      project_id: 'p1',
      title: 'T1',
      llm_model: 'deepseek-v4-flash',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    }
    vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({ threads: [thread] })

    await store.listThreads('p1')

    expect(store.threadsByProject['p1']).toEqual([thread])
  })

  it('loadProjectThreads caches threads per project without touching current list', async () => {
    const store = useAgentStore()
    const thread = {
      id: 't2',
      project_id: 'p2',
      title: 'T2',
      llm_model: 'deepseek-v4-flash',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    }
    const spy = vi.spyOn(agentApi, 'listThreads').mockResolvedValueOnce({ threads: [thread] })

    await store.loadProjectThreads('p2')

    expect(spy).toHaveBeenCalledWith('p2')
    expect(store.threadsByProject['p2']).toEqual([thread])
    expect(store.threads).toEqual([])
  })

  it('exposes selectedModel with the default agent model', () => {
    const store = useAgentStore()
    expect(store.selectedModel).toBe(agentApi.DEFAULT_AGENT_MODEL)
    store.selectedModel = 'deepseek-v4-pro'
    expect(store.selectedModel).toBe('deepseek-v4-pro')
  })
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/stores/__tests__/agent.spec.ts`
Expected: FAIL（`store.loadProjectThreads is not a function` / `threadsByProject` undefined / `selectedModel` undefined）

- [ ] **Step 3: 实现**

在 `frontend/src/stores/agent.ts` 中：

1) 顶部 import 行加入 `DEFAULT_AGENT_MODEL`（改现有 `import type {...} from '@/api/agent'` 之外的值导入；若该文件当前只 import type，则新增一行）：

```ts
import { DEFAULT_AGENT_MODEL } from '@/api/agent'
```

2) `const threads = ref<ThreadSummary[]>([])` 之后新增状态：

```ts
  // 按项目分组的对话列表缓存，供合并侧边栏懒加载展示；
  // listThreads 会同步对应项目的缓存，保证增删改后一致。
  const threadsByProject = ref<Record<string, ThreadSummary[]>>({})
  // 期望打开的对话 id：跨项目点击对话时由侧边栏设置，
  // AgentView 的项目切换 watcher 消费后完成加载（保证只加载一次）。
  const preferredThreadId = ref<string | null>(null)
  // 对话模型选择从 AgentView 提升到 store，侧边栏切换对话时同步更新。
  const selectedModel = ref(DEFAULT_AGENT_MODEL)
```

3) `listThreads` 改为同步缓存，并新增 `loadProjectThreads`：

```ts
  async function listThreads(projectId: string): Promise<void> {
    const data = await api.listThreads(projectId)
    threads.value = data.threads ?? []
    threadsByProject.value[projectId] = threads.value
  }

  async function loadProjectThreads(projectId: string): Promise<void> {
    const data = await api.listThreads(projectId)
    threadsByProject.value[projectId] = data.threads ?? []
  }
```

4) return 中追加导出：`threadsByProject`、`preferredThreadId`、`selectedModel`、`loadProjectThreads`。

> 执行期补充（质量审查后落地）：store 另增 `threadsProjectId`（扁平列表所属项目，`listThreads` 设置、`resetThread` 清空；`renameThread`/`deleteThread` 跨项目时只刷缓存走 `loadProjectThreads`）与 `clearProjectThreads(projectId)` action（删除项目时清缓存，供 ProjectTree 调用）。

- [ ] **Step 4: 运行确认通过**

Run: `cd frontend && npx vitest run src/stores/__tests__/agent.spec.ts`
Expected: 全部 PASS（含原有用例）

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/agent.ts frontend/src/stores/__tests__/agent.spec.ts
git commit -m "feat(frontend): group threads cache by project in agent store"
```

---

### Task 5: tokens.css 侧边栏令牌

**Files:**
- Modify: `frontend/src/styles/tokens.css`

- [ ] **Step 1: 修改**

`:root` 的 `/* 背景 */` 分组内（`--app-bg-bubble` 之后）追加：

```css
  /* 侧边栏（参考 Kimi 风格：圆角行、浅灰分层） */
  --app-sidebar-hover: #f3f3f3;
  --app-sidebar-active: #e9e9e9;
```

`html.dark` 的对应位置追加：

```css
  /* 侧边栏 */
  --app-sidebar-hover: #181818;
  --app-sidebar-active: #242424;
```

- [ ] **Step 2: 验证**

Run: `cd frontend && npm run type-check`
Expected: 通过（纯 CSS，确认无意外破坏）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/styles/tokens.css
git commit -m "style(frontend): add sidebar hover/active tokens"
```

---

### Task 6: ProjectTree.vue 组件 + 测试

**Files:**
- Create: `frontend/src/components/ProjectTree.vue`
- Create: `frontend/src/components/__tests__/ProjectTree.spec.ts`
- Delete: `frontend/src/components/__tests__/ProjectList.spec.ts`
- Delete: `frontend/src/components/__tests__/ThreadList.spec.ts`

- [ ] **Step 1: 写失败测试**

创建 `frontend/src/components/__tests__/ProjectTree.spec.ts`：

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox, ElMessage, MessageBoxData, MessageHandler } from 'element-plus'
import ProjectTree from '../ProjectTree.vue'
import { useProjectStore } from '@/stores/project'
import { useAgentStore } from '@/stores/agent'
import type { Project } from '@/api/projects'
import type { ThreadSummary } from '@/api/agent'

vi.mock('@/api/projects', () => ({
  listProjects: vi.fn(),
  getProject: vi.fn(),
  createProject: vi.fn(),
  updateConfig: vi.fn(),
  deleteProject: vi.fn(),
  renameProject: vi.fn(),
}))

vi.mock('@/api/agent', () => ({
  createThread: vi.fn(),
  listThreads: vi.fn(),
  renameThread: vi.fn(),
  deleteThread: vi.fn(),
  resumeThread: vi.fn(),
  getThread: vi.fn(),
  sendMessage: vi.fn(),
  confirm: vi.fn(),
  cancel: vi.fn(),
  stopAgent: vi.fn(),
  setAutoApprove: vi.fn(),
  updatePlan: vi.fn(),
  connectAgentEvents: vi.fn(),
  DEFAULT_AGENT_MODEL: 'deepseek-v4-flash',
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ path: '/' }),
  useRouter: () => ({ push: vi.fn() }),
}))

import * as projectsApi from '@/api/projects'
import * as agentApi from '@/api/agent'

const mockAnalysis = () => ({
  image_dir: '',
  clinical_path: '',
  output_dir: './outputs',
  modality: 'auto',
  covariates: '',
  model: 'logistic',
  analysis_model: 'logistic',
  api_key: '',
})

const mockProject = (id: string): Project => ({
  id,
  name: `Project ${id}`,
  path: `/tmp/${id}`,
  description: '',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  analysis: mockAnalysis(),
})

const mockThread = (id: string, projectId: string): ThreadSummary => ({
  id,
  project_id: projectId,
  title: `Thread ${id}`,
  llm_model: 'deepseek-v4-flash',
  created_at: '2026-01-01',
  updated_at: '2026-01-02',
})

function setupWrapper() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(ProjectTree, {
    global: {
      plugins: [pinia, ElementPlus],
    },
  })
}

describe('ProjectTree', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as MessageBoxData)
    vi.spyOn(ElMessageBox, 'prompt').mockResolvedValue({ value: '新名称', action: 'confirm' } as any)
    vi.spyOn(ElMessage, 'error').mockImplementation(() => ({ close: () => {} }) as MessageHandler)
    vi.spyOn(ElMessage, 'warning').mockImplementation(() => ({ close: () => {} }) as MessageHandler)
  })

  it('renders empty state when there are no projects', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([])
    const wrapper = setupWrapper()
    await flushPromises()

    expect(wrapper.text()).toContain('暂无项目')
  })

  it('renders projects; clicking selects, expands and lazily loads threads', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1'), mockProject('2')])
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [mockThread('t1', '2')] })

    const wrapper = setupWrapper()
    await flushPromises()

    const rows = wrapper.findAll('[data-testid="project-row"]')
    expect(rows).toHaveLength(2)
    expect(wrapper.findAll('[data-testid="thread-row"]')).toHaveLength(0)

    await rows[1].trigger('click')
    await flushPromises()

    const projectStore = useProjectStore()
    expect(projectStore.currentProject?.id).toBe('2')
    expect(agentApi.listThreads).toHaveBeenCalledWith('2')
    expect(wrapper.findAll('[data-testid="thread-row"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Thread t1')
  })

  it('collapses when clicking the current expanded project', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [mockThread('t1', '1')] })

    const wrapper = setupWrapper()
    await flushPromises()

    const row = wrapper.find('[data-testid="project-row"]')
    await row.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-testid="thread-row"]')).toHaveLength(1)

    await row.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('[data-testid="thread-row"]')).toHaveLength(0)
  })

  it('loads a thread of the current project directly on click', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [mockThread('t1', '1')] })
    vi.mocked(agentApi.resumeThread).mockResolvedValue({
      thread_id: 't1',
      messages: [],
      interrupt_type: null,
      operation_log: [],
      pending_plan: null,
      pending_command: null,
      pending_script: null,
    })

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="project-row"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="thread-row"]').trigger('click')
    await flushPromises()

    expect(agentApi.resumeThread).toHaveBeenCalledWith('t1', expect.objectContaining({
      api_key: '',
      llm_model: 'deepseek-v4-flash',
    }))
    const agentStore = useAgentStore()
    expect(agentStore.preferredThreadId).toBeNull()
  })

  it('defers loading a thread of another project via preferredThreadId', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1'), mockProject('2')])
    vi.mocked(agentApi.listThreads).mockImplementation(async (projectId: string) => ({
      threads: projectId === '2' ? [mockThread('t9', '2')] : [],
    }))

    const wrapper = setupWrapper()
    await flushPromises()

    const rows = wrapper.findAll('[data-testid="project-row"]')
    await rows[0].trigger('click') // 选中并展开项目 1
    await flushPromises()
    await rows[1].trigger('click') // 选中并展开项目 2
    await flushPromises()
    await rows[0].trigger('click') // 切回项目 1（项目 2 保持展开）
    await flushPromises()

    // 此时项目 2 展开但非当前项目，点击其对话走 preferredThreadId 延迟加载
    await wrapper.find('[data-testid="thread-row"]').trigger('click')
    await flushPromises()

    const agentStore = useAgentStore()
    expect(agentStore.preferredThreadId).toBe('t9')
    expect(agentApi.resumeThread).not.toHaveBeenCalled()
    expect(useProjectStore().currentProject?.id).toBe('2')
  })

  it('renames a project via prompt', async () => {
    const project = mockProject('1')
    vi.mocked(projectsApi.listProjects).mockResolvedValue([project])
    vi.mocked(projectsApi.renameProject).mockResolvedValue({ ...project, name: '新名称' })

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="project-rename"]').trigger('click')
    await flushPromises()

    expect(ElMessageBox.prompt).toHaveBeenCalled()
    expect(projectsApi.renameProject).toHaveBeenCalledWith('1', '新名称')
  })

  it('deletes a project after confirming', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(projectsApi.deleteProject).mockResolvedValue(undefined)
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [] })

    const wrapper = setupWrapper()
    await flushPromises()

    // 点击删除前先展开项目造出缓存
    await wrapper.find('[data-testid="project-row"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-testid="project-delete"]').trigger('click')
    await flushPromises()

    expect(ElMessageBox.confirm).toHaveBeenCalled()
    expect(projectsApi.deleteProject).toHaveBeenCalledWith('1')
    const agentStore = useAgentStore()
    expect(agentStore.threadsByProject['1']).toBeUndefined()
  })

  it('renames a thread via prompt', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [mockThread('t1', '1')] })
    vi.mocked(agentApi.renameThread).mockResolvedValue({ thread: mockThread('t1', '1') })

    const wrapper = setupWrapper()
    await flushPromises()
    await wrapper.find('[data-testid="project-row"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-testid="thread-rename"]').trigger('click')
    await flushPromises()

    expect(agentApi.renameThread).toHaveBeenCalledWith('t1', '新名称')
  })

  it('deletes a thread after confirming', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [mockThread('t1', '1')] })
    vi.mocked(agentApi.deleteThread).mockResolvedValue(undefined)

    const wrapper = setupWrapper()
    await flushPromises()
    await wrapper.find('[data-testid="project-row"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-testid="thread-delete"]').trigger('click')
    await flushPromises()

    expect(agentApi.deleteThread).toHaveBeenCalledWith('t1')
  })

  it('creates a project through the dialog', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([])
    const created = mockProject('new')
    vi.mocked(projectsApi.createProject).mockResolvedValue(created)

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="new-project"]').trigger('click')
    await flushPromises()

    await wrapper.find('input[placeholder="请输入项目名称"]').setValue('New Project')
    await wrapper.find('input[placeholder*="本机绝对路径"]').setValue('/tmp/new')

    const createButton = wrapper.findAll('button').find((b) => b.text().includes('创建'))
    await createButton!.trigger('click')
    await flushPromises()

    expect(projectsApi.createProject).toHaveBeenCalledWith({
      name: 'New Project',
      path: '/tmp/new',
      description: undefined,
    })
  })

  it('creates a thread in the clicked project via its plus action', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])
    vi.mocked(agentApi.createThread).mockResolvedValue({ thread_id: 't-new' })
    vi.mocked(agentApi.listThreads).mockResolvedValue({ threads: [] })

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="project-new-thread"]').trigger('click')
    await flushPromises()

    expect(agentApi.createThread).toHaveBeenCalledWith('1', expect.objectContaining({
      llm_model: 'deepseek-v4-flash',
    }))
    expect(useProjectStore().currentProject?.id).toBe('1')
  })

  it('warns on 新建任务 when no project is selected', async () => {
    vi.mocked(projectsApi.listProjects).mockResolvedValue([mockProject('1')])

    const wrapper = setupWrapper()
    await flushPromises()

    await wrapper.find('[data-testid="new-task"]').trigger('click')
    await flushPromises()

    expect(ElMessage.warning).toHaveBeenCalled()
    expect(agentApi.createThread).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/components/__tests__/ProjectTree.spec.ts`
Expected: FAIL（找不到模块 `../ProjectTree.vue`）

- [ ] **Step 3: 实现组件**

创建 `frontend/src/components/ProjectTree.vue`：

```vue
<template>
  <div class="project-tree">
    <div class="project-tree-top">
      <button class="new-task-btn" data-testid="new-task" @click="handleNewTask">
        <el-icon><Plus /></el-icon>
        <span>新建任务</span>
      </button>
      <el-button
        link
        size="small"
        :icon="FolderAdd"
        data-testid="new-project"
        title="新建项目"
        @click="dialogVisible = true"
      >
        新建项目
      </el-button>
    </div>

    <div class="project-tree-group">项目</div>

    <el-skeleton
      v-if="projectStore.loading && !projectStore.projects.length"
      :rows="4"
      animated
      class="tree-skeleton"
    />
    <el-empty v-else-if="!projectStore.projects.length" description="暂无项目" :image-size="60" />

    <ul v-else class="project-tree-items">
      <li v-for="project in projectStore.projects" :key="project.id">
        <div
          class="project-row"
          :class="{ 'project-row--active': projectStore.currentProject?.id === project.id }"
          data-testid="project-row"
          tabindex="0"
          role="button"
          @click="handleProjectClick(project)"
          @keydown.enter="handleProjectClick(project)"
        >
          <el-icon class="row-icon">
            <FolderOpened v-if="isExpanded(project.id)" />
            <Folder v-else />
          </el-icon>
          <span class="row-label">{{ project.name }}</span>
          <span class="row-actions">
            <el-button
              link
              size="small"
              :icon="Plus"
              title="新建对话"
              data-testid="project-new-thread"
              @click.stop="handleNewThread(project)"
            />
            <el-button
              link
              size="small"
              :icon="Edit"
              title="重命名项目"
              data-testid="project-rename"
              @click.stop="handleRenameProject(project)"
            />
            <el-button
              link
              size="small"
              type="danger"
              :icon="Delete"
              title="删除项目"
              data-testid="project-delete"
              @click.stop="handleDeleteProject(project)"
            />
          </span>
        </div>

        <ul v-if="isExpanded(project.id)" class="thread-items">
          <li
            v-for="thread in threadsOf(project.id)"
            :key="thread.id"
            class="thread-row"
            :class="{ 'thread-row--active': agentStore.currentThread?.id === thread.id }"
            data-testid="thread-row"
            tabindex="0"
            role="button"
            @click="handleThreadClick(project, thread)"
            @keydown.enter="handleThreadClick(project, thread)"
          >
            <el-icon class="row-icon"><ChatDotRound /></el-icon>
            <span class="row-label">{{ thread.title || '未命名会话' }}</span>
            <span class="row-actions">
              <el-button
                link
                size="small"
                :icon="Edit"
                title="重命名会话"
                data-testid="thread-rename"
                @click.stop="handleRenameThread(project, thread)"
              />
              <el-button
                link
                size="small"
                type="danger"
                :icon="Delete"
                title="删除会话"
                data-testid="thread-delete"
                @click.stop="handleDeleteThread(project, thread)"
              />
            </span>
          </li>
          <li v-if="threadsOf(project.id).length === 0" class="thread-empty">暂无会话</li>
        </ul>
      </li>
    </ul>

    <el-dialog v-model="dialogVisible" title="新建项目" width="480px" @closed="resetForm">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入项目名称" />
        </el-form-item>
        <el-form-item label="路径" prop="path">
          <el-input
            v-model="form.path"
            placeholder="相对路径（如 demo）或本机绝对路径（如 D:\project）"
          />
        </el-form-item>
        <el-form-item label="描述" prop="description">
          <el-input
            v-model="form.description"
            type="textarea"
            placeholder="请输入项目描述"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="projectStore.loading" @click="handleCreate">
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Plus,
  Edit,
  Delete,
  Folder,
  FolderOpened,
  FolderAdd,
  ChatDotRound,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useProjectStore } from '@/stores/project'
import { useAgentStore } from '@/stores/agent'
import type { Project } from '@/api/projects'
import type { ThreadSummary } from '@/api/agent'

const projectStore = useProjectStore()
const agentStore = useAgentStore()
const route = useRoute()
const router = useRouter()

const dialogVisible = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({
  name: '',
  path: '',
  description: '',
})

const rules = reactive<FormRules>({
  name: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
  path: [{ required: true, message: '请输入项目路径', trigger: 'blur' }],
})

// 展开状态：会话内存即可，刷新后默认只展开当前项目。
const expandedIds = ref<Set<string>>(new Set())

function isExpanded(projectId: string): boolean {
  return expandedIds.value.has(projectId)
}

function threadsOf(projectId: string): ThreadSummary[] {
  return agentStore.threadsByProject[projectId] ?? []
}

onMounted(() => {
  loadProjects()
})

async function loadProjects(): Promise<void> {
  try {
    await projectStore.loadProjects()
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '加载项目失败')
  }
}

// 当前项目始终保持展开（含刷新后的初始状态）。
watch(
  () => projectStore.currentProject?.id,
  (id) => {
    if (id && !expandedIds.value.has(id)) {
      expandedIds.value.add(id)
      void ensureThreadsLoaded(id)
    }
  },
  { immediate: true }
)

async function ensureThreadsLoaded(projectId: string): Promise<void> {
  if (agentStore.threadsByProject[projectId]) return
  try {
    await agentStore.loadProjectThreads(projectId)
  } catch {
    // axios 拦截器统一 toast；折叠后重新展开即可重试
  }
}

async function handleProjectClick(project: Project): Promise<void> {
  const isCurrent = projectStore.currentProject?.id === project.id
  projectStore.selectProject(project.id)
  if (expandedIds.value.has(project.id)) {
    // 只有再次点击当前项目才折叠；切换到其他项目时保持展开
    if (isCurrent) {
      expandedIds.value.delete(project.id)
    }
    return
  }
  expandedIds.value.add(project.id)
  await ensureThreadsLoaded(project.id)
}

async function handleThreadClick(project: Project, thread: ThreadSummary): Promise<void> {
  if (projectStore.currentProject?.id !== project.id) {
    // 交由 AgentView 的项目切换 watcher 消费 preferredThreadId 完成加载
    agentStore.preferredThreadId = thread.id
    agentStore.selectedModel = thread.llm_model
    projectStore.selectProject(project.id)
  } else if (thread.id !== agentStore.currentThread?.id) {
    agentStore.selectedModel = thread.llm_model
    await agentStore.loadThread(thread.id, project.analysis.api_key, thread.llm_model)
  }
  if (route.path !== '/') {
    void router.push('/')
  }
}

function handleNewTask(): void {
  const project = projectStore.currentProject
  if (!project) {
    ElMessage.warning('请先选择项目')
    return
  }
  void handleNewThread(project)
}

async function handleNewThread(project: Project): Promise<void> {
  if (projectStore.currentProject?.id !== project.id) {
    projectStore.selectProject(project.id)
  }
  await agentStore.createThread(project.id, project.analysis.api_key, agentStore.selectedModel)
  if (route.path !== '/') {
    void router.push('/')
  }
}

async function handleRenameProject(project: Project): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('请输入新名称', '重命名项目', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: project.name,
      inputValidator: (v) => (v && v.trim() ? true : '名称不能为空'),
    })
    await projectStore.renameProject(project.id, value.trim())
  } catch {
    // 用户取消；API 失败由 axios 拦截器统一 toast
  }
}

async function handleDeleteProject(project: Project): Promise<void> {
  try {
    await ElMessageBox.confirm('确定要删除该项目吗？其下的会话将一并删除。', '提示', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  try {
    await projectStore.deleteProject(project.id)
    agentStore.clearProjectThreads(project.id)
    expandedIds.value.delete(project.id)
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '删除项目失败')
  }
}

async function handleRenameThread(project: Project, thread: ThreadSummary): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('请输入新标题', '重命名会话', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: thread.title || '未命名会话',
      inputValidator: (v) => (v && v.trim() ? true : '标题不能为空'),
    })
    await agentStore.renameThread(thread.id, value.trim(), project.id)
  } catch {
    // 用户取消；API 失败由 axios 拦截器统一 toast
  }
}

async function handleDeleteThread(project: Project, thread: ThreadSummary): Promise<void> {
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
    await agentStore.deleteThread(thread.id, project.id)
  } catch {
    // 用户取消；API 失败由 axios 拦截器统一 toast
  }
}

async function handleCreate(): Promise<void> {
  if (!formRef.value) return

  try {
    await formRef.value.validate()
  } catch {
    ElMessage.warning('请填写必填项')
    return
  }

  try {
    await projectStore.createProject({
      name: form.name.trim(),
      path: form.path.trim(),
      description: form.description.trim() || undefined,
    })

    dialogVisible.value = false
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '创建项目失败')
  }
}

function resetForm(): void {
  form.name = ''
  form.path = ''
  form.description = ''
  formRef.value?.resetFields()
}
</script>

<style scoped>
.project-tree {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.project-tree-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.75rem 0.75rem 0.25rem;
}

.new-task-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.375rem;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-lg);
  background: transparent;
  color: var(--app-text);
  font-size: 0.875rem;
  cursor: pointer;
  transition: background-color 0.2s;
}

.new-task-btn:hover {
  background-color: var(--app-sidebar-hover);
}

.project-tree-group {
  padding: 1rem 1rem 0.375rem;
  font-size: 0.75rem;
  color: var(--app-text-muted);
}

.tree-skeleton {
  padding: 1rem;
}

.project-tree-items {
  list-style: none;
  margin: 0;
  padding: 0 0.5rem 0.5rem;
  overflow-y: auto;
  flex: 1;
}

.project-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4375rem 0.625rem;
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: background-color 0.2s;
  outline: none;
}

.project-row:hover {
  background-color: var(--app-sidebar-hover);
}

.project-row:focus-visible {
  outline: 2px solid var(--app-accent);
  outline-offset: -2px;
}

.project-row--active {
  background-color: var(--app-sidebar-active);
}

.project-row--active .row-label {
  font-weight: 600;
}

.row-icon {
  flex-shrink: 0;
  color: var(--app-text-muted);
}

.row-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-text);
  font-size: 0.875rem;
}

.row-actions {
  display: flex;
  gap: 0.125rem;
  opacity: 0;
  transition: opacity 0.2s;
}

.project-row:hover .row-actions,
.project-row:focus-within .row-actions,
.thread-row:hover .row-actions,
.thread-row:focus-within .row-actions {
  opacity: 1;
}

.row-actions .el-button + .el-button {
  margin-left: 0;
}

.thread-items {
  list-style: none;
  margin: 0;
  padding: 0 0 0.25rem 1.25rem;
}

.thread-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0.625rem;
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: background-color 0.2s;
}

.thread-row:hover {
  background-color: var(--app-sidebar-hover);
}

.thread-row:focus-visible {
  outline: 2px solid var(--app-accent);
  outline-offset: -2px;
}

.thread-row--active {
  background-color: var(--app-sidebar-active);
}

.thread-row--active .row-label {
  font-weight: 600;
}

.thread-empty {
  padding: 0.375rem 0.625rem;
  font-size: 0.75rem;
  color: var(--app-text-muted);
}
</style>
```

- [ ] **Step 4: 运行确认通过**

Run: `cd frontend && npx vitest run src/components/__tests__/ProjectTree.spec.ts`
Expected: 全部 PASS

- [ ] **Step 5: 删除旧测试并提交**

```bash
rm frontend/src/components/__tests__/ProjectList.spec.ts frontend/src/components/__tests__/ThreadList.spec.ts
git add frontend/src/components/ProjectTree.vue frontend/src/components/__tests__/
git commit -m "feat(frontend): add ProjectTree merged sidebar component"
```

注意：此 commit 后 `App.vue`/`AgentView.vue` 仍引用旧组件，`npm run build` 暂时可用（旧组件文件还在），完整套件在 Task 8 后跑。

---

### Task 7: App.vue 接入 ProjectTree

**Files:**
- Modify: `frontend/src/App.vue`
- Test: `frontend/src/__tests__/App.spec.ts`

- [ ] **Step 1: 改测试（先失败）**

`frontend/src/__tests__/App.spec.ts` 中 stubs 改为：

```ts
      stubs: {
        ProjectTree: { template: '<div class="project-tree-stub" />' },
        'router-link': { template: '<a><slot /></a>' },
        'router-view': true,
      },
```

三个断言里的 `.project-list-stub` 全部改为 `.project-tree-stub`。

- [ ] **Step 2: 运行确认失败**

Run: `cd frontend && npx vitest run src/__tests__/App.spec.ts`
Expected: FAIL（找不到 `.project-tree-stub`，因为 App.vue 还在用 ProjectList）

- [ ] **Step 3: 修改 App.vue**

- import 行 `import ProjectList from '@/components/ProjectList.vue'` 改为 `import ProjectTree from '@/components/ProjectTree.vue'`
- 模板中 `<ProjectList v-show="!isSidebarCollapsed" />` 改为 `<ProjectTree v-show="!isSidebarCollapsed" />`
- 侧边栏宽度 320px 保留；折叠/展开与 localStorage 逻辑不动

- [ ] **Step 4: 运行确认通过**

Run: `cd frontend && npx vitest run src/__tests__/App.spec.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.vue frontend/src/__tests__/App.spec.ts
git commit -m "feat(frontend): mount ProjectTree in App sidebar"
```

---

### Task 8: AgentView 移除 ThreadList，watcher 消费 preferredThreadId

**Files:**
- Modify: `frontend/src/views/AgentView.vue`
- Test: `frontend/src/views/__tests__/AgentView.spec.ts`
- Delete: `frontend/src/components/ProjectList.vue`
- Delete: `frontend/src/components/ThreadList.vue`

- [ ] **Step 1: 改测试**

`frontend/src/views/__tests__/AgentView.spec.ts`：

1) 删除两个用例：`'persists thread list collapse state in localStorage'` 和 `'restores thread list collapse state from localStorage on mount'`。

2) 追加新用例：

```ts
  it('loads the preferred thread instead of the latest when one is set', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    const t1 = {
      id: 't1',
      project_id: '2',
      title: 'Latest',
      llm_model: 'deepseek-v4-flash',
      created_at: '2026-01-01',
      updated_at: '2026-01-03',
    }
    const t2 = { ...t1, id: 't2', title: 'Preferred', updated_at: '2026-01-02' }
    vi.spyOn(agentStore, 'listThreads').mockImplementation(async () => {
      agentStore.threads = [t1, t2]
    })
    const loadSpy = vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    // 用 selectProject 而不是直接赋值，保证 currentConfig 被设置（watcher 依赖）
    projectStore.projects = [mockProject('1'), mockProject('2')]
    projectStore.selectProject('1')
    setupWrapper()
    await flushPromises()

    agentStore.preferredThreadId = 't2'
    projectStore.selectProject('2')
    await flushPromises()

    expect(loadSpy).toHaveBeenCalledWith('t2', expect.any(String), 'deepseek-v4-flash')
    expect(agentStore.preferredThreadId).toBeNull()
  })

  it('does not reload when the current thread already belongs to the project', async () => {
    const projectStore = useProjectStore()
    const agentStore = useAgentStore()
    const listSpy = vi.spyOn(agentStore, 'listThreads').mockResolvedValue(undefined)
    vi.spyOn(agentStore, 'loadThread').mockResolvedValue(undefined)

    agentStore.threadId = 't1'
    agentStore.currentThread = {
      id: 't1',
      project_id: '1',
      title: 'Open',
      llm_model: 'deepseek-v4-flash',
      created_at: '2026-01-01',
      updated_at: '2026-01-02',
    }

    projectStore.currentProject = mockProject('1')
    setupWrapper()
    await flushPromises()

    expect(listSpy).not.toHaveBeenCalled()
  })
```

- [ ] **Step 2: 修改 AgentView.vue**

1) 模板：删除整个 `<ThreadList ... />` 块（11–20 行），`.agent-workspace` 内只留 `.agent-chat-wrapper` 和 `.agent-side-panel`。

2) script：

- 删除 `import ThreadList from '@/components/ThreadList.vue'`
- 删除 `THREAD_LIST_COLLAPSED_KEY`、`loadThreadListCollapsed`、`saveThreadListCollapsed`、`isThreadListCollapsed`、`handleToggleThreadListCollapse`
- 删除 `handleSelectThread`、`handleCreateThread`、`handleRenameThread`、`handleDeleteThread`（逻辑已迁入 ProjectTree）
- 删除 `import { DEFAULT_AGENT_MODEL } from '@/api/agent'`；`selectedModel` 改为 store 代理：

```ts
const selectedModel = computed({
  get: () => agentStore.selectedModel,
  set: (value: string) => {
    agentStore.selectedModel = value
  },
})
```

- 项目切换 watcher 改为：

```ts
watch(
  () => projectStore.currentProject?.id,
  async (newId, oldId) => {
    if (newId === oldId) return
    // 当前对话已属于该项目（例如在设置页通过侧边栏打开了当前项目的会话）：
    // 不重置、不重复加载。
    if (newId && agentStore.threadId && agentStore.currentThread?.project_id === newId) {
      // 不重载对话，但离开页面时 SSE 已断开，恢复事件流与最新状态。
      void agentStore.reconnect()
      return
    }
    agentStore.resetThread()
    if (!newId) return
    await agentStore.listThreads(newId)
    const config = projectStore.currentConfig
    if (!config) return
    // 侧边栏跨项目点选对话时设置了 preferredThreadId，优先加载它。
    const preferred = agentStore.preferredThreadId
    agentStore.preferredThreadId = null
    const target =
      agentStore.threads.find((t) => t.id === preferred) ?? agentStore.threads[0]
    if (target) {
      await agentStore.loadThread(target.id, config.api_key, target.llm_model)
      agentStore.selectedModel = target.llm_model
    }
  },
  { immediate: true }
)
```

- `onMounted` 空函数及其注释一并删除，同时从 `vue` 的 import 中移除 `onMounted`（保留 `ref, computed, watch, onUnmounted`）。

> 执行期补充（质量审查后落地）：store 的 `loadThread` 解析 `currentThread` 时在扁平列表与桩之间增加 `Object.values(threadsByProject.value).flat().find(...)` 缓存查找（修复深链刷新后 guard 失效导致已打开对话被顶替的问题）。

3) 删除旧组件文件：

```bash
rm frontend/src/components/ProjectList.vue frontend/src/components/ThreadList.vue
```

- [ ] **Step 3: 运行确认通过**

Run: `cd frontend && npx vitest run`
Expected: 全部 PASS（无残留引用 ProjectList/ThreadList 的测试）

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/AgentView.vue frontend/src/views/__tests__/AgentView.spec.ts frontend/src/components/
git commit -m "feat(frontend): remove ThreadList; consume preferredThreadId in AgentView"
```

---

### Task 9: 全量验证

- [ ] **Step 1: 后端全量测试**

Run: `.venv/Scripts/python -m pytest tests/ -q`
Expected: 全部 PASS

- [ ] **Step 2: 前端类型检查 + 测试 + 构建**

Run: `cd frontend && npm run type-check && npx vitest run && npm run build`
Expected: 全部通过

- [ ] **Step 3: 手动冒烟（dev 环境）**

Run: 后端 `uvicorn main:app --reload`（或项目惯用启动方式）+ 前端 `npm run dev`，人工验证：
- 侧边栏项目展开/折叠、懒加载对话
- 项目重命名、对话重命名、两级删除
- 跨项目点击对话只加载一次目标对话
- 浅色/深色主题下侧边栏观感

- [ ] **Step 4: Commit（如有修复）**

```bash
git add -A
git commit -m "chore: smoke fixes for merged sidebar"
```
