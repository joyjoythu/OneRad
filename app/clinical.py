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
