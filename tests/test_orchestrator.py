import pandas as pd
import pytest

from app.orchestrator import PipelineStage, Orchestrator, STAGE_ORDER, get_next_stage, merge_data


def test_stage_order():
    assert get_next_stage(PipelineStage.DISCOVERY) == PipelineStage.CLINICAL
    assert get_next_stage(PipelineStage.REPORT) == PipelineStage.COMPLETED


def test_get_next_stage_returns_none_for_non_execution_stages():
    assert get_next_stage(PipelineStage.IDLE) is None
    assert get_next_stage(PipelineStage.COMPLETED) is None
    assert get_next_stage(PipelineStage.FAILED) is None


def test_orchestrator_init():
    orch = Orchestrator(
        image_dir="./data/images",
        clinical_path="./data/clinical.csv",
    )
    assert orch.state["stage"] == PipelineStage.IDLE
    assert orch.state["config"]["image_dir"] == "./data/images"


def test_register_handler_rejects_non_execution_stage():
    orch = Orchestrator(
        image_dir="./data/images",
        clinical_path="./data/clinical.csv",
    )
    with pytest.raises(ValueError):
        orch.register_handler(PipelineStage.IDLE, lambda x: x)


def test_register_handler_rejects_non_callable():
    orch = Orchestrator(
        image_dir="./data/images",
        clinical_path="./data/clinical.csv",
    )
    with pytest.raises(TypeError):
        orch.register_handler(PipelineStage.DISCOVERY, "not callable")


def test_set_sse_emitter_and_emit_delivers_event():
    orch = Orchestrator(
        image_dir="./data/images",
        clinical_path="./data/clinical.csv",
    )
    received = []
    orch.set_sse_emitter(lambda event: received.append(event))
    orch._emit({"type": "test", "message": "hello"})
    assert len(received) == 1
    assert received[0]["type"] == "test"
    assert received[0]["message"] == "hello"


def test_run_with_mock_handlers():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")

    def mock_discovery(state):
        return {"success": True, "message": "ok"}

    orch.register_handler(PipelineStage.DISCOVERY, mock_discovery)

    events = list(orch.run())
    assert any(e["type"] == "pipeline_start" for e in events)
    assert orch.state["stage"] == PipelineStage.INTERRUPTED  # 后续阶段未注册


def test_resume_abort():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")
    orch.register_handler(PipelineStage.DISCOVERY, lambda s: {"success": True})
    list(orch.run())
    assert orch.state["stage"] == PipelineStage.INTERRUPTED

    events = list(orch.resume("abort"))
    assert orch.state["stage"] == PipelineStage.FAILED
    assert any(e["type"] == "pipeline_fail" for e in events)


def test_resume_skip_adds_stage_to_skip_stages():
    orch = Orchestrator(
        image_dir="./data", clinical_path="./data/clinical.csv", min_samples=0
    )
    orch.register_handler(PipelineStage.DISCOVERY, lambda s: {"success": True})
    for stage in (
        PipelineStage.MATCHING,
        PipelineStage.QC,
        PipelineStage.FEATURE,
        PipelineStage.MERGE,
        PipelineStage.ANALYSIS,
        PipelineStage.REPORT,
    ):
        orch.register_handler(stage, lambda s: {"success": True})

    list(orch.run())
    assert orch.state["stage"] == PipelineStage.INTERRUPTED
    assert orch.state["interrupted_at"] == PipelineStage.CLINICAL

    events = list(orch.resume("skip"))
    assert "CLINICAL" in orch.state["config"]["skip_stages"]
    assert orch.state["stage"] == PipelineStage.COMPLETED
    assert any(e["type"] == "pipeline_complete" for e in events)


