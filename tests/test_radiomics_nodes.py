import json
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.messages import AIMessage, ToolMessage
from app.agent.nodes import process_tool_calls, execute_confirmed
from app.agent.state import AgentState


def test_process_discover_radiomics_pairs(tmp_path):
    state = AgentState(
        messages=[
            AIMessage(content="", tool_calls=[{
                "id": "tc1",
                "name": "discover_radiomics_pairs",
                "args": {}
            }])
        ],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
    )
    (tmp_path / "images").mkdir()
    (tmp_path / "masks").mkdir()

    with patch("app.agent.nodes._resolve_api_key", return_value=""), \
         patch("app.agent.nodes.ChatOpenAI") as mock_llm_cls:
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm
        result = process_tool_calls(state)

    assert result["interrupt_type"] == "radiomics_plan"
    assert result["pending_radiomics_plan"]["tool_call_id"] == "tc1"


def test_execute_confirmed_radiomics_plan(tmp_path):
    state = AgentState(
        messages=[],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_plan",
        confirmed=True,
        pending_radiomics_plan={
            "tool_call_id": "tc1",
            "result": {"success": True, "pairs": {"high": [], "medium": [], "low": []}}
        },
    )

    result = execute_confirmed(state)
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ToolMessage)
    content = json.loads(result["messages"][0].content)
    assert content["result"]["success"] is True
    assert result["interrupt_type"] is None


def test_process_extract_radiomics_features(tmp_path):
    import yaml
    yaml_path = tmp_path / "Params_labels.yaml"
    yaml.safe_dump({"setting": {"label": 1}}, yaml_path.open("w"))
    img = tmp_path / "images" / "case_001_T1.nii.gz"
    mask = tmp_path / "masks" / "case_001_T1.nii.gz"
    img.parent.mkdir(parents=True)
    mask.parent.mkdir(parents=True)
    img.write_text("img")
    mask.write_text("mask")

    state = AgentState(
        messages=[
            AIMessage(content="", tool_calls=[{
                "id": "tc2",
                "name": "extract_radiomics_features",
                "args": {
                    "pairs": [{"patient_id": "case_001", "image_path": str(img), "mask_path": str(mask)}],
                    "yaml_path": str(yaml_path),
                },
            }])
        ],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
    )

    with patch("app.agent.nodes._resolve_api_key", return_value=""), \
         patch("app.agent.nodes.ChatOpenAI") as mock_llm_cls:
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm
        result = process_tool_calls(state)

    assert result["interrupt_type"] == "radiomics_execution"
    assert result["pending_radiomics_execution"]["tool_call_id"] == "tc2"


def test_execute_confirmed_radiomics_execution_failure(tmp_path):
    state = AgentState(
        messages=[],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_execution",
        confirmed=True,
        pending_radiomics_execution={
            "tool_call_id": "tc2",
            "pairs": [{"patient_id": "case_001", "image_path": "images/case_001.nii.gz", "mask_path": "masks/case_001.nii.gz"}],
            "yaml_path": "Params_labels.yaml",
            "output_dir": str(tmp_path / "radiomics_features"),
        },
    )

    with patch("app.agent.nodes.FeatureAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.run.side_effect = RuntimeError("feature extraction failed")
        mock_agent_cls.return_value = mock_agent
        result = execute_confirmed(state)

    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ToolMessage)
    content = json.loads(result["messages"][0].content)
    assert content["success"] is False
    assert "feature extraction failed" in content["error"]


def test_execute_confirmed_radiomics_execution_cancelled(tmp_path):
    state = AgentState(
        messages=[],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_execution",
        confirmed=False,
        pending_radiomics_execution={
            "tool_call_id": "tc2",
            "pairs": [],
            "yaml_path": "Params_labels.yaml",
            "output_dir": str(tmp_path / "radiomics_features"),
        },
    )

    result = execute_confirmed(state)
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ToolMessage)
    content = json.loads(result["messages"][0].content)
    assert content.get("cancelled") is True


def test_execute_confirmed_radiomics_execution(tmp_path):
    import yaml
    yaml_path = tmp_path / "Params_labels.yaml"
    yaml.safe_dump({"setting": {"label": 1}}, yaml_path.open("w"))

    img = tmp_path / "images" / "case_001_T1.nii.gz"
    mask = tmp_path / "masks" / "case_001_T1.nii.gz"
    img.parent.mkdir(parents=True)
    mask.parent.mkdir(parents=True)
    img.write_text("img")
    mask.write_text("mask")

    state = AgentState(
        messages=[],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_execution",
        confirmed=True,
        pending_radiomics_execution={
            "tool_call_id": "tc2",
            "pairs": [{"patient_id": "case_001", "image_path": str(img), "mask_path": str(mask)}],
            "yaml_path": str(yaml_path),
            "output_dir": str(tmp_path / "radiomics_features"),
        },
    )

    with patch("app.agent.nodes.FeatureAgent") as mock_agent_cls:
        mock_agent = MagicMock()
        mock_agent.run.return_value = {"success": True, "feature_path": "..."}
        mock_agent_cls.return_value = mock_agent
        result = execute_confirmed(state)

    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ToolMessage)
    assert result["interrupt_type"] is None
    mock_agent.run.assert_called_once()


def test_process_discover_radiomics_pairs_returns_error_when_images_missing(tmp_path):
    state = AgentState(
        messages=[
            AIMessage(content="", tool_calls=[{
                "id": "tc1",
                "name": "discover_radiomics_pairs",
                "args": {}
            }])
        ],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
    )

    with patch("app.agent.nodes._resolve_api_key", return_value=""), \
         patch("app.agent.nodes.ChatOpenAI") as mock_llm_cls:
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm
        result = process_tool_calls(state)

    assert result["interrupt_type"] is None
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ToolMessage)
    content = json.loads(result["messages"][0].content)
    assert content.get("success") is False
    assert "error" in content or "message" in content


def test_process_extract_radiomics_features_returns_error_when_yaml_missing(tmp_path):
    state = AgentState(
        messages=[
            AIMessage(content="", tool_calls=[{
                "id": "tc2",
                "name": "extract_radiomics_features",
                "args": {
                    "pairs": [{"patient_id": "case_001", "image_path": "images/case_001.nii.gz", "mask_path": "masks/case_001.nii.gz"}],
                    "yaml_path": "missing_params.yaml",
                },
            }])
        ],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
    )

    with patch("app.agent.nodes._resolve_api_key", return_value=""), \
         patch("app.agent.nodes.ChatOpenAI") as mock_llm_cls:
        mock_llm = MagicMock()
        mock_llm_cls.return_value = mock_llm
        result = process_tool_calls(state)

    assert result["interrupt_type"] is None
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], ToolMessage)
    content = json.loads(result["messages"][0].content)
    assert content.get("success") is False
    assert "error" in content
