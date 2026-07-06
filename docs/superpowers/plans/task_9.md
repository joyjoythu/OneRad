# Task 9: 实现 Matching Agent

### Task 9: 实现 Matching Agent

**Files:**
- Modify: `app/clinical.py`
- Create: `tests/test_matching.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_matching.py`:
```python
import pandas as pd
from app.clinical import run_matching


def test_run_matching_basic():
    pairs = [
        {"patient_id": "P001", "image_path": "a.nii", "mask_path": "a_mask.nii"},
        {"patient_id": "P002", "image_path": "b.nii", "mask_path": "b_mask.nii"},
    ]
    df = pd.DataFrame({
        "PatientID": ["P001", "P002", "P003"],
        "Age": [50, 60, 70],
        "Label": [0, 1, 0],
    })
    result = run_matching(pairs, df, id_col="PatientID")
    assert result["success"] is True
    assert result["match_stats"]["matched"] == 2
    assert "P003" in result["unmatched_clinical_ids"]
```

- [ ] **Step 2: 实现 run_matching**

`app/clinical.py` 追加：
```python
import difflib


def _normalize_id(id_str: str) -> str:
    if not isinstance(id_str, str):
        id_str = str(id_str)
    s = id_str.strip()
    s = re.sub(r"\.(nii\.gz|nii|dcm|mha|mhd|raw|nrrd)$", "", s, flags=re.IGNORECASE)
    return s.lower()


def run_matching(discovery_pairs: List[dict], clinical_df: pd.DataFrame, id_col: str,
                 fuzzy_threshold: float = 0.8, enable_fuzzy: bool = True) -> dict:
    if not discovery_pairs:
        return {"success": False, "message": "Discovery pairs 为空"}
    if clinical_df is None or clinical_df.empty:
        return {"success": False, "message": "临床表格为空"}
    if id_col not in clinical_df.columns:
        return {"success": False, "message": f"ID 列 '{id_col}' 不存在"}

    image_ids = set()
    for p in discovery_pairs:
        pid = p.get("patient_id")
        if pid is None:
            return {"success": False, "message": "pair 缺少 patient_id"}
        image_ids.add(_normalize_id(pid))

    clinical_ids = set(clinical_df[id_col].astype(str).apply(_normalize_id))

    matched = image_ids & clinical_ids
    unmatched_img = image_ids - matched
    unmatched_cli = clinical_ids - matched

    method = "exact"
    fuzzy_map = {}

    if enable_fuzzy and unmatched_img and unmatched_cli:
        available = list(unmatched_cli)
        for img_id in sorted(unmatched_img):
            best_ratio, best_id = 0.0, None
            for cli_id in available:
                ratio = difflib.SequenceMatcher(None, img_id, cli_id).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_id = cli_id
            if best_id is not None and best_ratio >= fuzzy_threshold:
                fuzzy_map[img_id] = best_id
                available.remove(best_id)
        if fuzzy_map:
            method = "fuzzy"
            matched = matched | set(fuzzy_map.keys())
            unmatched_img = set(unmatched_img) - set(fuzzy_map.keys())
            unmatched_cli = set(unmatched_cli) - set(fuzzy_map.values())

    if not matched:
        return {"success": False, "message": "无任何 ID 匹配成功"}

    # 构建 matched_df
    norm_to_pair = {_normalize_id(p["patient_id"]): p for p in discovery_pairs}
    clinical_df = clinical_df.copy()
    clinical_df["__norm_id__"] = clinical_df[id_col].astype(str).apply(_normalize_id)
    norm_to_original = dict(zip(clinical_df["__norm_id__"], clinical_df[id_col]))

    rows = []
    for norm_id in matched:
        pair = norm_to_pair.get(norm_id)
        if pair is None:
            continue
        target_norm = fuzzy_map.get(norm_id, norm_id)
        original_id = norm_to_original.get(target_norm)
        if original_id is None:
            continue
        row_df = clinical_df[clinical_df[id_col] == original_id]
        if row_df.empty:
            continue
        row = row_df.iloc[0].to_dict()
        row.pop("__norm_id__", None)
        row["patient_id"] = pair["patient_id"]
        row["image_path"] = pair["image_path"]
        row["mask_path"] = pair["mask_path"]
        rows.append(row)

    matched_df = pd.DataFrame(rows)
    matched_df = matched_df.drop_duplicates(subset=["patient_id"], keep="first")

    return {
        "success": True,
        "message": f"匹配完成: {len(matched_df)} 例",
        "matched_df": matched_df,
        "matched_ids": matched_df["patient_id"].tolist(),
        "unmatched_image_ids": sorted(unmatched_img),
        "unmatched_clinical_ids": sorted(unmatched_cli),
        "match_method": method,
        "match_stats": {
            "total_images": len(discovery_pairs),
            "total_clinical": len(clinical_df),
            "matched": len(matched_df),
            "unmatched_images": len(unmatched_img),
            "unmatched_clinical": len(unmatched_cli),
        },
    }
```

- [ ] **Step 3: 运行测试确认通过**

Run: `pytest tests/test_matching.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app/clinical.py tests/test_matching.py
git commit -m "feat: add MatchingAgent for ID alignment"
```

---
