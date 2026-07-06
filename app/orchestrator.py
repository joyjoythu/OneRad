from enum import Enum, auto
from typing import Dict, Any, Optional, Callable, List, Tuple


class PipelineStage(Enum):
    """Radiomics pipeline lifecycle stages."""
    IDLE = auto()
    DISCOVERY = auto()
    CLINICAL = auto()
    MATCHING = auto()
    QC = auto()
    FEATURE = auto()
    MERGE = auto()
    ANALYSIS = auto()
    REPORT = auto()
    COMPLETED = auto()
    INTERRUPTED = auto()
    FAILED = auto()


STAGE_ORDER = [
    PipelineStage.DISCOVERY,
    PipelineStage.CLINICAL,
    PipelineStage.MATCHING,
    PipelineStage.QC,
    PipelineStage.FEATURE,
    PipelineStage.MERGE,
    PipelineStage.ANALYSIS,
    PipelineStage.REPORT,
]


def get_next_stage(current: PipelineStage) -> Optional[PipelineStage]:
    """Return the stage that follows `current` in the pipeline order.

    Returns ``None`` for stages that are not part of the ordered execution path
    (e.g. IDLE, COMPLETED, FAILED). The REPORT stage advances to COMPLETED.
    """
    try:
        idx = STAGE_ORDER.index(current)
        return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else PipelineStage.COMPLETED
    except ValueError:
        return None


class Orchestrator:
    """Coordinates radiomics pipeline execution and stage-to-stage event emission."""

    def __init__(
        self,
        image_dir: str,
        clinical_path: str,
        user_request: str = "",
        output_dir: str = "./output",
        modality: str = "auto",
        covariates: Optional[List[str]] = None,
        n_jobs: int = -1,
        target_spacing: Optional[Tuple[float, float, float]] = None,
        yaml_path: str = "./DONGGUAN_NEW_Radiomic/Params_labels_qian.yaml",
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
    ):
        self.state: Dict[str, Any] = {
            "stage": PipelineStage.IDLE,
            "previous_stage": PipelineStage.IDLE,
            "user_request": user_request,
            "config": {
                "image_dir": image_dir,
                "clinical_path": clinical_path,
                "output_dir": output_dir,
                "modality": modality,
                "covariates": covariates or [],
                "skip_stages": [],
                "n_jobs": n_jobs,
                "target_spacing": target_spacing,
                "yaml_path": yaml_path,
                "llm": {
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model,
                },
            },
            "discovery": None,
            "clinical": None,
            "matching": None,
            "qc": None,
            "feature": None,
            "merged": None,
            "analysis": None,
            "report": None,
            "interrupted_at": None,
            "error_log": [],
            "user_decision": None,
        }
        self._stage_handlers: Dict[PipelineStage, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
        self._sse_emitter: Optional[Callable[[Dict[str, Any]], None]] = None

    def register_handler(self, stage: PipelineStage, handler: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        """Register a handler callable for an executable pipeline stage."""
        if not callable(handler):
            raise TypeError("handler must be callable")
        if stage in STAGE_ORDER:
            self._stage_handlers[stage] = handler
        else:
            raise ValueError(f"无法注册非流水线阶段: {stage}")

    def set_sse_emitter(self, emitter: Callable[[Dict[str, Any]], None]) -> None:
        """Set the callback used to emit server-sent events."""
        self._sse_emitter = emitter

    def _emit(self, event: Dict[str, Any]) -> None:
        if self._sse_emitter:
            self._sse_emitter(event)

    def _make_event(self, event_type: str, message: str, payload: Optional[Dict] = None) -> Dict:
        """Build a standard event payload for SSE delivery."""
        return {
            "type": event_type,
            "message": message,
            "stage": self.state["stage"].name,
            "payload": payload or {},
        }
