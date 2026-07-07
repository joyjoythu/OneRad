# OneRad 项目管理模块实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Gradio UI 中增加左侧项目侧边栏，实现多项目管理和配置/运行历史持久化，产品名显示为 OneRad。

**Architecture:** 新增 `app/projects.py` 作为项目数据层，使用 SQLite 保存项目列表和运行历史，并在每个项目目录下维护 `project.yaml` 与 `Params_labels.yaml`；`app/ui.py` 重构为左右布局，左侧项目列表，右侧当前项目分析工作区。

**Tech Stack:** Python 3.10+, Gradio 4.x, SQLite3, PyYAML, pytest

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `app/projects.py` | 新建 | 项目 CRUD、SQLite 数据库、`project.yaml`/`Params_labels.yaml` 文件操作、运行历史记录 |
| `app/ui.py` | 修改 | 重构为左右布局，集成项目侧边栏与当前项目工作区 |
| `tests/test_projects.py` | 新建 | `ProjectStore` 的单元测试 |
| `tests/test_ui.py` | 修改/新建 | UI 事件函数测试（若不存在则新建） |
| `README.md` | 修改 | 更新产品名 OneRad 和 UI 使用说明 |

---

## Task 1: 创建项目数据层 `app/projects.py`

**Files:**
- Create: `app/projects.py`
- Test: `tests/test_projects.py`

### Step 1.1: 编写数据库初始化与项目 CRUD 的测试

```python
# tests/test_projects.py
import pytest
import tempfile
import shutil
from pathlib import Path

from app.projects import ProjectStore


@pytest.fixture
def temp_db():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test.db"
    store = ProjectStore(str(db_path))
    yield store, Path(tmp)
    shutil.rmtree(tmp)


def test_create_project_writes_files_and_record(temp_db):
    store, root = temp_db
    project_path = root / "ZHY-ESWA"
    project = store.create_project("ZHY-ESWA", str(project_path), "测试项目")
    assert project["name"] == "ZHY-ESWA"
    assert Path(project["path"]).exists()
    assert (Path(project["path"]) / "project.yaml").exists()
    assert (Path(project["path"]) / "Params_labels.yaml").exists()
    projects = store.list_projects()
    assert len(projects) == 1


def test_list_projects_sorted_by_updated_at(temp_db):
    store, root = temp_db
    p1 = store.create_project("A", str(root / "a"), "")
    p2 = store.create_project("B", str(root / "b"), "")
    projects = store.list_projects()
    assert projects[0]["id"] == p2["id"]
    assert projects[1]["id"] == p1["id"]


def test_delete_project_keeps_directory(temp_db):
    store, root = temp_db
    p = store.create_project("A", str(root / "a"), "")
    store.delete_project(p["id"])
    assert store.load_project(p["id"]) is None
    assert (root / "a").exists()


def test_duplicate_name_raises(temp_db):
    store, root = temp_db
    store.create_project("A", str(root / "a"), "")
    with pytest.raises(ValueError):
        store.create_project("A", str(root / "b"), "")
```

Run: `pytest tests/test_projects.py::test_create_project_writes_files_and_record tests/test_projects.py::test_list_projects_sorted_by_updated_at tests/test_projects.py::test_delete_project_keeps_directory tests/test_projects.py::test_duplicate_name_raises -v`
Expected: 全部 FAIL（`ProjectStore` 不存在）

### Step 1.2: 实现 `ProjectStore` 初始化与表结构

```python
# app/projects.py
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


DEFAULT_DB_DIR = Path.home() / ".onerad"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "projects.db"
DEFAULT_PARAMS_TEMPLATE = Path(__file__).resolve().parent.parent / "config" / "Params_labels.yaml"


class ProjectStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    path TEXT NOT NULL UNIQUE,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    image_dir TEXT,
                    clinical_path TEXT,
                    output_dir TEXT,
                    modality TEXT,
                    covariates TEXT,
                    model TEXT,
                    status TEXT NOT NULL,
                    log_summary TEXT,
                    report_path TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()
```

### Step 1.3: 实现 `create_project`

