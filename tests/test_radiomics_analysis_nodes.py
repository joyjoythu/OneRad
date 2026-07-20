import json
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.nodes import process_tool_calls, execute_confirmed
from app.agent.state import AgentState


def _make_project(tmp_path, n=60, extra_binary=False):
    ids = [f"P{i:03d}" for i in range(n)]
    rng = np.random.RandomState(42)
    label = np.array([i % 2 for i in range(n)])
    feat = pd.DataFrame({"patient_id": ids})
    for j in range(6):
        feat[f"original_sig_{j}"] = rng.randn(n) + label * 1.5
    feat.to_csv(tmp_path / "features.csv", index=False)
    # 当需要构造标签列歧义时，避免使用会被自动识别的 "Label" 列名。
    label_name = "group1" if extra_binary else "Label"
    clin = pd.DataFrame({"patient_id": ids, label_name: label})
    if extra_binary:
        clin["group2"] = rng.randint(0, 2, n)
    clin.to_csv(tmp_path / "clinical.csv", index=False)


def _tool_call_state(tmp_path, args):
    return AgentState(
        messages=[AIMessage(content="", tool_calls=[{
            "id": "tc-a1",
            "name": "run_radiomics_analysis",
            "args": args,
        }])],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
    )


def _run_process(state):
    with patch("app.agent.nodes._resolve_api_key", return_value=""), \
         patch("app.agent.nodes.ChatOpenAI") as mock_llm_cls:
        mock_llm_cls.return_value = MagicMock()
        return process_tool_calls(state)


def test_process_run_radiomics_analysis_sets_interrupt(tmp_path):
    _make_project(tmp_path)
    state = _tool_call_state(tmp_path, {
        "feature_csv": "features.csv", "clinical": "clinical.csv"})
    result = _run_process(state)
    assert result["interrupt_type"] == "radiomics_analysis"
    pending = result["pending_radiomics_analysis"]
    assert pending["tool_call_id"] == "tc-a1"
    assert pending["label_col"] == "Label"
    assert pending["n_matched"] == 60
    assert result["messages"] == []  # 确认类工具不产生 ToolMessage


def test_process_run_radiomics_analysis_clarification_passthrough(tmp_path):
    _make_project(tmp_path, extra_binary=True)
    state = _tool_call_state(tmp_path, {
        "feature_csv": "features.csv", "clinical": "clinical.csv"})
    result = _run_process(state)
    assert result["interrupt_type"] is None
    assert "pending_radiomics_analysis" not in result
    assert len(result["messages"]) == 1
    content = json.loads(result["messages"][0].content)
    assert content["status"] == "need_clarification"


def test_execute_confirmed_radiomics_analysis(tmp_path):
    fake_result = {
        "success": True,
        "message": "分析完成",
        "n_matched": 60,
        "analysis_result": {
            "n_samples": 60,
            "selected_features": ["original_sig_0"],
            "metrics": {"auc": 0.9, "auc_ci": [0.8, 0.99]},
            "oof_probabilities": [0.1] * 60,  # 大数组不得进入摘要
        },
        "outputs": {"report_docx": "out/AutoRadiomics_Report.docx"},
    }
    state = AgentState(
        messages=[],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_analysis",
        confirmed=True,
        pending_radiomics_analysis={
            "tool_call_id": "tc-a1",
            "feature_csv": str(tmp_path / "features.csv"),
            "clinical": str(tmp_path / "clinical.csv"),
            "id_col": "patient_id",
            "label_col": "Label",
            "covariates": [],
            "output_dir": str(tmp_path / "radiomics_analysis"),
        },
    )
    with patch("app.agent.nodes.run_radiomics_cv_analysis",
               return_value=fake_result) as mock_run:
        result = execute_confirmed(state)

    assert mock_run.call_count == 1
    kwargs = mock_run.call_args.kwargs
    assert kwargs["label_col"] == "Label"
    content = json.loads(result["messages"][0].content)
    assert content["success"] is True
    assert content["metrics"]["auc"] == 0.9
    assert content["selected_features"] == ["original_sig_0"]
    assert "oof_probabilities" not in json.dumps(content)
    assert result["interrupt_type"] is None
    assert result["pending_radiomics_analysis"] is None


def test_execute_confirmed_radiomics_analysis_failure(tmp_path):
    state = AgentState(
        messages=[],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_analysis",
        confirmed=True,
        pending_radiomics_analysis={
            "tool_call_id": "tc-a1",
            "feature_csv": str(tmp_path / "features.csv"),
            "clinical": str(tmp_path / "clinical.csv"),
            "id_col": "patient_id",
            "label_col": "Label",
            "output_dir": str(tmp_path / "radiomics_analysis"),
        },
    )
    with patch("app.agent.nodes.run_radiomics_cv_analysis",
               side_effect=RuntimeError("boom")):
        result = execute_confirmed(state)
    content = json.loads(result["messages"][0].content)
    assert content["success"] is False
    assert "boom" in content["error"]
    assert result["interrupt_type"] is None


def test_execute_confirmed_radiomics_analysis_missing_pending(tmp_path):
    state = AgentState(
        messages=[AIMessage(content="", tool_calls=[{
            "id": "tc-a9", "name": "run_radiomics_analysis", "args": {}}])],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_analysis",
        confirmed=True,
        pending_radiomics_analysis=None,
    )
    result = execute_confirmed(state)
    content = json.loads(result["messages"][0].content)
    assert "Missing pending radiomics analysis" in content["error"]
    assert result["interrupt_type"] is None


def test_execute_confirmed_radiomics_analysis_cancelled(tmp_path):
    state = AgentState(
        messages=[],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_analysis",
        confirmed=False,
        pending_radiomics_analysis={
            "tool_call_id": "tc-a1",
            "feature_csv": str(tmp_path / "features.csv"),
            "clinical": str(tmp_path / "clinical.csv"),
            "output_dir": str(tmp_path / "radiomics_analysis"),
        },
    )
    result = execute_confirmed(state)
    # 取消时返回 ToolMessage + HumanMessage（告知 LLM 不要重试）
    assert len(result["messages"]) == 2
    content = json.loads(result["messages"][0].content)
    assert content["cancelled"] is True
    assert isinstance(result["messages"][1], HumanMessage)
    assert result["interrupt_type"] is None
    assert result["pending_radiomics_analysis"] is None
