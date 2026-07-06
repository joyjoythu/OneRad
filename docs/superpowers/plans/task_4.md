# Task 4: 实现 Merge 函数

### Task 4: 实现 Merge 函数

**Files:**
- Modify: `app/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_orchestrator.py` 追加：
```python
import pandas as pd


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
    from app.orchestrator import merge_data
    result = merge_data(orch.state)
    assert result["n_samples"] == 2
    assert "f1" in result["df"].columns
    assert "Label" in result["df"].columns
```

- [ ] **Step 2: 实现 merge_data**

`app/orchestrator.py` 添加：
```python
def merge_data(state: Dict[str, Any]) -> Dict[str, Any]:
    feature_df = state["feature"]["feature_df"]
    matched_df = state["matching"]["matched_df"]

    if feature_df is None or feature_df.empty:
        return {"success": False, "message": "特征矩阵为空", "df": None, "n_samples": 0, "n_features": 0}
    if matched_df is None or matched_df.empty:
        return {"success": False, "message": "匹配表格为空", "df": None, "n_samples": 0, "n_features": 0}

    merged = matched_df.set_index("patient_id").join(feature_df, how="inner")
    merged = merged.reset_index()

    return {
        "success": True,
        "message": f"合并完成: {len(merged)} 样本, {len(feature_df.columns)} 影像特征",
        "df": merged,
        "n_samples": len(merged),
        "n_features": len(feature_df.columns),
    }
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_orchestrator.py::test_merge_data -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add merge_data for feature and clinical tables"
```

---