```python
    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_project(self, name: str, path: str, description: str = "") -> Dict[str, Any]:
        project_path = Path(path).resolve()
        if not project_path.exists():
            project_path.mkdir(parents=True, exist_ok=True)
        if not project_path.is_dir():
            raise ValueError(f"项目路径必须是目录: {path}")

        project_id = str(uuid.uuid4())
        now = self._now()
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "INSERT INTO projects (id, name, path, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (project_id, name, str(project_path), description, now, now),
                )
                conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"项目名或路径已存在: {e}")

        project_yaml_path = project_path / "project.yaml"
        params_yaml_path = project_path / "Params_labels.yaml"

        project_data = {
            "name": name,
            "description": description,
            "path": str(project_path),
            "created_at": now,
            "updated_at": now,
            "analysis": {
                "image_dir": "",
                "clinical_path": "",
                "output_dir": "./outputs",
                "modality": "auto",
                "covariates": "",
                "model": "deepseek-chat",
            },
        }
        with open(project_yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(project_data, f, allow_unicode=True, sort_keys=False)

        if DEFAULT_PARAMS_TEMPLATE.exists():
            shutil.copy(DEFAULT_PARAMS_TEMPLATE, params_yaml_path)
        else:
            with open(params_yaml_path, "w", encoding="utf-8") as f:
                yaml.safe_dump({}, f)

        return {
            "id": project_id,
            "name": name,
            "path": str(project_path),
            "description": description,
            "created_at": now,
            "updated_at": now,
        }
```

Add `import shutil` at top of `app/projects.py`.

### Step 1.4: 实现 `list_projects`、`load_project`、`delete_project`

```python
    def list_projects(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, path, description, created_at, updated_at FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def load_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, name, path, description, created_at, updated_at FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        project = dict(row)
        project_path = Path(project["path"])
        yaml_path = project_path / "project.yaml"
        if yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as f:
                try:
                    data = yaml.safe_load(f) or {}
                except yaml.YAMLError:
                    data = {}
            project["analysis"] = data.get("analysis", self._default_analysis())
        else:
            project["analysis"] = self._default_analysis()
        return project

    def _default_analysis(self) -> Dict[str, str]:
        return {
            "image_dir": "",
            "clinical_path": "",
            "output_dir": "./outputs",
            "modality": "auto",
            "covariates": "",
            "model": "deepseek-chat",
        }

    def delete_project(self, project_id: str) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
```

### Step 1.5: 实现 `save_project_config`

```python
    def save_project_config(self, project_id: str, analysis_config: Dict[str, Any]) -> Dict[str, Any]:
        project = self.load_project(project_id)
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")

        now = self._now()
        project_path = Path(project["path"])
        yaml_path = project_path / "project.yaml"

        project_data = {
            "name": project["name"],
            "description": project.get("description", ""),
            "path": str(project_path),
            "created_at": project["created_at"],
            "updated_at": now,
            "analysis": {
                "image_dir": analysis_config.get("image_dir", ""),
                "clinical_path": analysis_config.get("clinical_path", ""),
                "output_dir": analysis_config.get("output_dir", "./outputs"),
                "modality": analysis_config.get("modality", "auto"),
                "covariates": analysis_config.get("covariates", ""),
                "model": analysis_config.get("model", "deepseek-chat"),
            },
        }
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(project_data, f, allow_unicode=True, sort_keys=False)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            conn.commit()

        return self.load_project(project_id)
```

### Step 1.6: 实现运行历史 `record_run_start` / `record_run_end` / `list_runs`

```python
    def record_run_start(self, project_id: str, analysis_config: Dict[str, Any]) -> str:
        run_id = str(uuid.uuid4())
        now = self._now()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                INSERT INTO runs (id, project_id, image_dir, clinical_path, output_dir,
                                  modality, covariates, model, status, log_summary,
                                  report_path, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    project_id,
                    analysis_config.get("image_dir", ""),
                    analysis_config.get("clinical_path", ""),
                    analysis_config.get("output_dir", ""),
                    analysis_config.get("modality", "auto"),
                    analysis_config.get("covariates", ""),
                    analysis_config.get("model", "deepseek-chat"),
                    "running",
                    "",
                    "",
                    now,
                    None,
                ),
            )
            conn.commit()
        return run_id

    def record_run_end(
        self,
        run_id: str,
        status: str,
        log_summary: str = "",
        report_path: str = "",
    ) -> None:
        now = self._now()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE runs SET status = ?, log_summary = ?, report_path = ?, finished_at = ? WHERE id = ?",
                (status, log_summary, report_path, now, run_id),
            )
            conn.commit()

    def list_runs(self, project_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM runs WHERE project_id = ? ORDER BY started_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]
```

### Step 1.7: 运行项目数据层测试

Run: `pytest tests/test_projects.py -v`
Expected: 全部 PASS

### Step 1.8: 提交

```bash
git add app/projects.py tests/test_projects.py
git commit -m "feat: add project data layer with SQLite and YAML persistence"
```

---

## Task 2: 扩展测试覆盖边界情况

**Files:**
- Modify: `tests/test_projects.py`

