import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import h5py
import numpy as np
import pandas as pd
import yaml
from langchain_core.messages import AIMessage

from app.agent.nodes import process_tool_calls, execute_confirmed
from app.radiomics_discovery import discover_pairs
from app.feature import FeatureAgent


def test_discovery_to_feature_agent_with_mocked_extractor(tmp_path, monkeypatch):
    """Integration test of discovery + FeatureAgent with the actual radiomics computation mocked.

    Real PyRadiomics extraction requires real NIfTI data and the dependency may not be
    available in all test environments, so ``app.feature.cir_get_features`` is mocked to
    return a single known feature value.
    """
    (tmp_path / "images" / "case_001").mkdir(parents=True)
    (tmp_path / "masks" / "case_001").mkdir(parents=True)
    (tmp_path / "images" / "case_001" / "T1.nii.gz").write_text("img")
    (tmp_path / "masks" / "case_001" / "T1.nii.gz").write_text("mask")

    yaml_path = tmp_path / "Params_labels.yaml"
    with yaml_path.open("w") as f:
        yaml.safe_dump({"setting": {"label": 1, "binWidth": 25}}, f)

    discovery = discover_pairs(str(tmp_path))
    assert discovery["success"]
    pairs = discovery["pairs"]["high"]

    # FeatureAgent resolves relative image/mask paths from the working directory.
    monkeypatch.chdir(tmp_path)

    with patch("app.feature.cir_get_features") as mock_extract:
        mock_extract.return_value = {"original_firstorder_Mean": 1.0}
        agent = FeatureAgent(output_dir=str(tmp_path / "radiomics_features"))
        result = agent.run(pairs, yaml_path=str(yaml_path))

    assert result["success"]

    csv_path = tmp_path / "radiomics_features" / "radiomics_features.csv"
    h5_path = tmp_path / "radiomics_features" / "h5" / "case_001_T1.h5"
    assert csv_path.exists()
    assert h5_path.exists()

    df = pd.read_csv(csv_path)
    assert "patient_id" in df.columns
    assert "original_firstorder_Mean" in df.columns
    row = df[df["patient_id"] == "case_001"]
    assert len(row) == 1
    assert row.iloc[0]["original_firstorder_Mean"] == 1.0

    with h5py.File(h5_path, "r") as hf:
        assert "f_values" in hf
        assert "feature_names" in hf
        np.testing.assert_allclose(hf["f_values"][:], [[1.0]])
        assert list(hf["feature_names"].asstr()[:]) == ["original_firstorder_Mean"]


def _make_agent_state(project_path):
    """Build a minimal AgentState for direct node tests."""
    return {
        "project_path": str(project_path),
        "api_key": "fake",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-pro",
        "messages": [],
        "interrupt_type": None,
        "pending_plan": None,
        "pending_command": None,
        "pending_script": None,
        "script_risk_level": None,
        "pending_radiomics_plan": None,
        "pending_radiomics_execution": None,
        "confirmed": None,
        "tool_outputs": [],
        "operation_log": [],
    }


def test_agent_tool_flow_discovers_and_extracts(tmp_path):
    """Agent-level integration test for the discover -> extract tool flow.

    ``process_tool_calls`` is driven directly with synthetic AIMessages containing tool
    calls.  User confirmation is simulated by calling ``execute_confirmed`` with the
    pending state.  FeatureAgent is mocked so the test does not depend on PyRadiomics
    or real NIfTI files.
    """
    (tmp_path / "images" / "case_001").mkdir(parents=True)
    (tmp_path / "masks" / "case_001").mkdir(parents=True)
    (tmp_path / "images" / "case_001" / "T1.nii.gz").write_text("img")
    (tmp_path / "masks" / "case_001" / "T1.nii.gz").write_text("mask")

    yaml_path = tmp_path / "Params_labels.yaml"
    with yaml_path.open("w") as f:
        yaml.safe_dump({"setting": {"label": 1, "binWidth": 25}}, f)

    with patch("app.agent.nodes.ChatOpenAI"):
        # Step 1: discovery tool call triggers a radiomics_plan interrupt.
        state = _make_agent_state(tmp_path)
        state["messages"] = [
            AIMessage(
                content="",
                tool_calls=[{"name": "discover_radiomics_pairs", "args": {}, "id": "call_discover"}],
            )
        ]
        updates = process_tool_calls(state)

    assert updates["interrupt_type"] == "radiomics_plan"
    pending_plan = updates["pending_radiomics_plan"]
    assert pending_plan["success"] is True
    pairs = pending_plan["pairs"]["high"]
    assert len(pairs) == 1
    assert pairs[0]["patient_id"] == "case_001"

    with patch("app.agent.nodes.ChatOpenAI"):
        # Step 2: confirming the plan returns the discovery payload as a ToolMessage.
        state = _make_agent_state(tmp_path)
        state.update(
            interrupt_type="radiomics_plan",
            pending_radiomics_plan=pending_plan,
            confirmed=True,
        )
        updates = execute_confirmed(state)

    tool_msg = updates["messages"][0]
    plan_result = json.loads(tool_msg.content)
    assert plan_result["success"] is True
    assert plan_result["pairs"]["high"][0]["patient_id"] == "case_001"

    with patch("app.agent.nodes.ChatOpenAI"):
        # Step 3: extract tool call triggers a radiomics_execution interrupt.
        state = _make_agent_state(tmp_path)
        state["messages"] = [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "extract_radiomics_features",
                        "args": {"pairs": pairs, "yaml_path": str(yaml_path)},
                        "id": "call_extract",
                    }
                ],
            )
        ]
        updates = process_tool_calls(state)

    assert updates["interrupt_type"] == "radiomics_execution"
    pending_execution = updates["pending_radiomics_execution"]
    assert pending_execution["n_cases"] == 1
    assert pending_execution["yaml_path"] == str(yaml_path)

    with patch("app.agent.nodes.ChatOpenAI"), patch("app.agent.nodes.FeatureAgent") as mock_agent_class:
        # Step 4: confirming execution delegates to FeatureAgent and returns success.
        mock_agent = MagicMock()
        mock_agent.run.return_value = {
            "success": True,
            "message": "mocked extraction complete",
            "feature_names": ["original_firstorder_Mean"],
        }
        mock_agent_class.return_value = mock_agent

        state = _make_agent_state(tmp_path)
        state.update(
            interrupt_type="radiomics_execution",
            pending_radiomics_execution=pending_execution,
            confirmed=True,
        )
        updates = execute_confirmed(state)

    tool_msg = updates["messages"][0]
    extract_result = json.loads(tool_msg.content)
    assert extract_result["success"] is True
    assert extract_result["message"] == "mocked extraction complete"
    mock_agent.run.assert_called_once()
