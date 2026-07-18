# 合并项目/对话侧边栏设计（ProjectTree）

日期：2026-07-18

## 背景与目标

当前前端有两个独立侧边栏：

- `frontend/src/components/ProjectList.vue`（挂在 `App.vue`，320px，项目列表 + 新建/删除）
- `frontend/src/components/ThreadList.vue`（挂在 `AgentView.vue`，240px，当前项目的对话列表 + 新建/重命名/删除）

目标：合并为一个侧边栏——项目以"文件夹"形式展示，下一级嵌套该项目的对话；支持项目重命名和对话重命名；视觉风格向参考截图（Kimi 风格侧边栏）看齐。

## 范围

做：

- 新组件 `ProjectTree.vue` 替换上述两个组件
- 项目重命名（含后端新接口）
- 对话重命名（复用现有接口与交互）
- 侧边栏视觉重做（参考图风格）

不做（YAGNI）：

- 会话跨项目移动
- 拖拽排序、项目嵌套、会话搜索
- 未归属项目的"默认分组"（现有数据模型中 thread 必有 project_id）

## 架构与组件

### 布局改动

- `App.vue`：原 `<ProjectList>` 位置换成 `<ProjectTree>`，保留 320px / 折叠 40px 行为与 localStorage 持久化
- `AgentView.vue`：删除内部 240px 的 `<ThreadList>`，工作区只剩对话区 + 右侧审批面板

### ProjectTree.vue 结构

```
┌─────────────────────────┐
│ [+ 新建任务]   (顶部按钮) │  圆角描边按钮
│ 项目          (分组小标题) │
│ 📁 项目A            ⋯   │  ← 项目行：点击=选中+展开/折叠
│    💬 对话 1        ⋯   │  ← 对话行：点击=进入对话
│    💬 对话 2            │
│ 📁 项目B                │
│ 📁 项目C                │
└─────────────────────────┘
```

- 项目行悬停操作：重命名 / 删除 / 新建对话
- 对话行悬停操作：重命名 / 删除
- 重命名统一用 `ElMessageBox.prompt`（与 ThreadList 现有交互一致）
- 删除沿用现有确认逻辑

### 数据流

- `stores/agent.ts`：`threads: ThreadSummary[]` 改为按项目分组缓存 `threadsByProject: Record<string, ThreadSummary[]>`；展开某项目时懒加载 `listThreads(projectId)`（已加载过则直接用缓存，`createThread/renameThread/deleteThread` 同步更新对应分组）
- `stores/project.ts`：新增 `renameProject(id, name)` action
- `api/projects.ts`：新增 `renameProject(id, name)` → `PATCH /api/projects/{id}` body `{name}`
- 进入 Agent 页 / 切换项目的现有逻辑不变（仍由 `currentProject` 驱动），`ProjectTree` 选中项目即调用现有 `selectProject`

### 后端改动

- `app/projects.py`：`ProjectStore` 新增 `update_name(project_id, name)`（UPDATE projects SET name, updated_at）
- `app/api/projects.py`：新增 `PATCH /api/projects/{id}`，请求体 `ProjectPatchRequest{name: str}`，复用现有错误处理风格；名称校验非空
- 对话重命名接口 `PATCH /api/agent/threads/{id}` 已存在，不动

### 视觉规范（向参考图看齐）

- 侧边栏浅灰白底色（复用现有 `--app-*` 背景令牌），与主内容区无硬边框，靠留白分层
- 分组小标题"项目"：小字号、浅灰、上下大留白
- 行：圆角 ~8px 矩形；选中项浅灰填充背景（令牌 `--app-sidebar-active-bg`）；hover 更浅一档（`--app-sidebar-hover-bg`）；无边框无下划线
- 图标：小号细线条文件夹 / 对话图标（`@element-plus/icons-vue` 中 `Folder` / `ChatDotRound` 类），与文字基线对齐
- 文字：项目名常规字重；选中项深色/加粗；次要信息浅灰小字
- 行操作按钮：平时隐藏，hover 时行右侧浮出小图标按钮
- 顶部"新建任务"：圆角描边按钮，不用 Element 实心默认样式
- `tokens.css` 补侧边栏专用令牌，`html.dark` 同步适配
- 不用 Element Plus 的 Menu/Tree 默认样式，行手写

## 错误处理

- 项目重命名失败：`ElMessage.error` 提示，列表保持原值（后端 404/校验失败均返回现有错误格式）
- 空项目名：前端 trim 后为空则不发起请求；后端同样校验 422/400
- 展开项目加载对话失败：该项目行下方显示"加载失败，点击重试"，不阻塞其他项目
- 删除项目沿用级联删除语义（threads ON DELETE CASCADE），删除后若该项目含当前对话则 `resetThread()`

## 测试

- 后端：`tests/` 中按现有 API 测试风格为 `PATCH /api/projects/{id}` 补用例——成功改名、空名 400、不存在 404、重名 400；`ProjectStore.update_project_name` 单元用例
- 前端（vitest + @vue/test-utils，已有测试体系）：新增 `ProjectTree.spec.ts` 覆盖合并侧边栏交互；删除 `ProjectList.spec.ts` / `ThreadList.spec.ts`；更新 `App.spec.ts`、`AgentView.spec.ts`、`stores/__tests__/project.spec.ts`、`stores/__tests__/agent.spec.ts`；验收再加 `npm run type-check` 与 `npm run build`

## 涉及文件清单

新增：

- `frontend/src/components/ProjectTree.vue`

修改：

- `frontend/src/App.vue`
- `frontend/src/views/AgentView.vue`（移除 ThreadList）
- `frontend/src/stores/agent.ts`（threads 分组缓存）
- `frontend/src/stores/project.ts`（renameProject）
- `frontend/src/api/projects.ts`（renameProject）
- `frontend/src/styles/tokens.css`（侧边栏令牌）
- `frontend/src/__tests__/App.spec.ts`
- `frontend/src/views/__tests__/AgentView.spec.ts`
- `frontend/src/stores/__tests__/project.spec.ts`
- `frontend/src/stores/__tests__/agent.spec.ts`
- `app/projects.py`（update_project_name）
- `app/api/projects.py`（PATCH 路由）
- `tests/test_projects.py`、`tests/test_api_projects.py`

新增测试：

- `frontend/src/components/__tests__/ProjectTree.spec.ts`

删除：

- `frontend/src/components/ProjectList.vue` + `frontend/src/components/__tests__/ProjectList.spec.ts`
- `frontend/src/components/ThreadList.vue` + `frontend/src/components/__tests__/ThreadList.spec.ts`