### Step 2.1: 添加边界测试

```python
# 追加到 tests/test_projects.py

def test_save_project_config_updates_yaml(temp_db):
    store, root = temp_db
    p = store.create_project("A", str(root / "a"), "")
    updated = store.save_project_config(p["id"], {
        "image_dir": "/data/images",
        "clinical_path": "/data/clinical.csv",
        "output_dir": "./out",
        "modality": "CT",
        "covariates": "age,gender",
        "model": "deepseek-chat",
    })
    assert updated["analysis"]["modality"] == "CT"
    yaml_path = Path(p["path"]) / "project.yaml"
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["analysis"]["covariates"] == "age,gender"


def test_run_history(temp_db):
    store, root = temp_db
    p = store.create_project("A", str(root / "a"), "")
    run_id = store.record_run_start(p["id"], {"image_dir": "/img", "clinical_path": "/clin.csv"})
    store.record_run_end(run_id, "success", "完成", "/report.docx")
    runs = store.list_runs(p["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "success"
    assert runs[0]["report_path"] == "/report.docx"


def test_load_project_returns_default_analysis_for_missing_yaml(temp_db):
    store, root = temp_db
    p = store.create_project("A", str(root / "a"), "")
    (Path(p["path"]) / "project.yaml").unlink()
    loaded = store.load_project(p["id"])
    assert loaded["analysis"]["modality"] == "auto"
```

### Step 2.2: 运行测试

Run: `pytest tests/test_projects.py -v`
Expected: 全部 PASS

### Step 2.3: 提交

```bash
git add tests/test_projects.py
git commit -m "test: cover project config save and run history"
```

---

## Task 3: 重构 `app/ui.py` 为左右布局并集成项目管理

**Files:**
- Modify: `app/ui.py`

### Step 3.1: 修改导入并新增 UI 构建函数

```python
# app/ui.py
import os
import traceback
from pathlib import Path

import gradio as gr

from app.orchestrator import Orchestrator, register_default_handlers
from app.projects import ProjectStore
from app.utils import parse_covariates


def _run_analysis(img_dir, clinical, out_dir, mod, covs, key, m, yaml_path):
    if not img_dir or not img_dir.strip() or not clinical or not clinical.strip():
        return "错误：影像文件夹路径和临床表格路径不能为空", None

    try:
        orch = Orchestrator(
            image_dir=img_dir,
            clinical_path=clinical,
            output_dir=out_dir,
            modality=mod,
            covariates=parse_covariates(covs),
            api_key=key,
            base_url="https://api.deepseek.com/v1",
            model=m,
            yaml_path=yaml_path,
        )
        register_default_handlers(orch)

        logs = []
        def emitter(event):
            logs.append(f"[{event.get('stage', '')}] {event['type']}: {event['message']}")

        orch.set_sse_emitter(emitter)
        for _ in orch.run():
            pass

        report = orch.state.get("report")
        if not report or report.get("success") is False:
            return "\n".join(logs) + "\n错误：流水线执行失败，未能生成报告", None

        report_path = report.get("report_path")
        return "\n".join(logs), report_path
    except Exception:
        return traceback.format_exc(), None
```

### Step 3.2: 实现 `create_ui` 左右布局

