# 左侧项目侧边栏常驻列表实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 OneRad 的 Gradio UI 左侧项目管理区从 Dropdown 改为常驻项目列表，支持点击切换、行内删除确认、侧边栏内新建项目。

**Architecture:** 使用 `gr.HTML` 渲染自定义项目列表，内嵌 JS 处理点击事件；通过两个隐藏的 `gr.Textbox`（`elem_id` 分别为 `project-select-bridge` 和 `project-delete-bridge`）作为事件桥，把用户操作传回 Python 回调处理；CSS 集中在 `app/ui_style.py` 中管理。

**Tech Stack:** Python 3.10+, Gradio ~6.19.0, pytest

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `app/ui_style.py` | 新增项目列表相关 CSS 类和 HTML 渲染辅助函数 `project_list_html`。 |
| `app/ui.py` | 重构左侧边栏：移除 Dropdown，新增 `gr.HTML` 项目列表、隐藏事件桥组件、选择/删除回调，并连接新建/删除/选择事件。 |
| `tests/test_ui.py` | 新增/更新测试：验证 CSS 类存在、HTML 列表渲染、事件桥组件存在、删除后列表刷新等。 |

---

### Task 1: 添加项目列表 CSS 样式

**Files:**
- Modify: `app/ui_style.py`
- Test: `tests/test_ui.py`

- [ ] **Step 1: 编写测试，验证 CSS 中包含项目列表相关类名**

```python
# tests/test_ui.py 中添加

def test_project_list_css_classes(isolated_store):
    from app.ui_style import CUSTOM_CSS
    assert ".onerad-project-list" in CUSTOM_CSS
    assert ".onerad-project-item" in CUSTOM_CSS
    assert ".onerad-project-item-active" in CUSTOM_CSS
    assert ".onerad-project-delete" in CUSTOM_CSS
    assert ".onerad-empty-state" in CUSTOM_CSS
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_ui.py::test_project_list_css_classes -v
```

Expected: FAIL，因为 CSS 类名还不存在。

- [ ] **Step 3: 在 `app/ui_style.py` 中添加项目列表 CSS**

在 `CUSTOM_CSS` 字符串末尾、`""".strip()` 之前插入以下内容：

```css
/* 项目列表 */
.onerad-project-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-height: calc(100vh - 300px);
    overflow-y: auto;
    padding-right: 4px;
}
.onerad-project-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px;
    border-radius: 8px;
    background: #f9fafb;
    color: #4b5563;
    font-size: 14px;
    cursor: pointer;
    transition: background-color 0.15s ease, color 0.15s ease;
}
.onerad-project-item:hover {
    background: #f3f4f6;
}
.onerad-project-item-active,
.onerad-project-item-active:hover {
    background: #2563eb;
    color: #ffffff;
}
.onerad-project-item-active .onerad-project-delete {
    color: #ffffff;
}
.onerad-project-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    margin-left: 8px;
}
.onerad-project-delete {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 4px;
    color: #9ca3af;
    font-size: 16px;
    line-height: 1;
    margin-left: 8px;
}
.onerad-project-delete:hover {
    background: rgba(220, 38, 38, 0.1);
    color: #dc2626;
}
.onerad-empty-state {
    padding: 20px 12px;
    text-align: center;
    color: #9ca3af;
    font-size: 13px;
    background: #f9fafb;
    border-radius: 8px;
}
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_ui.py::test_project_list_css_classes -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui_style.py tests/test_ui.py
git commit -m "feat(ui): add project list CSS classes"
```

---

### Task 2: 添加项目列表 HTML 渲染辅助函数

**Files:**
- Modify: `app/ui_style.py`
- Test: `tests/test_ui.py`

- [ ] **Step 1: 编写测试，验证 HTML 渲染行为**

```python
# tests/test_ui.py 中添加

from app.ui_style import project_list_html


def test_project_list_html_renders_projects():
    projects = [
        {"id": "proj-1", "name": "AutoRadiomic-A"},
        {"id": "proj-2", "name": "ZHY-ESWA"},
    ]
    html_text = project_list_html(projects, selected_id="proj-1")
    assert "AutoRadiomic-A" in html_text
    assert "ZHY-ESWA" in html_text
    assert 'data-project-id="proj-1"' in html_text
    assert 'data-project-id="proj-2"' in html_text
    assert "onerad-project-item-active" in html_text
    # 只有选中的项目才有 active 类
    assert html_text.count("onerad-project-item-active") == 1


def test_project_list_html_escapes_name():
    projects = [{"id": "proj-1", "name": "<script>alert(1)</script>"}]
    html_text = project_list_html(projects, selected_id="proj-1")
    assert "<script>" not in html_text
    assert "&lt;script&gt;" in html_text


def test_project_list_html_empty_state():
    html_text = project_list_html([], selected_id="")
    assert "onerad-empty-state" in html_text
    assert "暂无项目" in html_text
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_ui.py::test_project_list_html_renders_projects tests/test_ui.py::test_project_list_html_escapes_name tests/test_ui.py::test_project_list_html_empty_state -v
```

