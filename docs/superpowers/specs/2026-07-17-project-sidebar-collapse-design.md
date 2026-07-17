# 项目侧边栏可折叠 — 设计

日期：2026-07-17
状态：已批准

## 背景与问题

全局布局 `frontend/src/App.vue` 的 `.app-sidebar`（320px，内嵌 `ProjectList`）固定展开，占宽不可回收。Agent 页的历史会话面板（ThreadList）已支持折叠成窄条，用户希望项目侧边栏也有同样能力。

## 目标

项目侧边栏可折叠为 40px 窄条（仅留展开按钮），折叠状态记忆到 localStorage，刷新后保持。只读布局行为，不影响 ProjectList 功能。

## 方案

复用 ThreadList 的既有折叠模式（Fold/Expand 图标按钮 + collapsed 类 + `v-show` 隐藏内容 + localStorage 记忆），内聚在 `App.vue` 实现——折叠是布局行为，ProjectList 组件零改动。

## 改动点

### `frontend/src/App.vue`

- 新增 `isSidebarCollapsed` ref，初始值读 localStorage 键 `onerad:app:sidebarCollapsed`；load/save 函数复刻 `AgentView.vue:87-101` 的 try/catch 模式（读取异常时默认展开，写入异常静默忽略）。
- `.app-sidebar` 内、`<ProjectList />` 上方加折叠按钮栏：`el-button` link 小按钮，图标 `Fold`（展开时）/`Expand`（折叠时），来自 `@element-plus/icons-vue`；aria-label 随状态为「折叠项目面板」/「展开项目面板」；点击切换状态并写 localStorage。
- 折叠态：aside 加 `.app-sidebar--collapsed` 类，宽度 320px → 40px，按钮栏居中；`<ProjectList />` 直接加 `v-show="!isSidebarCollapsed"`（v-show 作用于组件根节点）。`.app-sidebar` 加 `transition: width 0.2s ease`（同 ThreadList）。

### `frontend/src/__tests__/App.spec.ts`（新建）

挂载 App.vue：pinia + ElementPlus 插件；stub `ProjectList`、`router-link`、`router-view`；每个用例前清空 localStorage mock。

## 行为

- 折叠后所有页面（分析/Agent）主区域同步变宽——aside 是全局布局，符合预期。
- 刷新/重开页面保持折叠状态；localStorage 不可用时静默降级为默认展开。

## 测试用例

1. 默认展开：aside 无 collapsed 类，按钮 aria-label 为「折叠项目面板」。
2. 点击切换：折叠后 aside 出现 collapsed 类、ProjectList 内容隐藏、按钮 aria-label 变「展开项目面板」，localStorage 写入 `'true'`；再点恢复。
3. 状态记忆：localStorage 预置 `'true'` 时挂载即为折叠态。

## 错误处理

- localStorage 抛异常（隐私模式等）：读默认展开、写静默忽略，页面功能不受影响。

## 不做的事（YAGNI）

- 拖拽调宽
- 折叠状态同步到后端
- ProjectList 组件接口改动