def test_resume_retry():
    orch = Orchestrator(
        image_dir="./data", clinical_path="./data/clinical.csv", min_samples=0
    )
    orch.register_handler(PipelineStage.DISCOVERY, lambda s: {"success": True})
    list(orch.run())
    assert orch.state["interrupted_at"] == PipelineStage.CLINICAL

    orch.register_handler(PipelineStage.CLINICAL, lambda s: {"success": True})
    for stage in (
        PipelineStage.MATCHING,
        PipelineStage.QC,
        PipelineStage.FEATURE,
        PipelineStage.MERGE,
        PipelineStage.ANALYSIS,
        PipelineStage.REPORT,
    ):
        orch.register_handler(stage, lambda s: {"success": True})

    events = list(orch.resume("retry"))
    assert orch.state["stage"] == PipelineStage.COMPLETED
    assert any(e["type"] == "stage_complete" and e["stage"] == "CLINICAL" for e in events)
    assert any(e["type"] == "pipeline_complete" for e in events)


def test_resume_retry_without_interrupted_stage_stays_interrupted():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")
    orch.state["stage"] = PipelineStage.INTERRUPTED
    orch.state["interrupted_at"] = None

    events = list(orch.resume("retry"))
    assert orch.state["stage"] == PipelineStage.INTERRUPTED
    assert any(e["type"] == "error" for e in events)


def test_resume_unknown_emits_error():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")
    orch.register_handler(PipelineStage.DISCOVERY, lambda s: {"success": True})
    list(orch.run())
    assert orch.state["stage"] == PipelineStage.INTERRUPTED

    events = list(orch.resume("unknown"))
    assert orch.state["stage"] == PipelineStage.INTERRUPTED
    assert any(e["type"] == "error" for e in events)


def test_skip_stages_config_behavior():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")
    orch.register_handler(PipelineStage.DISCOVERY, lambda s: {"success": True})
    orch.register_handler(PipelineStage.CLINICAL, lambda s: {"success": True})
    orch.state["config"]["skip_stages"].append("CLINICAL")

    events = list(orch.run())
    assert any(e["type"] == "stage_skip" and e["stage"] == "CLINICAL" for e in events)
    assert orch.state["stage"] == PipelineStage.INTERRUPTED
    assert orch.state["interrupted_at"] == PipelineStage.MATCHING


def test_get_merged_sample_count_merged_state():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")
    orch.state["merged"] = {"n_samples": 42}
    assert orch._get_merged_sample_count() == 42


def test_get_merged_sample_count_fallback():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")
    orch.state["matching"] = {"matched_ids": ["A", "B", "C"]}
    orch.state["qc"] = {
        "passed_pairs": [
            {"patient_id": "B"},
            {"patient_id": "D"},
            "not_a_dict",
            {"no_id": "x"},
        ]
    }
    assert orch._get_merged_sample_count() == 1


def test_full_pipeline_completion():
    orch = Orchestrator(
        image_dir="./data", clinical_path="./data/clinical.csv", min_samples=0
    )
    for stage in STAGE_ORDER:
        orch.register_handler(stage, lambda s, _stage=stage.name: {"success": True, "message": _stage})

    events = list(orch.run())
    assert orch.state["stage"] == PipelineStage.COMPLETED
    assert any(e["type"] == "pipeline_complete" for e in events)
    assert all(stage.name in {e["stage"] for e in events if e["type"] == "stage_complete"} for stage in STAGE_ORDER)


def test_merge_data():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")
    orch.state["feature"] = {
        "feature_df": pd.DataFrame(
            {"f1": [1.0, 2.0]},
            index=["P001", "P002"],
        )
    }
    orch.state["matching"] = {
        "matched_df": pd.DataFrame({
            "patient_id": ["P001", "P002"],
            "image_path": ["a.nii", "b.nii"],
            "mask_path": ["a_mask.nii", "b_mask.nii"],
            "Label": [0, 1],
        })
    }
    result = merge_data(orch.state)
    assert result["n_samples"] == 2
    assert "f1" in result["df"].columns
    assert "Label" in result["df"].columns
