import traceback
from enum import Enum, auto
from typing import Dict, Any, Optional, Callable, List, Tuple, Generator


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
        min_samples: int = 30,
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
                "min_samples": min_samples,
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

    def _make_event(self, event_type: str, message: str, payload: Optional[Dict] = None) -> Dict[str, Any]:
        """Build a standard event payload for SSE delivery."""
        return {
            "type": event_type,
            "message": message,
            "stage": self.state["stage"].name,
            "payload": payload or {},
        }

    def _yield_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Emit the event via SSE (if configured) and return it for yielding."""
        self._emit(event)
        return event

    def run(self) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        self.state["stage"] = PipelineStage.IDLE
        yield self._yield_event(self._make_event("pipeline_start", "流水线启动"))
        current = PipelineStage.DISCOVERY
        return (yield from self._continue_from(current))

    def _continue_from(self, stage: PipelineStage) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        current = stage
        while current is not None and current not in (
            PipelineStage.COMPLETED,
            PipelineStage.FAILED,
        ):
            self.state["stage"] = current

            if current.name in self.state["config"]["skip_stages"]:
                yield self._yield_event(self._make_event("stage_skip", f"跳过阶段: {current.name}"))
                current = get_next_stage(current)
                continue

            success, error_msg = yield from self._run_stage(current)

            if not success:
                self.state["interrupted_at"] = current
                self.state["previous_stage"] = current
                self.state["stage"] = PipelineStage.INTERRUPTED
                self.state["error_log"].append(f"[{current.name}] {error_msg}")
                yield self._yield_event(self._make_event(
                    "stage_interrupt",
                    f"阶段 {current.name} 中断: {error_msg}",
                    {"error": error_msg, "stage": current.name},
                ))
                return self.state

            current = get_next_stage(current)

        if current == PipelineStage.COMPLETED or current is None:
            self.state["stage"] = PipelineStage.COMPLETED
            yield self._yield_event(self._make_event("pipeline_complete", "流水线完成"))
        else:
            self.state["stage"] = PipelineStage.FAILED
            yield self._yield_event(self._make_event("pipeline_fail", "流水线终止"))

        return self.state

    def _run_stage(self, stage: PipelineStage) -> Generator[Dict[str, Any], None, tuple[bool, str]]:
        handler = self._stage_handlers.get(stage)
        if handler is None:
            return False, f"阶段 {stage.name} 未注册 handler"

        yield self._yield_event(self._make_event("stage_start", f"开始: {stage.name}", {"stage": stage.name}))

        try:
            if stage == PipelineStage.ANALYSIS:
                n = self._get_merged_sample_count()
                min_samples = self.state["config"].get("min_samples", 30)
                if n < min_samples:
                    return False, f"有效样本量不足: 仅 {n} 例，要求 ≥ {min_samples}"

            result = handler(self.state)
            if not isinstance(result, dict) or "success" not in result:
                return False, f"阶段 {stage.name} 返回格式错误"

            key = "merged" if stage == PipelineStage.MERGE else stage.name.lower()
            self.state[key] = result

            if not result["success"]:
                return False, result.get("message", "未知错误")

            yield self._yield_event(self._make_event(
                "stage_complete",
                f"完成: {stage.name}",
                {"stage": stage.name, "details": result.get("message", "")},
            ))
            return True, ""
        except Exception as e:
            tb = traceback.format_exc()
            return False, f"{stage.name} 阶段异常: {e}\n{tb}"

    def _get_merged_sample_count(self) -> int:
        merged = self.state.get("merged")
        if merged and isinstance(merged, dict):
            return merged.get("n_samples", 0)
        qc_passed = self.state.get("qc", {}).get("passed_pairs", [])
        if not isinstance(qc_passed, list):
            qc_passed = []
        matched_ids = self.state.get("matching", {}).get("matched_ids", [])
        if not isinstance(matched_ids, list):
            matched_ids = []
        qc_ids = set()
        for p in qc_passed:
            if isinstance(p, dict):
                patient_id = p.get("patient_id")
                if patient_id is not None:
                    qc_ids.add(patient_id)
        matched_id_set = {str(m) for m in matched_ids}
        return len(matched_id_set & qc_ids)

    def resume(self, user_decision: str) -> Generator[Dict[str, Any], None, Dict[str, Any]]:
        if self.state["stage"] != PipelineStage.INTERRUPTED:
            yield self._yield_event(self._make_event("error", "resume() 只能在 INTERRUPTED 状态下调用"))
            return self.state

        self.state["user_decision"] = user_decision
        interrupted_stage = self.state.get("interrupted_at")

        if user_decision == "abort":
            self.state["stage"] = PipelineStage.FAILED
            yield self._yield_event(self._make_event("pipeline_fail", "用户终止流水线"))
            return self.state

        if user_decision == "skip":
            if interrupted_stage:
                skip_stages = self.state["config"]["skip_stages"]
                if interrupted_stage.name not in skip_stages:
                    skip_stages.append(interrupted_stage.name)
            next_stage = get_next_stage(interrupted_stage) if interrupted_stage else None
            if next_stage is None:
                self.state["stage"] = PipelineStage.COMPLETED
                yield self._yield_event(self._make_event("pipeline_complete", "流水线完成"))
                return self.state
            return (yield from self._continue_from(next_stage))

        if user_decision == "retry":
            if interrupted_stage is None:
                yield self._yield_event(self._make_event("error", "无法重试：未记录中断阶段"))
                return self.state
            return (yield from self._continue_from(interrupted_stage))

        yield self._yield_event(self._make_event("error", f"未知决策: {user_decision}"))
        return self.state
