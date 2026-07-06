# Task 16: 实现端到端 smoke test（mock 数据）

### Task 16: 实现端到端 smoke test（mock 数据）

**Files:**
- Create: `tests/test_smoke.py`

- [ ] **Step 1: 编写 smoke test**

`tests/test_smoke.py`:
```python
import pytest
import SimpleITK as sitk
import numpy as np
import pandas as pd
from pathlib import Path

from app.orchestrator import Orchestrator, register_default_handlers, PipelineStage


def test_smoke_pipeline(tmp_path):
    # 创建临时数据
    img_dir = tmp_path / "images"
    img_dir.mkdir()

    for pid in ["P001", "P002", "P003"]:
        img = sitk.GetImageFromArray(np.random.randint(0, 100, (8, 8, 8)).astype(np.int16))
        mask = sitk.GetImageFromArray(np.ones((8, 8, 8), dtype=np.uint8))
        sitk.WriteImage(img, str(img_dir / f"{pid}_image.nii.gz"))
        sitk.WriteImage(mask, str(img_dir / f"{pid}_mask.nii.gz"))

    clinical_path = tmp_path / "clinical.csv"
    pd.DataFrame({
        "PatientID": ["P001", "P002", "P003"],
        "Age": [50, 60, 70],
        "Label": [0, 1, 0],
    }).to_csv(clinical_path, index=False)

    # 由于 YAML 配置需要真实 PyRadiomics，这里 mock Feature Agent
    orch = Orchestrator(
        image_dir=str(img_dir),
        clinical_path=str(clinical_path),
        output_dir=str(tmp_path / "output"),
        yaml_path=str(Path(__file__).parent.parent / "DONGGUAN_NEW_Radiomic" / "Params_labels_qian.yaml"),
    )
    register_default_handlers(orch)

    # Mock Feature Agent 以跳过 PyRadiomics
    import app.feature as feature_module
    original_run = feature_module.FeatureAgent.run
    def mock_run(self, pairs, yaml_path, n_jobs=-1):
        import pandas as pd
        rows = []
        for p in pairs:
            rows.append({"patient_id": p["patient_id"], "original_firstorder_Mean": 1.0, "original_shape_VoxelVolume": 2.0})
        df = pd.DataFrame(rows).set_index("patient_id")
        return {"success": True, "message": "mock", "feature_df": df, "feature_names": df.columns.tolist(), "failed_ids": [], "zero_variance_features": [], "settings_used": {}, "extraction_time_seconds": 0.1}
    feature_module.FeatureAgent.run = mock_run

    events = list(orch.run())
    feature_module.FeatureAgent.run = original_run

    assert orch.state["stage"] == PipelineStage.COMPLETED
    assert orch.state["report"]["success"] is True
```

- [ ] **Step 2: 运行 smoke test**

Run: `pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: add end-to-end smoke test with mocked feature extraction"
```

---