Expected: FAIL，`project_list_html` 未定义。

- [ ] **Step 3: 在 `app/ui_style.py` 中实现 `project_list_html`**

在 `project_status_html` 函数之后添加：

```python
from typing import Any, Dict, List


def project_list_html(projects: List[Dict[str, Any]], selected_id: str = "") -> str:
    """渲染左侧项目列表 HTML，含选择/删除交互所需的 data 属性。"""
    if not projects:
        return '<div class="onerad-empty-state">暂无项目，点击上方按钮创建</div>'

    script = """
    <script>
    window.oneradSelectProject = function(el) {
        var id = el.getAttribute('data-project-id');
        var input = document.getElementById('project-select-bridge');
        if (!input) return;
        input.value = id;
        input.dispatchEvent(new Event('input', {bubbles: true}));
    };
    window.oneradDeleteProject = function(e, el) {
        e.stopPropagation();
        var id = el.getAttribute('data-project-id');
        if (!confirm('确定要删除该项目吗？')) return;
        var input = document.getElementById('project-delete-bridge');
        if (!input) return;
        input.value = id;
        input.dispatchEvent(new Event('input', {bubbles: true}));
    };
    </script>
    """.strip()

    items = []
    for p in projects:
        active_class = " onerad-project-item-active" if p["id"] == selected_id else ""
        pid = html.escape(p["id"])
        pname = html.escape(p["name"])
        items.append(f"""
        <div class="onerad-project-item{active_class}" data-project-id="{pid}" onclick="window.oneradSelectProject(this)">
            <span>📁</span>
            <span class="onerad-project-name">{pname}</span>
            <span class="onerad-project-delete" data-project-id="{pid}" onclick="window.oneradDeleteProject(event, this)">×</span>
        </div>
        """)

    list_html = "".join(items)
    return f'{script}\n<div class="onerad-project-list">{list_html}</div>'
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_ui.py::test_project_list_html_renders_projects tests/test_ui.py::test_project_list_html_escapes_name tests/test_ui.py::test_project_list_html_empty_state -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui_style.py tests/test_ui.py
git commit -m "feat(ui): add project list HTML renderer with XSS escaping"
```

---

### Task 3: 重构 `app/ui.py` 左侧边栏

**Files:**
- Modify: `app/ui.py`
- Test: `tests/test_ui.py`

- [ ] **Step 1: 编写测试，验证 UI 中包含项目列表 HTML 和事件桥组件**

```python
# tests/test_ui.py 中添加

def test_ui_renders_project_list(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    store.create_project("TestProj", str(Path(isolated_store) / "TestProj"), "desc")
    demo = create_ui(store=store)
    config = demo.get_config_file()
    textboxes = [c for c in config.get("components", []) if c.get("type") == "textbox"]
    html_blocks = [c for c in config.get("components", []) if c.get("type") == "html"]

    # 找到事件桥文本框
    select_bridges = [t for t in textboxes if t.get("props", {}).get("elem_id") == "project-select-bridge"]
    delete_bridges = [t for t in textboxes if t.get("props", {}).get("elem_id") == "project-delete-bridge"]
    assert len(select_bridges) == 1
    assert len(delete_bridges) == 1

    # HTML 中包含项目列表和项目名称
    html_text = _html_text(demo)
    assert "onerad-project-list" in html_text
    assert "TestProj" in html_text
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
pytest tests/test_ui.py::test_ui_renders_project_list -v
```

Expected: FAIL，因为 `app/ui.py` 尚未重构。

- [ ] **Step 3: 修改 `app/ui.py` 导入和重构左侧边栏**

**导入更新：**

```python
from app.ui_style import (
    CUSTOM_CSS,
    header_html,
    section_title_html,
    project_status_html,
    project_list_html,
    ICON_FOLDER,
    ICON_SETTINGS,
    ICON_GLOBE,
    ICON_FILE_CODE,
)
```

**新增/修改回调函数：**

在 `create_ui` 内部、返回 `demo` 之前，添加以下辅助函数（替换原 `refresh_projects` 等逻辑）：

