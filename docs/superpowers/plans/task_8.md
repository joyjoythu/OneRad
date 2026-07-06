# Task 8: 实现 Clinical Agent

### Task 8: 实现 Clinical Agent

**Files:**
- Create: `app/clinical.py`
- Create: `tests/test_clinical.py`

- [ ] **Step 1: 编写失败测试**

`tests/test_clinical.py`:
```python
import pandas as pd
from app.clinical import ClinicalAgent


def test_clinical_agent_basic():
    df = pd.DataFrame({
        "PatientID": ["P001", "P002"],
        "Age": [50, 60],
        "Sex": ["F", "M"],
        "Label": [0, 1],
    })
    from io import BytesIO
    buf = BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)

    # 使用 mock LLM
    from unittest.mock import MagicMock
    mock_llm = MagicMock()
    mock_llm.call.return_value = '{"id_col": "PatientID", "label_col": "Label", "feature_cols": ["Age", "Sex"]}'
    mock_llm._extract_json.return_value = {"id_col": "PatientID", "label_col": "Label", "feature_cols": ["Age", "Sex"]}

    agent = ClinicalAgent(llm_client=mock_llm)
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        f.write(buf.getvalue())
        path = f.name
    result = agent.run(path)
    os.unlink(path)

    assert result["success"] is True
    assert result["id_col"] == "PatientID"
    assert result["label_col"] == "Label"
```

- [ ] **Step 2: 实现 ClinicalAgent**

`app/clinical.py`:
```python
import os
import json
import re
from typing import Optional, List, Dict, Any

import pandas as pd


class ClinicalAgent:
    SUPPORTED_EXTS = {".csv", ".xlsx", ".xls"}

    def __init__(self, llm_client=None, max_retries: int = 2):
        self.llm_client = llm_client
        self.max_retries = max_retries

    def run(self, clinical_path: str, task_hint: str = "") -> dict:
        if not os.path.exists(clinical_path):
            return {"success": False, "message": f"文件不存在: {clinical_path}"}

        ext = os.path.splitext(clinical_path)[1].lower()
        if ext not in self.SUPPORTED_EXTS:
            return {"success": False, "message": f"不支持的格式: {ext}"}

        try:
            if ext == ".csv":
                try:
                    df = pd.read_csv(clinical_path, encoding="utf-8")
                except UnicodeDecodeError:
                    df = pd.read_csv(clinical_path, encoding="gbk")
            else:
                df = pd.read_excel(clinical_path)
        except Exception as e:
            return {"success": False, "message": f"读取表格失败: {e}"}

        if df.empty or df.shape[1] < 2:
            return {"success": False, "message": "表格为空或列数不足"}

        context = self._build_column_context(df, task_hint)
        parsed = self._call_llm_with_retry(context)
        if isinstance(parsed, dict) and not parsed.get("success", True):
            return parsed

        validated = self._validate_columns(df, parsed)
        if isinstance(validated, dict) and not validated.get("success", True):
            return validated

        id_col = validated["id_col"]
        id_series = df[id_col]
        id_dtype = "int" if pd.api.types.is_integer_dtype(id_series) else "str"

        return {
            "success": True,
            "message": "列名识别完成",
            "df": df,
            "id_col": id_col,
            "label_col": validated.get("label_col"),
            "feature_cols": validated["feature_cols"],
            "id_dtype": id_dtype,
            "n_samples": len(df),
        }

    def _build_column_context(self, df: pd.DataFrame, task_hint: str) -> Dict[str, Any]:
        columns = []
        for col in df.columns:
            s = df[col]
            columns.append({
                "column_name": col,
                "dtype": str(s.dtype),
                "non_null": int(s.notna().sum()),
                "missing_rate": round(1 - s.notna().sum() / len(df), 3),
                "n_unique": int(s.nunique(dropna=False)),
                "samples": ", ".join(s.dropna().head(3).astype(str).tolist()),
            })
        return {
            "n_rows": len(df),
            "n_columns": len(df.columns),
            "task_hint": task_hint or "未提供",
            "columns": columns,
        }

    def _call_llm_with_retry(self, context: Dict[str, Any]) -> Dict[str, Any]:
        if self.llm_client is None:
            return {"success": False, "message": "未配置 LLM，无法自动识别列名"}
        from app.llm import build_column_identification_prompt
        system, user = build_column_identification_prompt(context)
        last_error = None
        for _ in range(self.max_retries + 1):
            try:
                response = self.llm_client.call(system, user, temperature=0.1)
                parsed = self.llm_client._extract_json(response)
                if parsed and {"id_col", "label_col", "feature_cols"}.issubset(parsed.keys()):
                    return parsed
                last_error = "JSON 解析失败或字段缺失"
            except Exception as e:
                last_error = str(e)
        return {"success": False, "message": f"LLM 列名识别失败: {last_error}"}

    def _validate_columns(self, df: pd.DataFrame, parsed: Dict[str, Any]) -> Dict[str, Any]:
        all_cols = set(df.columns)
        id_col = parsed.get("id_col")
        label_col = parsed.get("label_col")
        feature_cols = parsed.get("feature_cols", [])

        if id_col not in all_cols:
            return {"success": False, "message": f"ID 列 '{id_col}' 不存在"}
        if label_col not in all_cols:
            return {"success": False, "message": f"Label 列 '{label_col}' 不存在"}

        if not isinstance(feature_cols, list):
            feature_cols = [feature_cols] if feature_cols else []
        feature_cols = [c for c in feature_cols if c in all_cols]
        special = {id_col, label_col}
        feature_cols = [c for c in feature_cols if c not in special]

        if not feature_cols:
            return {"success": False, "message": "未识别到有效临床特征列"}

        # label 值域检查
        unique_labels = df[label_col].dropna().unique()
        if not set(unique_labels).issubset({0, 1}):
            return {"success": False, "message": f"Label 列值域非 0/1: {unique_labels}"}

        return {
            "success": True,
            "id_col": id_col,
            "label_col": label_col,
            "feature_cols": feature_cols,
        }
```

