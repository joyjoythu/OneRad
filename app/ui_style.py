"""OneRad UI 样式、图标与 HTML 片段资源。"""

import html
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# 项目列表 JS bridge 输入框 ID（与 app/ui.py 保持一致）
# ---------------------------------------------------------------------------
PROJECT_SELECT_BRIDGE_ID = "project-select-bridge"
PROJECT_DELETE_BRIDGE_ID = "project-delete-bridge"


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
/* 注意：以下选择器基于 gradio==6.19.0 的 DOM 结构验证，升级后可能失效 */
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
    cursor: pointer;
}
.onerad-project-delete:hover {
    background: rgba(220, 38, 38, 0.1);
    color: #dc2626;
}
.onerad-project-item-active .onerad-project-delete:hover {
    color: #ffffff;
    background: rgba(255, 255, 255, 0.2);
}
.onerad-empty-state {
    padding: 20px 12px;
    text-align: center;
    color: #9ca3af;
    font-size: 13px;
    background: #f9fafb;
    border-radius: 8px;
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
      <span>{html.escape(title)}</span>
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
        <span>{html.escape(title)}</span>
      </div>
      <div class="onerad-status-desc">{html.escape(description)}</div>
    </div>
    """.strip()


def project_list_html(projects: List[Dict[str, Any]], selected_id: str = "") -> str:
    """渲染左侧项目列表 HTML，含选择/删除交互所需的 data 属性。"""
    if not projects:
        return """
        <div class="onerad-project-list">
          <div class="onerad-empty-state">暂无项目，点击上方按钮创建</div>
        </div>
        """.strip()

    select_onclick = (
        "var input=document.getElementById('project-select-bridge');"
        "if(!input)return;input.value=this.getAttribute('data-project-id');"
        "input.dispatchEvent(new Event('input',{bubbles:true}));"
    )
    delete_onclick = (
        "event.stopPropagation();"
        "if(!confirm('确定要删除该项目吗？'))return;"
        "var input=document.getElementById('project-delete-bridge');"
        "if(!input)return;input.value=this.getAttribute('data-project-id');"
        "input.dispatchEvent(new Event('input',{bubbles:true}));"
    )

    items = []
    for p in projects:
        active_class = " onerad-project-item-active" if p["id"] == selected_id else ""
        pid = html.escape(p["id"], quote=True)
        pname = html.escape(p["name"], quote=True)
        items.append(f"""
        <div class="onerad-project-item{active_class}" data-project-id="{pid}" onclick="{select_onclick}">
            <span>📁</span>
            <span class="onerad-project-name">{pname}</span>
            <span class="onerad-project-delete" data-project-id="{pid}" onclick="{delete_onclick}">×</span>
        </div>
        """)

    list_html = "".join(items)
    return f"""
    <div class="onerad-project-list">{list_html}</div>
    """.strip()
