import pytest

from app.orchestrator import PipelineStage, Orchestrator, get_next_stage


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