```python
    def _refresh_project_list(selected_id: str = ""):
        projects = store.list_projects()
        return gr.update(value=project_list_html(projects, selected_id))

    def _on_select_bridge(project_id):
        if not project_id:
            return [gr.update()] * 9 + [
                _config_status_html("", ""),
                None,
            ]
        return on_project_select(project_id)

    def _on_delete_bridge(project_id, current_id):
        if not project_id:
            return (
                gr.update(),  # project_list
                gr.update(),  # current_project_id
                gr.update(),  # project_title
                gr.update(),  # image_dir
                gr.update(),  # clinical_path
                gr.update(),  # output_dir
                gr.update(),  # modality
                gr.update(),  # covariates
                gr.update(),  # model
                gr.update(),  # api_key
                project_status_html("error", "删除失败", "未获取到项目 ID"),
                gr.update(),  # report_file
            )
        try:
            store.delete_project(project_id)
        except Exception as e:
            return (
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                project_status_html("error", "删除项目失败", str(e)),
                gr.update(),
            )

        projects = store.list_projects()
        if not projects:
            # 删除后无项目，清空右侧
            return (
                _refresh_project_list(""),
                "",
                "## 当前项目: 未选择",
                "", "", "./outputs", "auto", "", "deepseek-chat", "",
                project_status_html("info", "未选择项目", "请从左侧选择或新建项目"),
                None,
            )

        # 如果被删的是当前项目，自动选择第一个；否则保持当前项目
        next_id = projects[0]["id"] if project_id == current_id else current_id
        select_updates = list(on_project_select(next_id))
        return (
            _refresh_project_list(next_id),
            *select_updates,
        )
```

**左侧边栏 UI 替换：**

将原：

```python
            with gr.Column(scale=0, min_width=320, elem_classes="onerad-card") as sidebar_col:
                gr.HTML(section_title_html(ICON_FOLDER, "项目管理"))
                with gr.Row():
                    btn_new = gr.Button("+ 新建项目", scale=1, elem_classes="onerad-btn-new")
                    btn_delete = gr.Button("删除", scale=0, min_width=60)

                project_selector = gr.Dropdown(label="选择项目", choices=[], value=None)

                with gr.Row(visible=False) as new_project_row:
                    ...

                status_msg = gr.HTML()
```

替换为：

```python
            with gr.Column(scale=0, min_width=320, elem_classes="onerad-card") as sidebar_col:
                gr.HTML(section_title_html(ICON_FOLDER, "项目"))

                with gr.Row():
                    btn_new = gr.Button("+ 新建项目", scale=1, elem_classes="onerad-btn-new")

                with gr.Row(visible=False) as new_project_row:
                    with gr.Column():
                        new_name = gr.Textbox(label="名称", elem_classes="onerad-input")
                        new_path = gr.Textbox(label="目录路径", elem_classes="onerad-input")
                        new_description = gr.Textbox(label="描述", elem_classes="onerad-input")
                        with gr.Row():
                            btn_create_confirm = gr.Button("创建")
                            btn_create_cancel = gr.Button("取消")

                # 项目列表（HTML 自定义）
                project_list = gr.HTML(value=project_list_html([], ""), elem_classes="onerad-project-list-container")

                # JS 事件桥：隐藏在页面中
                select_bridge = gr.Textbox(elem_id="project-select-bridge", visible=False)
                delete_bridge = gr.Textbox(elem_id="project-delete-bridge", visible=False)

                status_msg = gr.HTML()
```

- [ ] **Step 4: 更新事件绑定**

删除原 `demo.load(refresh_projects, outputs=[project_selector])`。

新增 `demo.load(_refresh_project_list, outputs=[project_list])`。

修改 `on_create_project` 的返回值，使其刷新项目列表：

```python
    def on_create_project(name, path, description):
        if not name or not name.strip() or not path or not path.strip():
            return (
                _refresh_project_list(""),
                project_status_html("error", "创建失败", "项目名称和路径不能为空"),
                "",
                "",
            )
        try:
            project = store.create_project(name.strip(), path.strip(), description or "")
            return (
                _refresh_project_list(project["id"]),
                _config_status_html("", ""),
                "",
                "",
            )
        except Exception as e:
            return (
                _refresh_project_list(""),
                project_status_html("error", "创建项目失败", str(e)),
                "",
                "",
            )
```

修改 `btn_create_confirm.click` 的输出，加入 `project_list`：

```python
        btn_create_confirm.click(
            on_create_project,
            inputs=[new_name, new_path, new_description],
            outputs=[project_list, status_msg, new_name, new_path],
        ).then(lambda: gr.update(visible=False), outputs=[new_project_row])
```

删除原 `btn_delete.click(...)` 绑定，改为监听 `delete_bridge.change`：

```python
        delete_bridge.change(
            _on_delete_bridge,
            inputs=[delete_bridge, current_project_id],
            outputs=[
                project_list,
                current_project_id,
                project_title,
                image_dir,
                clinical_path,
                output_dir,
                modality,
                covariates,
                model,
                api_key,
                status_msg,
                report_file,
            ],
        )
```

将原 `project_selector.change(...)` 改为监听 `select_bridge.change`：

