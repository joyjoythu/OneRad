# 默认 Agent 页 + 设置页只留 API 配置 — 设计

日期：2026-07-17
状态：已批准

## 背景与问题

前端目前默认进入"分析"页（`/` → AnalysisView），包含数据配置、模型配置、运行/停止、报告、日志等经典分析流水线功能。用户的工作流已转向 Agent 页，希望：默认进入 Agent 界面；"分析"页只保留 API 配置，其余功能砍掉（前端-only 删除，后端 API 保留）。

关键约束（来自代码勘察）：`api_key` 是分析页与 Agent 页之间唯一的耦合点——Agent 页发消息/建 thread 都从 `projectStore.currentConfig.api_key` 取 key；后端 `app/agent/__init__.py` 也从 project 的 `analysis.api_key` 兜底取 key。必须保住"api_key 录入 + `PUT /api/projects/{id}/config` 持久化"链路。

## 目标

- 打开应用默认进入 Agent 界面。
- 原"分析"页改为"设置"页（`/settings`），只含 API 密钥的录入与保存。
- 被砍功能的前端代码（运行控制、日志、报告入口、runStore、runs API 封装）删除；后端代码零改动。

## 方案取舍

- **新建精简 `SettingsView.vue`** 而非原地改造 `AnalysisForm`：旧表单耦合运行控制，新建干净、旧文件整体删除。
- **`/agent` 保留为 redirect 到 `/`**：兼容已有链接，成本一行。
- **`AnalysisConfig` 类型整体保留**：收缩类型会牵动后端 config schema 与 PUT 整对象提交语义，前端-only 原则下不动。

## 改动点

### 路由与导航

- `frontend/src/router/index.ts`：
  - `{ path: '/', component: AgentView（懒加载） }`（原 `/agent` 的定义移到 `/`）
  - `{ path: '/agent', redirect: '/' }`
  - `{ path: '/settings', component: SettingsView（懒加载） }`
- `frontend/src/App.vue` 导航：`Agent` → `/`，`设置` → `/settings`（原"分析"链接移除）。

### 设置页（新建 `frontend/src/views/SettingsView.vue`）

- 未选项目（`projectStore.currentProject` 为空）：提示"请先选择一个项目"。
- 已选项目：el-form 仅一项 **API 密钥**（`show-password`，本地草稿 ref 初始化为 `currentConfig.api_key`）；文案如实描述"随项目保存"（不再沿用旧表单"仅当前会话保留"的错误提示）。
- 「保存」按钮 → `projectStore.saveConfig({ ...currentConfig, api_key: draft })`（PUT 整对象，其余字段保留原值），成功 `ElMessage.success` 提示；失败由 axios 拦截器统一提示。
- 切换项目时草稿同步刷新（watch `currentConfig`）。

### 删除清单（前端-only）

- `frontend/src/views/AnalysisView.vue`
- `frontend/src/components/AnalysisForm.vue`
- `frontend/src/components/LogViewer.vue`
- `frontend/src/stores/run.ts`
- `frontend/src/api/runs.ts`
- `frontend/src/components/__tests__/AnalysisForm.spec.ts`
- `frontend/src/stores/__tests__/run.spec.ts`

### 保留不动

- `frontend/src/stores/project.ts`（`currentConfig` / `saveConfig` 全保留）
- `frontend/src/api/projects.ts`（`AnalysisConfig` 类型整体保留）
- `frontend/src/components/AnalysisPanel.vue`（属 Agent 的 radiomics 分析确认面板，与分析页无关）
- 后端全部代码（runs 系列 API 变为无调用方，刻意保留）

## 数据流（设置页保存）

1. 用户输入 api_key → 本地草稿 ref；
2. 点保存 → `projectStore.saveConfig()` → `PUT /api/projects/{id}/config`（整对象）→ 更新 `currentConfig`；
3. Agent 页下次 ensureThread/loadThread/createThread 自动使用新 key（既有链路，无改动）。

## 错误处理

- 未选项目：显示提示，不渲染表单。
- 保存失败：axios 拦截器统一提示（既有行为）。
- localStorage/路由异常：无新增依赖。

## 测试

- 新建 `frontend/src/views/__tests__/SettingsView.spec.ts`：
  1. 未选项目时显示"请先选择一个项目"提示；
  2. 已选项目时渲染 api_key 输入框且初值来自 `currentConfig.api_key`；
  3. 点保存调用 `projectStore.saveConfig` 且载荷 api_key 为新值、其余字段不变。
- 回归：前端全量 `vitest run` + `type-check` + `lint` + `build`；后端零改动，不跑后端测试。

## 不做的事（YAGNI）

- 后端 runs 流水线及路由的删除
- `AnalysisConfig` 类型收缩
- 设置页内增加其他设置项（主题、语言等）
- 自动保存 debounce（设置页仅手动保存）
