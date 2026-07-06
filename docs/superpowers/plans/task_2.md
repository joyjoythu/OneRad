# Task 2: 实现 PipelineStage 枚举与 Orchestrator 骨架

### Task 2: 实现 PipelineStage 枚举与 Orchestrator 骨架

**Files:**
- Create: `app/orchestrator.py`
- Create: `tests/test_orchestrator.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_orchestrator.py`:
```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_orchestrator.py -v`
Expected: ImportError / function not defined

- [ ] **Step 3: 实现 PipelineStage 和 Orchestrator 骨架**

`app/orchestrator.py`:
```python
from enum import Enum, auto
from typing import Dict, Any, Optional, Callable, Generator


class PipelineStage(Enum):
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
    try:
        idx = STAGE_ORDER.index(current)
        return STAGE_ORDER[idx + 1] if idx + 1 < len(STAGE_ORDER) else PipelineStage.COMPLETED
    except ValueError:
        return None


class Orchestrator:
    def __init__(
        self,
        image_dir: str,
        clinical_path: str,
        user_request: str = "",
        output_dir: str = "./output",
        modality: str = "auto",
        covariates: Optional[list] = None,
        n_jobs: int = -1,
        target_spacing: Optional[tuple] = None,
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
        self._stage_handlers: Dict[PipelineStage, Callable[[Dict], Dict]] = {}
        self._sse_emitter: Optional[Callable[[Dict], None]] = None

    def register_handler(self, stage: PipelineStage, handler: Callable[[Dict], Dict]) -> None:
        if stage in STAGE_ORDER:
            self._stage_handlers[stage] = handler
        else:
            raise ValueError(f"无法注册非流水线阶段: {stage}")

    def set_sse_emitter(self, emitter: Callable[[Dict], None]) -> None:
        self._sse_emitter = emitter

    def _emit(self, event: Dict[str, Any]) -> None:
        if self._sse_emitter:
            self._sse_emitter(event)

    def _make_event(self, event_type: str, message: str, payload: Optional[Dict] = None) -> Dict:
        return {
            "type": event_type,
            "message": message,
            "stage": self.state["stage"].name,
            "payload": payload or {},
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add PipelineStage enum and Orchestrator skeleton"
```

---
