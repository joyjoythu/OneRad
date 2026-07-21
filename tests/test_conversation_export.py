import json

from app.conversation_export import (
    export_conversation,
    render_markdown,
    write_docx,
)


MESSAGES = [
    {"role": "user", "content": "开始分析", "timestamp": "2026-07-21T04:00:00+00:00"},
    {
        "role": "assistant",
        "content": "好的，先勘察项目。",
        "timestamp": "2026-07-21T04:00:05+00:00",
        "reasoning_content": "先看看目录结构",
        "tool_calls": [
            {"id": "tc1", "name": "list_directory", "args": {"path": "images"}},
        ],
    },
    {"role": "tool", "content": "images/\n  a.nii.gz", "tool_call_id": "tc1"},
    {"role": "assistant", "content": "勘察完成。"},
]


def test_render_markdown_structure():
    md = render_markdown("测试会话", MESSAGES)
    assert md.startswith("# 对话导出：测试会话")
    assert "## 用户" in md
    assert "开始分析" in md
    assert "## 助手" in md
    assert "**思考过程：**" in md
    assert "> 先看看目录结构" in md
    assert "**工具调用：**" in md
    assert "`list_directory`" in md
    # 工具结果通过 tool_call_id 关联到工具名
    assert "### 工具结果：list_directory" in md
    assert "a.nii.gz" in md


def test_render_markdown_skips_system_and_empty():
    md = render_markdown("t", [{"role": "system", "content": "sys"}])
    assert "sys" not in md


def test_export_conversation_writes_md(tmp_path):
    path = export_conversation(str(tmp_path), "我的/会话:标题", MESSAGES, "md")
    assert path.exists()
    assert path.parent.name == "conversation_exports"
    assert path.suffix == ".md"
    # 文件名中的非法字符已清洗
    assert "/" not in path.name and ":" not in path.name
    content = path.read_text(encoding="utf-8")
    assert "开始分析" in content


def test_export_conversation_writes_docx(tmp_path):
    from docx import Document

    path = export_conversation(str(tmp_path), "测试会话", MESSAGES, "docx")
    assert path.exists()
    assert path.suffix == ".docx"
    doc = Document(str(path))
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "对话导出：测试会话" in full_text
    assert "开始分析" in full_text
    assert "思考过程：" in full_text
    assert "工具结果：list_directory" in full_text
    assert "a.nii.gz" in full_text


def test_export_conversation_defaults_to_md(tmp_path):
    path = export_conversation(str(tmp_path), "t", MESSAGES, "other-format")
    assert path.suffix == ".md"