```python
        select_bridge.change(
            _on_select_bridge,
            inputs=[select_bridge],
            outputs=[
                current_project_id,
                project_title,
                image_dir,
                clinical_path,
                output_dir,
                modality,
                covariates,
                model,
                api_key,
                status_msg,
                report_file,
            ],
        )
```

- [ ] **Step 5: 运行测试，确认通过**

```bash
pytest tests/test_ui.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/ui.py tests/test_ui.py
git commit -m "feat(ui): replace project dropdown with persistent sidebar list"
```

---

### Task 4: 更新测试断言并补充删除/选择测试

**Files:**
- Modify: `tests/test_ui.py`

- [ ] **Step 1: 更新旧测试断言**

原测试 `test_ui_contains_key_sections` 断言 `"项目管理" in html_text`，现在标题已改为 `"项目"`。更新断言：

```python
def test_ui_contains_key_sections(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    demo = create_ui(store=store)
    html_text = _html_text(demo)
    assert "项目" in html_text
    assert "数据源" in html_text
    assert "分析配置" in html_text
    assert "AI 模型配置" in html_text
    assert "运行日志" in html_text
```

- [ ] **Step 2: 添加删除后列表刷新测试**

```python
def test_delete_project_refreshes_list(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    project = store.create_project("ToDelete", str(Path(isolated_store) / "ToDelete"), "")
    demo = create_ui(store=store)

    html_text = _html_text(demo)
    assert "ToDelete" in html_text

    # 模拟删除桥事件回调
    from app.ui import create_ui
    # 通过调用底层 store 删除，验证 UI 不再渲染（测试 HTML 渲染逻辑）
    store.delete_project(project["id"])
    projects = store.list_projects()
    from app.ui_style import project_list_html
    html_after = project_list_html(projects, "")
    assert "ToDelete" not in html_after
    assert "onerad-empty-state" in html_after
```

- [ ] **Step 3: 运行测试，确认通过**

```bash
pytest tests/test_ui.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_ui.py
git commit -m "test(ui): update assertions and add delete refresh test"
```

---

### Task 5: 全量回归测试

**Files:**
- Run: 全量测试

- [ ] **Step 1: 运行 UI 相关测试**

```bash
pytest tests/test_ui.py tests/test_projects.py tests/test_smoke.py -v
```

Expected: PASS

- [ ] **Step 2: 运行全部测试**

```bash
pytest tests/ -v
```

Expected: PASS（或至少不因本次改动引入新失败）

- [ ] **Step 3: Commit**

```bash
git add .
git commit -m "test: regression tests pass for sidebar project list"
```

---

### Task 6: 本地手动验证（可选但推荐）

**Files:**
- Run: `main.py --ui`

- [ ] **Step 1: 启动 UI**

```bash
python main.py --ui
```

- [ ] **Step 2: 手动验证以下场景**

1. 侧边栏显示"项目"标题和"+ 新建项目"按钮。
2. 已有项目直接列在侧边栏。
3. 点击项目行，右侧加载对应配置，当前行蓝色高亮。
4. 点击行尾 ×，弹出确认框；确认后项目消失，列表刷新。
5. 删除最后一个项目后，列表显示"暂无项目"空状态。
6. 点击"+ 新建项目"展开表单，填写后创建，新项目出现在列表顶部。
7. 页面高度较小时，项目列表可独立滚动。

- [ ] **Step 3: 记录结果**

若手动验证发现问题，回到对应 Task 修复；无问题则结束。

---

## 自审检查

### Spec 覆盖

| 需求 | 对应 Task |
|------|-----------|
| 左侧常驻项目列表 | Task 2 + Task 3 |
| 点击切换项目 | Task 3（select_bridge + `_on_select_bridge`） |
| 行尾 × 删除 + 确认弹窗 | Task 2（JS）+ Task 3（delete_bridge + `_on_delete_bridge`） |
| 仅显示项目名称 | Task 2（`project_list_html`） |
| 蓝色背景高亮当前项 | Task 1（CSS）+ Task 2（`selected_id` 判断） |
| 侧边栏内新建表单 | Task 3（保留现有新建表单并连接列表刷新） |
| 空状态提示 | Task 2（`project_list_html`） |
| 项目数量无上限 | Task 2（动态 HTML）+ Task 1（滚动） |

### Placeholder 扫描

- 无 "TBD"、"TODO"、"implement later"。
- 每个步骤包含实际代码或命令。
- 测试代码完整可运行。

### 类型一致性

- 函数名：`project_list_html`、`_refresh_project_list`、`_on_select_bridge`、`_on_delete_bridge` 在全文中一致。
- `elem_id`：`project-select-bridge` 和 `project-delete-bridge` 在 JS 和 Python 中一致。
- 回调输出数量与组件数量一致。