```python
def create_ui():
    store = ProjectStore()

    def refresh_projects():
        projects = store.list_projects()
        choices = {p["name"]: p["id"] for p in projects}
        return gr.update(choices=choices if choices else None, value=None)

    def on_project_select(project_id):
        if not project_id:
            return [gr.update()] * 8 + ["", None]
        project = store.load_project(project_id)
        if project is None:
            return [gr.update()] * 8 + ["项目不存在", None]
        analysis = project.get("analysis", {})
        return (
            project_id,
            project["name"],
            analysis.get("image_dir", ""),
            analysis.get("clinical_path", ""),
            analysis.get("output_dir", "./outputs"),
            analysis.get("modality", "auto"),
            analysis.get("covariates", ""),
            analysis.get("model", "deepseek-chat"),
            f"已加载项目: {project['name']}",
            None,
        )

    def on_create_project(name, path, description):
        if not name or not name.strip() or not path or not path.strip():
            return refresh_projects(), "项目名称和路径不能为空", "", ""
        try:
            project = store.create_project(name.strip(), path.strip(), description or "")
            choices = {p["name"]: p["id"] for p in store.list_projects()}
            return (
                gr.update(choices=choices, value=project["id"]),
                f"已创建项目: {project['name']}",
                "",
                "",
            )
        except Exception as e:
            return refresh_projects(), f"创建项目失败: {e}", "", ""

    def on_save_config(project_id, image_dir, clinical_path, output_dir, modality, covariates, model):
        if not project_id:
            return "请先选择一个项目"
        try:
            store.save_project_config(project_id, {
                "image_dir": image_dir or "",
                "clinical_path": clinical_path or "",
                "output_dir": output_dir or "./outputs",
                "modality": modality or "auto",
                "covariates": covariates or "",
                "model": model or "deepseek-chat",
            })
            return "项目配置已保存"
        except Exception as e:
            return f"保存失败: {e}"

    def on_run(project_id, image_dir, clinical_path, output_dir, modality, covariates, api_key, model):
        if not project_id:
            return "请先选择一个项目", None
        config = {
            "image_dir": image_dir or "",
            "clinical_path": clinical_path or "",
            "output_dir": output_dir or "./outputs",
            "modality": modality or "auto",
            "covariates": covariates or "",
            "model": model or "deepseek-chat",
        }
        store.save_project_config(project_id, config)
        project = store.load_project(project_id)
        yaml_path = str(Path(project["path"]) / "Params_labels.yaml")
        run_id = store.record_run_start(project_id, config)
        logs, report_path = _run_analysis(
            config["image_dir"],
            config["clinical_path"],
            config["output_dir"],
            config["modality"],
            config["covariates"],
            api_key,
            config["model"],
            yaml_path,
        )
        status = "success" if report_path else "failed"
        store.record_run_end(run_id, status, logs[-1000:] if isinstance(logs, str) else logs, report_path or "")
        return logs, report_path

    with gr.Blocks(title="OneRad") as demo:
        gr.Markdown("# OneRad")

        current_project_id = gr.State("")
        create_name = gr.State("")
        create_path = gr.State("")
        create_description = gr.State("")

        with gr.Row():
            # 左侧项目侧边栏
            with gr.Column(scale=0, min_width=260):
                gr.Markdown("## 项目")
                btn_new = gr.Button("+ 新建项目")
                project_selector = gr.Radio(label="选择项目", choices={})

                with gr.Row(visible=False) as new_project_row:
                    new_name = gr.Textbox(label="名称")
                    new_path = gr.Textbox(label="目录路径")
                    new_description = gr.Textbox(label="描述")
                    btn_create_confirm = gr.Button("创建")
                    btn_create_cancel = gr.Button("取消")

                status_msg = gr.Textbox(label="状态", interactive=False, lines=1)

            # 右侧工作区
            with gr.Column(scale=1):
                project_title = gr.Markdown("## 当前项目: 未选择")
                with gr.Row():
                    image_dir = gr.Textbox(label="影像文件夹路径")
                    clinical_path = gr.Textbox(label="临床表格路径")
                with gr.Row():
                    output_dir = gr.Textbox(label="输出目录", value="./outputs")
                    modality = gr.Dropdown(choices=["auto", "CT", "MRI"], value="auto", label="模态")
                    covariates = gr.Textbox(label="协变量（逗号分隔）", value="")
                with gr.Row():
                    api_key = gr.Textbox(label="DeepSeek API Key", type="password")
                    model = gr.Textbox(label="模型", value="deepseek-chat")

                with gr.Row():
                    btn_save = gr.Button("保存项目配置")
                    btn_run = gr.Button("运行分析")

                log = gr.Textbox(label="日志", lines=20, interactive=False)
                report_file = gr.File(label="生成报告")

        # 事件绑定
        demo.load(refresh_projects, outputs=[project_selector])

        btn_new.click(lambda: gr.update(visible=True), outputs=[new_project_row])
        btn_create_cancel.click(lambda: gr.update(visible=False), outputs=[new_project_row])
        btn_create_confirm.click(
            on_create_project,
            inputs=[new_name, new_path, new_description],
            outputs=[project_selector, status_msg, new_name, new_path],
        ).then(lambda: gr.update(visible=False), outputs=[new_project_row])

        project_selector.change(
            on_project_select,
            inputs=[project_selector],
            outputs=[
                current_project_id,
                project_title,
                image_dir,
                clinical_path,
                output_dir,
                modality,
                covariates,
                model,
                log,
                report_file,
            ],
        )

        btn_save.click(
            on_save_config,
            inputs=[current_project_id, image_dir, clinical_path, output_dir, modality, covariates, model],
            outputs=[status_msg],
        )

        btn_run.click(
            on_run,
            inputs=[current_project_id, image_dir, clinical_path, output_dir, modality, covariates, api_key, model],
            outputs=[log, report_file],
        )

    return demo


if __name__ == "__main__":
    demo = create_ui()
    demo.launch()
```

