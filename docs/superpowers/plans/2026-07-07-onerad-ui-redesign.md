# OneRad UI 视觉与布局改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持现有功能不变的前提下，将 `app/ui.py` 的 Gradio 界面按设计文档改造成参考图风格的卡片化、品牌化界面。

**Architecture:** 将样式/图标常量抽离到 `app/ui_style.py`，`app/ui.py` 通过 `gr.Blocks(css=...)` 和 `gr.HTML` 引用这些资源构建新布局；事件处理逻辑复用现有函数，仅调整组件引用。

**Tech Stack:** Python 3.10+, Gradio, SQLite（项目存储已存在）

---

## 文件结构

| 文件 | 用途 |
|------|------|
| `app/ui.py` | 主 UI 入口，改造布局、组件结构和样式类名 |
| `app/ui_style.py` | 新增：SVG 图标、全局 CSS、辅助 HTML 渲染函数 |
| `tests/test_ui.py` | 新增 UI 结构测试 |

---

### Task 1: 为 UI 结构编写测试

**Files:**
- Modify: `tests/test_ui.py`

**背景：** 现有 `tests/test_ui.py` 只测试 `ProjectStore`。新增测试验证 `create_ui()` 能正常构建，并包含新的品牌头部、侧边栏、数据源等关键区块。

- [ ] **Step 1: 编写失败测试**

```python
import shutil
import sys
import tempfile
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
    yield tmp
    shutil.rmtree(tmp)


def test_create_project_flow(isolated_store):
    store = ProjectStore(str(Path(isolated_store) / "db"))
    project = store.create_project("TestProj", str(Path(isolated_store) / "TestProj"), "desc")
    loaded = store.load_project(project["id"])
    assert loaded["name"] == "TestProj"
    assert loaded["analysis"]["output_dir"] == "./outputs"


def test_create_ui_returns_blocks():
    demo = create_ui()
    assert demo is not None
    assert hasattr(demo, "launch")


def test_ui_contains_brand_header():
    demo = create_ui()
    config = demo.get_config_file()
    html_blocks = [c for c in config.get("components", []) if c.get("type") == "html"]
    html_text = " ".join([h.get("props", {}).get("value", "") for h in html_blocks])
    assert "OneRad" in html_text
    assert "医学影像智能分析平台" in html_text


def test_ui_contains_key_sections():
    demo = create_ui()
    config = demo.get_config_file()
    html_blocks = [c for c in config.get("components", []) if c.get("type") == "html"]
    html_text = " ".join([h.get("props", {}).get("value", "") for h in html_blocks])
    assert "项目管理" in html_text
    assert "数据源" in html_text
    assert "分析配置" in html_text
    assert "AI 模型配置" in html_text
    assert "运行日志" in html_text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_ui.py -v`
Expected: 新增的 `test_create_ui_returns_blocks`、`test_ui_contains_brand_header`、`test_ui_contains_key_sections` 失败（当前 UI 缺少这些结构）。

- [ ] **Step 3: 提交**

```bash
git add tests/test_ui.py
git commit -m "test(ui): add structural tests for redesigned OneRad UI"
```

---

### Task 2: 创建样式与图标资源文件

**Files:**
- Create: `app/ui_style.py`

**背景：** 将 SVG 图标和全局 CSS 抽离，避免 `app/ui.py` 过于臃肿，也便于后续单独调整视觉细节。

- [ ] **Step 1: 创建 `app/ui_style.py`**

