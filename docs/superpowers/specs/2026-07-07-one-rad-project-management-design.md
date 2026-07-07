# OneRad 项目管理模块设计

## 背景

AutoRadiomics Agent 目前只有一个 Gradio UI，所有分析参数都填在主界面上，无法同时管理多个影像组学项目，也无法把不同项目的配置、参数和结果分项目保存。用户希望像 Kimi Work 那样在左侧增加项目侧边栏，支持多项目并行管理，并把 `Params_labels.yaml`、影像组学配置和运行结果等项目相关信息保存在各自项目路径下。

产品名统一为 **OneRad**（仅在 UI 和文档中使用；CLI 入口 `main.py`、包名 `app` 保持不变）。

## 目标

1. 在 Gradio UI 左侧增加“项目”侧边栏，可新建、切换、保存、删除项目。
2. 每个项目拥有独立目录，目录下保存 `project.yaml`（项目元数据 + 当前分析配置快照）和 `Params_labels.yaml`（影像组学参数配置）。
3. 使用 SQLite 轻量数据库保存项目列表和每次运行历史，便于快速检索与状态追踪。
4. 影像文件和临床表格仍由用户路径引用，不复制到项目目录。
5. 运行分析时以当前项目配置为准，运行结束后自动记录运行历史。

## 非目标

- 不引入独立前端框架（Vue/React），保持现有 Gradio 方案。
- 不将影像 / mask / 临床数据复制或迁移到项目目录。
- 不做用户登录、权限、多机器同步。

## 总体布局

```
+----------------------------------+------------------------------+
|  OneRad                          |  当前项目: ZHY-ESWA          |
|  [+ 新建项目]                     |                              |
|                                  |  影像文件夹路径  [________]   |
|  项目                             |  临床表格路径    [________]   |
|  ----                            |  输出目录        [________]   |
|  • ZHY-ESWA                      |  模态            [auto ▼]    |
|  • C_Prj                         |  协变量          [________]   |
|  • XHY-MICCAI-EXP...             |  API Key         [********]   |
|                                  |  模型            [________]   |
|                                  |                              |
|                                  |  [保存项目配置]  [运行分析]   |
|                                  |                              |
|                                  |  日志                          |
|                                  |  [                         ]  |
|                                  |                              |
|                                  |  生成报告 [下载]               |
+----------------------------------+------------------------------+
```

- 左侧：`gr.Column(scale=0, min_width=240)`，包含标题、新建按钮、项目列表。
- 右侧：`gr.Column(scale=1)`，包含当前项目名称、分析表单、日志、报告。

## 数据模型

SQLite 默认路径：`~/.onerad/projects.db`（可通过环境变量 `ONERAD_DB_PATH` 覆盖）。

### 表 `projects`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PRIMARY KEY | UUID |
| `name` | TEXT NOT NULL UNIQUE | 项目显示名 |
| `path` | TEXT NOT NULL UNIQUE | 项目目录绝对路径 |
| `description` | TEXT | 项目描述 |
| `created_at` | TEXT (ISO 8601) | 创建时间 |
| `updated_at` | TEXT (ISO 8601) | 最后更新时间 |

### 表 `runs`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | TEXT PRIMARY KEY | UUID |
| `project_id` | TEXT NOT NULL FK → projects.id | 所属项目 |
| `image_dir` | TEXT | 影像目录 |
| `clinical_path` | TEXT | 临床表格路径 |
| `output_dir` | TEXT | 输出目录 |
| `modality` | TEXT | 模态 |
| `covariates` | TEXT | 协变量（逗号分隔字符串） |
| `model` | TEXT | 模型名 |
| `status` | TEXT | `running` / `success` / `failed` |
| `log_summary` | TEXT | 日志摘要或错误信息 |
| `report_path` | TEXT | 生成的报告路径 |
| `started_at` | TEXT (ISO 8601) | 开始时间 |
| `finished_at` | TEXT (ISO 8601) | 结束时间 |

## 项目目录结构

创建项目时在用户指定路径下生成：

```
<project_path>/
  project.yaml        # 项目元数据 + 当前分析配置快照
  Params_labels.yaml  # 影像组学特征提取参数
  outputs/            # 默认输出目录（可选，可配置）
```

### project.yaml 示例

```yaml
name: ZHY-ESWA
description: 乳腺癌影像组学项目
path: /home/user/projects/ZHY-ESWA
created_at: "2026-07-07T09:54:58"
updated_at: "2026-07-07T10:30:00"

# 当前分析配置快照
analysis:
  image_dir: /data/ZHY-ESWA/images
  clinical_path: /data/ZHY-ESWA/clinical.csv
  output_dir: ./outputs
  modality: auto
  covariates: ""
  model: deepseek-chat
```

### Params_labels.yaml

复制 `config/Params_labels.yaml` 作为默认模板，用户可在项目目录下直接编辑。UI 运行分析时优先使用项目目录下的 `Params_labels.yaml`。