- [ ] **Step 3: 在 llm.py 添加 Clinical prompt 构建函数**

`app/llm.py` 添加：
```python
COLUMN_IDENTIFICATION_TEMPLATE = """请分析以下临床数据表格，识别 ID 列、二分类标签列和临床特征列。
返回纯 JSON：{{"id_col": "...", "label_col": "...", "feature_cols": ["..."], "reasoning": "..."}}

表格信息：
- 行数: {n_rows}
- 列数: {n_columns}
- 任务描述: {task_hint}

列详情：
{columns}
"""


def _format_columns(columns: List[Dict]) -> str:
    lines = ["| 列名 | 类型 | 非空数 | 缺失率 | 唯一值 | 示例 |"]
    for c in columns:
        lines.append(f"| {c['column_name']} | {c['dtype']} | {c['non_null']} | {c['missing_rate']} | {c['n_unique']} | {c['samples']} |")
    return "\n".join(lines)


def build_column_identification_prompt(context: Dict[str, Any]) -> Tuple[str, str]:
    system = (
        "You are a clinical data analyst for radiomics research. "
        "Return ONLY a JSON object with keys: id_col, label_col, feature_cols, reasoning. "
        "Label_col must be a binary 0/1 outcome. feature_cols must not include id_col or label_col."
    )
    user = COLUMN_IDENTIFICATION_TEMPLATE.format(
        n_rows=context["n_rows"],
        n_columns=context["n_columns"],
        task_hint=context["task_hint"],
        columns=_format_columns(context["columns"]),
    )
    return system, user
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_clinical.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/clinical.py app/llm.py tests/test_clinical.py
git commit -m "feat: add ClinicalAgent for column identification"
```

---