```python
"""OneRad UI 样式、图标与 HTML 片段资源。"""

from typing import Optional


# ---------------------------------------------------------------------------
# SVG 图标（内联，可在 gr.HTML 或 CSS data URI 中使用）
# ---------------------------------------------------------------------------

LOGO_SVG = """
<svg width="28" height="28" viewBox="0 0 28 28" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="28" height="28" rx="7" fill="#2563EB"/>
  <path d="M7 18L11 14L13.5 17.5L17 10L21 16" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="21" cy="10" r="2" fill="white"/>
</svg>
""".strip()

ICON_FOLDER = """
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
</svg>
""".strip()

ICON_FILE_TEXT = """
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
  <polyline points="14 2 14 8 20 8"/>
  <line x1="16" y1="13" x2="8" y2="13"/>
  <line x1="16" y1="17" x2="8" y2="17"/>
  <polyline points="10 9 9 9 8 9"/>
</svg>
""".strip()

ICON_SETTINGS = """
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="3"/>
  <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
</svg>
""".strip()

ICON_GLOBE = """
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="10"/>
  <line x1="2" y1="12" x2="22" y2="12"/>
  <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
</svg>
""".strip()

ICON_FILE_CODE = """
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>
  <polyline points="14 2 14 8 20 8"/>
  <polyline points="10 13 12 15 10 17"/>
</svg>
""".strip()

ICON_CHECK_CIRCLE = """
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
  <polyline points="22 4 12 14.01 9 11.01"/>
</svg>
""".strip()

ICON_INFO_CIRCLE = """
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="10"/>
  <line x1="12" y1="16" x2="12" y2="12"/>
  <line x1="12" y1="8" x2="12.01" y2="8"/>
</svg>
""".strip()

ICON_X_CIRCLE = """
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="10"/>
  <line x1="15" y1="9" x2="9" y2="15"/>
  <line x1="9" y1="9" x2="15" y2="15"/>
</svg>
""".strip()

ICON_EYE = """
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
  <circle cx="12" cy="12" r="3"/>
</svg>
""".strip()

ICON_EYE_OFF = """
<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
  <line x1="1" y1="1" x2="23" y2="23"/>
</svg>
""".strip()


# ---------------------------------------------------------------------------
# 全局 CSS
# ---------------------------------------------------------------------------

CUSTOM_CSS = """
/* 页面背景 */
.gradio-container {
    background-color: #f5f6f8 !important;
}

/* 隐藏 Gradio 默认标题栏，改由自定义 HTML 头部替代 */
.gradio-container > .main > .wrap > .contain > .tabs,
.gradio-container > .main > .wrap > .contain > h1,
.gradio-container > .main > .wrap > .contain > h2 {
    display: none !important;
}

/* 卡片容器 */
.onerad-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
    height: 100%;
}

/* 品牌头部 */
.onerad-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #ffffff;
    border-bottom: 1px solid #e5e7eb;
    padding: 16px 24px;
    margin-bottom: 20px;
    border-radius: 0 0 12px 12px;
}
.onerad-header-left {
    display: flex;
    align-items: center;
    gap: 12px;
}
.onerad-header-title {
    font-size: 20px;
    font-weight: 700;
    color: #1f2937;
    line-height: 1.2;
}
.onerad-header-subtitle {
    font-size: 13px;
    color: #6b7280;
}
.onerad-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    border-radius: 12px;
    font-size: 12px;
    font-weight: 500;
}
.onerad-badge-gray {
    background: #f3f4f6;
    color: #6b7280;
}
.onerad-badge-green {
    background: #dcfce7;
    color: #16a34a;
}
.onerad-badge-blue {
    background: #dbeafe;
    color: #2563eb;
}

/* 区块标题 */
.onerad-section-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 15px;
    font-weight: 700;
    color: #1f2937;
    margin: 20px 0 12px 0;
}
.onerad-section-title svg {
    color: #2563eb;
}
.onerad-section-title:first-child {
    margin-top: 0;
}

/* 输入框 */
.onerad-input input {
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 10px 12px;
}

/* 按钮 */
.onerad-btn-primary {
    background: #2563eb !important;
    color: #ffffff !important;
    border-radius: 8px !important;
}
.onerad-btn-secondary {
    background: #ffffff !important;
    color: #374151 !important;
    border: 1px solid #e5e7eb !important;
    border-radius: 8px !important;
}
.onerad-btn-new {
    background: #f3f4f6 !important;
    color: #6b7280 !important;
    border: none !important;
    border-radius: 8px !important;
    width: 100%;
}

/* 状态面板 */
.onerad-status {
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 12px;
    background: #ffffff;
}
.onerad-status-title {
    display: flex;
    align-items: center;
    gap: 6px;
    font-weight: 600;
    font-size: 14px;
}
.onerad-status-desc {
    font-size: 12px;
    color: #6b7280;
    margin-top: 4px;
}
.onerad-status-success .onerad-status-title { color: #16a34a; }
.onerad-status-info .onerad-status-title { color: #2563eb; }
.onerad-status-error .onerad-status-title { color: #dc2626; }

/* 日志区 */
.onerad-logs {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 13px;
    background: #f9fafb;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    padding: 12px;
    min-height: 160px;
}
""".strip()


# ---------------------------------------------------------------------------
# HTML 片段辅助函数
# ---------------------------------------------------------------------------

def _inline_svg(svg: str) -> str:
    return svg.replace('"', "'").replace("\n", " ").strip()


def header_html() -> str:
    return f"""
    <div class="onerad-header">
      <div class="onerad-header-left">
        {_inline_svg(LOGO_SVG)}
        <div>
          <div class="onerad-header-title">OneRad</div>
          <div class="onerad-header-subtitle">医学影像智能分析平台</div>
        </div>
      </div>
      <div>
        <span class="onerad-badge onerad-badge-gray">v2.0</span>
        <span class="onerad-badge onerad-badge-green">Ready</span>
      </div>
    </div>
    """.strip()


def section_title_html(icon_svg: str, title: str) -> str:
    return f"""
    <div class="onerad-section-title">
      {_inline_svg(icon_svg)}
      <span>{title}</span>
    </div>
    """.strip()


def project_status_html(status: str, title: str, description: str) -> str:
    if status == "success":
        icon = ICON_CHECK_CIRCLE
        css_class = "onerad-status-success"
    elif status == "error":
        icon = ICON_X_CIRCLE
        css_class = "onerad-status-error"
    else:
        icon = ICON_INFO_CIRCLE
        css_class = "onerad-status-info"
    return f"""
    <div class="onerad-status {css_class}">
      <div class="onerad-status-title">
        {_inline_svg(icon)}
        <span>{title}</span>
      </div>
      <div class="onerad-status-desc">{description}</div>
    </div>
    """.strip()
```