注意：`project_title` 是 `gr.Markdown`，Gradio 更新 Markdown 组件需要传字符串。`on_project_select` 返回第二个值是字符串（markdown 内容），与输出列表对应。

### Step 3.3: 修复 `project_title` 更新

如果 Gradio 报错 `Markdown` 不支持 `gr.update(value=...)`，改用 `gr.HTML` 或在 `on_project_select` 中返回完整 Markdown 字符串：

```python
project_title = gr.Markdown("## 当前项目: 未选择")
```

`on_project_select` 返回 `f"## 当前项目: {project['name']}"` 即可。

### Step 3.4: 启动 UI  smoke test

Run: `python -c "from app.ui import create_ui; demo = create_ui(); print('UI created')"`
Expected: 打印 `UI created`，无异常

### Step 3.5: 提交

```bash
git add app/ui.py
git commit -m "feat: add project sidebar and integrate with analysis workspace"
```

---

## Task 4: 编写 UI 行为测试

**Files:**
- Create: `tests/test_ui.py`

### Step 4.1: 测试项目选择回填

```python
# tests/test_ui.py
import sys
import tempfile
import shutil
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.projects import ProjectStore
from app.ui import create_ui


@pytest.fixture
def isolated_store():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "ui_test.db"
    # Patch default store by recreating UI in tests would require dependency injection.
    # Instead test store functions directly; UI tests use gradio internals minimally.
    yield tmp
    shutil.rmtree(tmp)


def test_create_project_flow(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    project = store.create_project("TestProj", str(Path(isolated_store) / "TestProj"), "desc")
    loaded = store.load_project(project["id"])
    assert loaded["name"] == "TestProj"
    assert loaded["analysis"]["output_dir"] == "./outputs"
```

### Step 4.2: 运行测试

Run: `pytest tests/test_ui.py -v`
Expected: PASS

### Step 4.3: 提交

```bash
git add tests/test_ui.py
git commit -m "test: add basic UI store integration test"
```

---

## Task 5: 更新文档

**Files:**
- Modify: `README.md`

### Step 5.1: 更新 README

- 将 `# AutoRadiomics Agent` 保留，但在简介中增加：UI 模式下产品名为 OneRad。
- 在 `### UI` 小节补充：启动后可创建/切换项目，每个项目目录下保存 `project.yaml` 和 `Params_labels.yaml`。

示例修改：

```markdown
# AutoRadiomics Agent (OneRad)

基于影像组学的端到端二分类分析 Agent。支持影像/mask 自动配对、临床表格合并、QC、特征提取、LASSO+Logistic Regression 建模，并输出 Word 报告。
UI 模式下以 **OneRad** 品牌运行，支持左侧项目侧边栏同时管理多个影像组学项目。

...

### UI

```bash
python main.py --ui
```

启动后访问 http://localhost:7860。在 OneRad 界面左侧可新建、切换、删除项目；每个项目目录下会自动保存 `project.yaml`（项目配置）和 `Params_labels.yaml`（影像组学参数）。
```

### Step 5.2: 提交

```bash
git add README.md
git commit -m "docs: update README with OneRad project management UI"
```

---

## Task 6: 全量测试与收尾

### Step 6.1: 运行全部测试

Run: `pytest tests/ -v`
Expected: 全部 PASS（现有测试不应因本次改动失败）

### Step 6.2: 修复任何失败

如果 `tests/test_ui.py` 因 Gradio 版本问题失败，检查 Gradio API 并调整。

### Step 6.3: 提交

```bash
git commit -m "test: verify full suite passes with project management feature"
```

---

## 自我审查清单

1. **Spec 覆盖：** 左侧项目侧边栏（Task 3）、项目目录下保存 `project.yaml` 与 `Params_labels.yaml`（Task 1）、SQLite 运行历史（Task 1）、产品名 OneRad（Task 3/5）均已覆盖。
2. **无占位符：** 所有步骤包含具体代码/命令。
3. **类型一致性：** `ProjectStore` 方法签名在 Task 1 中统一定义，后续 Task 3 直接调用，无歧义。
4. **潜在注意点：**
   - `app/ui.py` 中原 `_run_analysis` 未传 `yaml_path`，Task 3 中补上并优先使用项目目录下的 `Params_labels.yaml`。
   - Gradio 的 `gr.Radio` 更新 `choices` 时传字典 `{label: value}`，与 `project_selector.change` 的输入值对应为 `project_id`。
   - `current_project_id` 使用 `gr.State` 在客户端保存当前项目 ID。