## 模块划分

### 1. `app/projects.py`

负责项目数据访问与文件操作，与 Gradio UI 解耦：

- `ProjectStore(db_path: str)`：SQLite 连接与 CRUD，支持内存数据库用于测试。
- `create_project(name, path, description)`：创建目录、生成 `project.yaml` 和默认 `Params_labels.yaml`，写入数据库。
- `load_project(project_id)`：读取数据库记录与 `project.yaml` 合并返回；若二者不一致以数据库为准并提示。
- `save_project_config(project_id, analysis_config)`：更新数据库和 `project.yaml`。
- `list_projects()`：返回项目列表（id, name, path），按 `updated_at` 降序排列。
- `delete_project(project_id)`：删除数据库记录，项目目录保留。
- `record_run_start(...)` / `record_run_end(...)`：写入运行历史。
- `list_runs(project_id, limit=50)`：查询项目的运行历史，按时间倒序。

### 2. `app/ui.py`（修改）

重构为左右布局，新增项目侧边栏组件：

- 左侧：标题 `OneRad`、`gr.Button("+ 新建项目")`、`gr.Radio`/`gr.Dataframe` 项目列表、`gr.Button("删除项目")`。
- 右侧：当前项目名称、分析表单、保存/运行按钮、日志、报告下载。
- 事件：
  - 新建项目：打开对话框（名称、路径、描述），确认后调用 `ProjectStore.create_project`。
  - 切换项目：加载项目配置并回填右侧表单，标题更新。
  - 保存配置：将右侧表单写入数据库和 `project.yaml`。
  - 运行分析：先保存当前配置，调用现有 `_run_analysis`，结束后写入 `runs` 表。

### 3. `tests/test_projects.py`（新增）

覆盖：

- 项目 CRUD（创建、列表、加载、保存、删除）。
- `project.yaml` 和 `Params_labels.yaml` 生成与读取。
- 运行历史记录。
- 项目路径不存在/不可写时的错误处理。

## 关键交互流程

### 新建项目

1. 用户点击“新建项目”，弹出 `gr.Row` 输入行：名称、目录、描述。
2. 确认后 `ProjectStore.create_project`：
   - 校验目录是否合法、是否已存在同名/同路径项目。
   - 创建目录。
   - 写入 `project.yaml` 和默认 `Params_labels.yaml`。
   - 插入 `projects` 表。
3. UI 刷新项目列表并自动切换到新项目。

### 切换项目

1. 用户点击左侧项目名。
2. `ProjectStore.load_project` 读取数据库与 `project.yaml`。
3. 右侧表单回填；若 `Params_labels.yaml` 缺失则自动生成默认副本。

### 保存配置

1. 用户修改右侧表单后点击“保存项目配置”。
2. `ProjectStore.save_project_config` 更新数据库 `analysis` 字段和 `project.yaml`。
3. UI 提示保存成功。

### 运行分析

1. 点击“运行分析”时先隐式保存当前配置。
2. 调用 `_run_analysis`，传入当前项目配置。
3. 运行开始前 `record_run_start` 插入 `runs` 表（status=`running`）。
4. 运行结束后 `record_run_end` 更新 status、`log_summary`、`report_path`、`finished_at`。
5. UI 显示日志和报告下载。

### 删除项目

1. 用户选中项目后点击“删除项目”，二次确认。
2. `ProjectStore.delete_project` 删除数据库记录。
3. 项目目录保留，用户可手动清理。
4. UI 刷新列表；若删除的是当前项目，右侧清空或切换到第一个项目。

## 错误处理

- 目录创建失败：返回明确错误信息，UI 弹窗/文本提示。
- 项目名或路径冲突：禁止创建，提示已有项目。
- 切换项目时 `project.yaml` 损坏：尝试读取数据库配置；若数据库也失败，提示用户项目文件损坏。
- `Params_labels.yaml` 缺失：自动生成默认模板并提示。
- 运行失败：`runs.status = failed`，日志摘要写入数据库，UI 显示失败原因。

## 配置与默认值

- 默认数据库目录：`~/.onerad/`，文件 `projects.db`。
- 默认 `Params_labels.yaml` 模板来源：`config/Params_labels.yaml`。
- 默认输出目录：`<project_path>/outputs`（用户可在表单中修改）。
- 产品名显示：`OneRad` 作为 UI 标题和浏览器标签页标题。

## 测试策略

- 单元测试使用临时目录和内存 SQLite（通过 `ProjectStore` 支持传入 `db_path`）。
- UI 行为测试使用 Gradio 的 `Blocks` 内部函数调用，验证切换项目后表单回填正确。
- 新增 `tests/test_projects.py`，不修改现有 `tests/test_*.py` 的测试逻辑。

## 后续可扩展点

- 项目搜索/过滤。
- 运行历史详情页。
- 项目导入/导出（打包 `project.yaml` + `Params_labels.yaml`）。
- 最近打开项目快速访问。