- [ ] **Step 2: 运行测试确认通过**

Run: `pytest tests/test_ui.py -v`
Expected: 之前失败的结构测试仍失败（尚未修改 UI），但无导入错误。

- [ ] **Step 3: 提交**

```bash
git add app/ui_style.py
git commit -m "feat(ui): add style, SVG icons and HTML helpers for OneRad redesign"
```

---

### Task 3: 重构 `app/ui.py` 布局与样式

**Files:**
- Modify: `app/ui.py`

**背景：** 保持所有事件处理函数不变，仅调整组件布局、样式类名和新增品牌头部/区块标题 HTML。

- [ ] **Step 1: 导入样式资源并注入 CSS**

在 `app/ui.py` 顶部新增导入：

```python
from app.ui_style import (
    CUSTOM_CSS,
    header_html,
    section_title_html,
    project_status_html,
    ICON_FOLDER,
    ICON_FILE_TEXT,
    ICON_SETTINGS,
    ICON_GLOBE,
    ICON_FILE_CODE,
)
```

将 `create_ui()` 中的 Blocks 定义改为：

```python
with gr.Blocks(title="OneRad", css=CUSTOM_CSS) as demo:
    gr.HTML(header_html())
```

- [ ] **Step 2: 重构侧边栏为卡片**

将原侧边栏 `gr.Column` 改为带 `elem_classes="onerad-card"` 的卡片，并添加 SVG 区块标题：

```python
with gr.Column(scale=0, min_width=320, elem_classes="onerad-card") as sidebar_col:
    gr.HTML(section_title_html(ICON_FOLDER, "项目管理"))
    btn_new = gr.Button("+ 新建项目", elem_classes="onerad-btn-new")
    # ... 保留其余组件
```

- [ ] **Step 3: 重构主内容区为卡片并添加区块标题**

右侧 `gr.Column` 添加 `elem_classes="onerad-card"`，并在内部使用 `gr.HTML(section_title_html(...))` 划分数据源、分析配置、AI 模型配置、运行日志区块。

- [ ] **Step 4: 更新输入框样式与操作按钮样式**

为关键输入框添加 `elem_classes="onerad-input"`，为保存/分析按钮分别添加 `onerad-btn-secondary` / `onerad-btn-primary`。

- [ ] **Step 5: 更新项目状态显示**

在 `on_project_select` 和 `on_save_config` 等位置，根据配置完整性返回对应的 `project_status_html(...)` HTML 片段，替换原 `status_msg` 的纯文本显示。

- [ ] **Step 6: 运行测试**

Run: `pytest tests/test_ui.py -v`
Expected: 所有测试通过。

- [ ] **Step 7: 提交**

```bash
git add app/ui.py
git commit -m "feat(ui): redesign OneRad layout with cards, brand header and SVG icons"
```

---

### Task 4: 手动验证与回归测试

**Files:**
- Modify: 无

- [ ] **Step 1: 启动 UI 并目测检查**

Run: `python main.py --ui`
Expected: 服务启动在 http://localhost:7860，界面呈现品牌头部、左侧项目卡片、右侧配置卡片、各区块标题与图标。

- [ ] **Step 2: 验证核心功能未回归**

在浏览器中执行：
1. 新建项目
2. 选择项目
3. 填写/保存配置
4. 删除项目

Expected: 所有操作与改造前行为一致，状态提示正常。

- [ ] **Step 3: 运行完整测试套件**

Run: `pytest tests/ -q`
Expected: 全部通过（或仅存在与本次改动无关的失败）。

- [ ] **Step 4: 提交**

```bash
git add docs/superpowers/specs/2026-07-07-onerad-ui-redesign-design.md
# 若 spec 尚未提交则一起提交
git commit -m "test(ui): verify redesigned UI passes manual and automated checks"
```

---

## Self-Review

1. **Spec coverage：**
   - 品牌头部：Task 3 Step 1 + `header_html()`。
   - 卡片化布局：Task 3 Step 2/3 中的 `elem_classes="onerad-card"`。
   - 图标：Task 2 中的 SVG 图标库 + Task 3 中的区块标题。
   - 状态显示：Task 3 Step 5。
   - 保留功能：Task 3 强调事件处理函数不变，Task 4 回归测试验证。
   无遗漏。

2. **Placeholder scan：** 无 TBD/TODO/"later"/"appropriate"。每步包含可执行代码或命令。

3. **Type consistency：** `create_ui()` 返回类型不变；`ProjectStore` API 不变；新增 `ui_style.py` 函数签名一致。
