from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from app import skills
from app.agent.nodes import call_llm
from app.agent.tools import build_tools
from app.llm import (
    build_column_identification_prompt,
    build_id_inference_prompt,
    build_thread_title_prompt,
)
from app.report import ReportAgent
from app.skills import SkillLoadError, load_skill


def _write_skill(root: Path, name: str, content: str) -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_skill_loader_reads_utf8_frontmatter_body_without_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path)
    path = _write_skill(
        tmp_path,
        "hot-skill",
        "---\nname: hot-skill\ndescription: test\n---\n\n# 第一版\n",
    )

    assert load_skill("hot-skill") == "# 第一版"

    path.write_text(
        "---\nname: hot-skill\ndescription: test\n---\n\n# 第二版\n",
        encoding="utf-8",
    )
    assert load_skill("hot-skill") == "# 第二版"


@pytest.mark.parametrize("content", ["", "---\nname: empty\n---\n\n"])
def test_skill_loader_rejects_empty_skill(monkeypatch, tmp_path, content):
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path)
    path = _write_skill(tmp_path, "empty", content)

    with pytest.raises(SkillLoadError) as error:
        load_skill("empty")
    assert str(path) in str(error.value)


def test_skill_loader_reports_missing_file_and_rejects_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(skills, "SKILLS_DIR", tmp_path)

    with pytest.raises(SkillLoadError) as missing:
        load_skill("missing-skill")
    assert str(tmp_path / "missing-skill" / "SKILL.md") in str(missing.value)

    with pytest.raises(SkillLoadError, match="非法 skill 名称"):
        load_skill("../outside")


def test_prompt_builders_read_their_mapped_markdown_skills():
    id_system, id_user = build_id_inference_prompt(["P001_CT", "P001_mask"])
    column_system, column_user = build_column_identification_prompt({
        "n_rows": 2,
        "n_columns": 3,
        "task_hint": "预测复发",
        "columns": [
            {
                "column_name": "patient_id",
                "dtype": "object",
                "non_null": 2,
                "missing_rate": 0.0,
                "n_unique": 2,
                "samples": "P001, P002",
            }
        ],
    })
    title_system, title_user = build_thread_title_prompt("分析这批 MRI")

    assert id_system == load_skill("filename-id")
    assert "P001_CT" in id_user
    assert column_system == load_skill("clinical-columns")
    assert "patient_id" in column_user
    assert title_system == load_skill("thread-title")
    assert "分析这批 MRI" in title_user


def test_main_agent_loads_core_and_radiomics_skills_on_every_call(tmp_path):
    state = {
        "messages": [],
        "project_path": str(tmp_path),
        "base_url": "https://api.deepseek.com/v1",
        "model": "legacy-model",
        "api_key": "fake",
    }

    with (
        patch("app.agent.nodes.load_skill_bundle", side_effect=["bundle-v1", "bundle-v2"]),
        patch("app.agent.nodes.build_tools", return_value={}),
        patch(
            "app.agent.nodes._stream_chat_completion",
            return_value=AIMessage(content="ok"),
        ) as stream,
    ):
        call_llm(state)
        call_llm(state)

    first_messages = stream.call_args_list[0].kwargs["messages"]
    second_messages = stream.call_args_list[1].kwargs["messages"]
    assert isinstance(first_messages[0], SystemMessage)
    assert first_messages[0].content == "bundle-v1"
    assert second_messages[0].content == "bundle-v2"


def test_file_operation_tool_reads_file_operations_skill(tmp_path):
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(content="[]")
    tools = build_tools(str(tmp_path), fake_llm)

    tools["plan_file_operations"].invoke({"instruction": "整理影像"})

    messages = fake_llm.invoke.call_args.args[0]
    assert messages[0].content == load_skill("file-operations")
    assert "整理影像" in messages[1].content


def test_report_polishing_reads_report_writing_skill():
    llm_client = MagicMock()
    llm_client.call.return_value = "polished"

    result = ReportAgent()._polish_methodology("raw methodology", llm_client)

    assert result == "polished"
    assert llm_client.call.call_args.args[0] == load_skill("report-writing")
