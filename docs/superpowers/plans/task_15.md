# Task 15: 实现 Orchestrator 与 Agent 的注册/适配函数

### Task 15: 实现 Orchestrator 与 Agent 的注册/适配函数

**Files:**
- Modify: `app/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: 在 orchestrator.py 中注册真实 Agent handler**

`app/orchestrator.py` 添加：
```python
import os


def _build_llm(state: Dict[str, Any]):
    cfg = state["config"]["llm"]
    if not cfg.get("api_key"):
        return None
    from app.llm import LLMClient
    return LLMClient(api_key=cfg["api_key"], base_url=cfg["base_url"], model=cfg["model"])


def register_default_handlers(orch: Orchestrator) -> None:
    from app import discovery, clinical, qc, feature, analysis, report

    orch.register_handler(PipelineStage.DISCOVERY, lambda state: discovery.DiscoveryAgent(
        llm_client=_build_llm(state) if state["config"]["llm"].get("api_key") else None
    ).run(state["config"]["image_dir"]))

    orch.register_handler(PipelineStage.CLINICAL, lambda state: clinical.ClinicalAgent(
        llm_client=_build_llm(state)
    ).run(state["config"]["clinical_path"], state["user_request"]))

    orch.register_handler(PipelineStage.MATCHING, lambda state: clinical.run_matching(
        state["discovery"]["pairs"],
        state["clinical"]["df"],
        state["clinical"]["id_col"],
    ))

    orch.register_handler(PipelineStage.QC, lambda state: qc.QCAgent(
        target_spacing=state["config"].get("target_spacing"),
        output_dir=os.path.join(state["config"]["output_dir"], "qc_resampled"),
    ).run([
        {
            "patient_id": row["patient_id"],
            "image_path": row["image_path"],
            "mask_path": row["mask_path"],
            "modality": row.get("modality", state["config"].get("modality", "CT")),
        }
        for _, row in state["matching"]["matched_df"].iterrows()
    ]))

    orch.register_handler(PipelineStage.FEATURE, lambda state: feature.FeatureAgent(
        n_workers=state["config"].get("n_jobs", -1),
    ).run(
        state["qc"]["passed_pairs"],
        state["config"]["yaml_path"],
    ))

    orch.register_handler(PipelineStage.MERGE, merge_data)

    orch.register_handler(PipelineStage.ANALYSIS, lambda state: analysis.AnalysisAgent(
        output_dir=state["config"]["output_dir"],
        covariates=state["config"].get("covariates", [])
    ).run(state["merged"]["df"], state["clinical"]["label_col"]))

    orch.register_handler(PipelineStage.REPORT, lambda state: report.ReportAgent().run(
        analysis_result=state["analysis"],
        output_dir=state["config"]["output_dir"],
        modality=state["config"].get("modality", "CT"),
        n_features=len(state["feature"]["feature_names"]),
        covariates=state["config"].get("covariates", []),
        plot_paths=state["analysis"].get("plot_paths", []),
        llm_client=_build_llm(state),
    ))
```

- [ ] **Step 2: 添加集成测试**

`tests/test_orchestrator.py` 追加：
```python
from unittest.mock import patch, MagicMock


def test_orchestrator_default_handlers_registration():
    orch = Orchestrator(image_dir="./data", clinical_path="./data/clinical.csv")
    from app.orchestrator import register_default_handlers
    register_default_handlers(orch)
    assert PipelineStage.DISCOVERY in orch._stage_handlers
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: register default agent handlers in orchestrator"
```

---
