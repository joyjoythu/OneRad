from app.orchestrator import PipelineStage, Orchestrator, get_next_stage


def test_stage_order():
    assert get_next_stage(PipelineStage.DISCOVERY) == PipelineStage.CLINICAL
    assert get_next_stage(PipelineStage.REPORT) == PipelineStage.COMPLETED


def test_orchestrator_init():
    orch = Orchestrator(
        image_dir="./data/images",
        clinical_path="./data/clinical.csv",
    )
    assert orch.state["stage"] == PipelineStage.IDLE
    assert orch.state["config"]["image_dir"] == "./data/images"
