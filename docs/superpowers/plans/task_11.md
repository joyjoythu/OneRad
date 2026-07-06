# Task 11: 实现 Feature Agent

### Task 11: 实现 Feature Agent

**Files:**
- Create: `app/feature.py`
- Create: `tests/test_feature.py`
- Create: `DONGGUAN_NEW_Radiomic/__init__.py`

- [ ] **Step 1: 创建 DONGGUAN_NEW_Radiomic/__init__.py**

Run: `touch DONGGUAN_NEW_Radiomic/__init__.py`

- [ ] **Step 2: 编写失败测试**

`tests/test_feature.py`:
```python
import pytest
import SimpleITK as sitk
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import patch
from app.feature import FeatureAgent


def test_feature_agent_empty_pairs():
    agent = FeatureAgent()
    result = agent.run([])
    assert result["success"] is False
```

- [ ] **Step 3: 实现 FeatureAgent**

`app/feature.py`:
```python
import os
import time
import logging
from typing import List, Dict, Any
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd
import numpy as np

from DONGGUAN_NEW_Radiomic.Atsea_def import cir_get_features

logger = logging.getLogger(__name__)


class FeatureAgent:
    def __init__(self, n_workers: int = -1, timeout_per_case: int = 300):
        import multiprocessing as mp
        self.n_workers = n_workers if n_workers > 0 else max(1, mp.cpu_count() - 1)
        self.timeout_per_case = timeout_per_case

    def run(self, pairs: List[Dict[str, str]], yaml_path: str, n_jobs: int = -1) -> Dict[str, Any]:
        if not pairs:
            return {"success": False, "message": "pairs 为空"}
        if not os.path.exists(yaml_path):
            return {"success": False, "message": f"YAML 配置不存在: {yaml_path}"}

        t0 = time.time()
        n_workers = n_jobs if n_jobs > 0 else self.n_workers

        if n_workers == 1 or len(pairs) == 1:
            results = [self._extract_single((p["patient_id"], p["image_path"], p["mask_path"], yaml_path)) for p in pairs]
        else:
            results = []
            with ProcessPoolExecutor(max_workers=n_workers) as executor:
                futures = {
                    executor.submit(self._extract_single, (p["patient_id"], p["image_path"], p["mask_path"], yaml_path)): p
                    for p in pairs
                }
                for future in as_completed(futures):
                    try:
                        results.append(future.result(timeout=self.timeout_per_case))
                    except Exception as e:
                        p = futures[future]
                        results.append((p["patient_id"], None, str(e)))

        rows = []
        failed_ids = []
        for pid, feats, err in results:
            if err:
                failed_ids.append(pid)
                logger.warning(f"特征提取失败 {pid}: {err}")
            else:
                row = {"patient_id": pid}
                row.update(feats)
                rows.append(row)

        if not rows:
            return {"success": False, "message": "所有样本特征提取均失败"}

        df = pd.DataFrame(rows).set_index("patient_id")
        df = df.apply(pd.to_numeric, errors="coerce")
        nan_cols = df.columns[df.isna().all()].tolist()
        if nan_cols:
            df = df.drop(columns=nan_cols)

        zero_var = [c for c in df.columns if df[c].nunique(dropna=True) <= 1]
        if zero_var:
            df = df.drop(columns=zero_var)

        return {
            "success": True,
            "message": f"特征提取完成: {len(df)}/{len(pairs)} 成功, {len(df.columns)} 特征",
            "feature_df": df,
            "feature_names": df.columns.tolist(),
            "failed_ids": failed_ids,
            "zero_variance_features": zero_var,
            "settings_used": {"yaml_path": yaml_path},
            "extraction_time_seconds": round(time.time() - t0, 2),
        }

    @staticmethod
    def _extract_single(args):
        patient_id, image_path, mask_path, yaml_path = args
        try:
            if not os.path.exists(image_path):
                return patient_id, None, f"影像不存在: {image_path}"
            if not os.path.exists(mask_path):
                return patient_id, None, f"Mask 不存在: {mask_path}"
            feats = cir_get_features(image_path, mask_path, yaml_path)
            return patient_id, feats, None
        except Exception as e:
            return patient_id, None, str(e)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_feature.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/feature.py tests/test_feature.py DONGGUAN_NEW_Radiomic/__init__.py
git commit -m "feat: add FeatureAgent wrapping cir_get_features"
```

---
