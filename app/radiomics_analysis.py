"""Radiomics CV analysis orchestration for the conversational agent.

Two entry points:

- ``inspect_analysis_inputs``: resolve feature CSV / clinical table / ID and
  label columns. Returns ``ready`` with resolved parameters, or
  ``need_clarification`` (with candidate lists) / ``error`` so the agent can
  ask the user in conversation before any execution.
- ``run_radiomics_cv_analysis``: run LASSO + logistic regression with
  stratified k-fold CV (via ``AnalysisAgent``), export curves and CSVs, and
  build Word + Markdown reports.
"""

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# NOTE: Callable/Tuple/np/_merge_feature_clinical 为 Task 4 编排函数预留，本任务暂不使用
from app.utils import (
    _load_feature_csv,
    _merge_feature_clinical,
    _infer_covariates,
)

logger = logging.getLogger(__name__)

_RADIOMIC_PREFIXES = ("original_", "wavelet-", "log-sigma_")
_CLINICAL_EXTS = {".csv", ".xlsx", ".xls"}
_MAX_SCAN_DEPTH = 2


def _load_table(path: str) -> pd.DataFrame:
    """Load a CSV (utf-8/gbk) or Excel table."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"文件不存在: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        try:
            return pd.read_csv(path, encoding="utf-8")
        except UnicodeDecodeError:
            return pd.read_csv(path, encoding="gbk")
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise ValueError(f"不支持的文件格式: {ext}")


def _binary_values(series: pd.Series) -> Optional[set]:
    """Return the set of numeric values if the series is numeric and all
    non-null values are exactly 0 or 1 (including "0"/"1" strings and
    0.0/1.0 floats); otherwise None. No int-truncation."""
    vals = series.dropna()
    if vals.empty:
        return None
    try:
        nums = pd.to_numeric(vals, errors="raise")
    except (ValueError, TypeError):
        return None
    unique = set(nums.unique())
    if unique and unique.issubset({0, 1}):
        return unique
    return None


def _binary_columns(df: pd.DataFrame, exclude: Optional[str] = None) -> List[str]:
    """Columns whose non-null values are exactly {0, 1}."""
    cols = []
    for col in df.columns:
        if col == exclude:
            continue
        if _binary_values(df[col]) == {0, 1}:
            cols.append(col)
    return cols


def _norm_id(value) -> str:
    """Normalize an ID for matching: strip, and collapse integral floats
    like "1.0" to "1"."""
    s = str(value).strip()
    if s.endswith(".0"):
        head = s[:-2]
        if head.lstrip("-").isdigit():
            return head
    return s


def _id_match_counts(df: pd.DataFrame, feature_ids: set) -> Dict[str, int]:
    """Per-column count of values present in ``feature_ids`` (string compare)."""
    counts = {}
    for col in df.columns:
        values = {_norm_id(v) for v in df[col].dropna()}
        counts[col] = len(values & feature_ids)
    return counts


def _detect_id_column(df: pd.DataFrame, feature_ids: set) -> Optional[str]:
    """Column with the largest intersection with ``feature_ids``; None if 0."""
    counts = _id_match_counts(df, feature_ids)
    if not counts:
        return None
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else None


def _find_clinical_candidates(project_path: str, feature_ids: set,
                              exclude_path: str = "") -> List[str]:
    """Scan the project (depth <= 2) for tables with a 0/1 column and an
    ID-like column overlapping the feature patient_ids."""
    candidates = []
    exclude_abs = (os.path.normcase(os.path.abspath(exclude_path))
                   if exclude_path else "")
    for base, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
        rel = os.path.relpath(base, project_path)
        depth = 0 if rel == "." else len(rel.split(os.sep))
        if depth >= _MAX_SCAN_DEPTH:
            dirs[:] = []
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() not in _CLINICAL_EXTS:
                continue
            path = os.path.join(base, name)
            if os.path.normcase(os.path.abspath(path)) == exclude_abs:
                continue
            try:
                df = _load_table(path)
            except Exception:
                continue
            if df.empty or not _binary_columns(df):
                continue
            if _detect_id_column(df, feature_ids) is None:
                continue
            candidates.append(path)
    return sorted(candidates)


def inspect_analysis_inputs(
    project_path: str,
    feature_csv: str = "",
    clinical: str = "",
    id_col: str = "",
    label_col: str = "",
    covariates: Optional[List[str]] = None,
    output_dir: str = "",
) -> Dict[str, Any]:
    """Resolve analysis inputs; report ambiguity as clarification questions.

    Returns one of:
      - {"status": "ready", "resolved": {...}}  all inputs resolved
      - {"status": "need_clarification", "questions": [...], "detected": {...}}
      - {"status": "error", "message": str, "detected": {...}}
    """
    # 1. 特征文件
    if not feature_csv:
        feature_csv = os.path.join(
            project_path, "radiomics_features", "radiomics_features.csv")
    try:
        feature_df = _load_feature_csv(feature_csv)
    except (FileNotFoundError, ValueError) as e:
        return {"status": "error",
                "message": f"{e}。请先提取特征或通过 feature_csv 指定路径",
                "detected": {}}
    feature_ids = {_norm_id(v) for v in feature_df["patient_id"]}
    n_features = len([c for c in feature_df.columns
                      if any(c.startswith(p) for p in _RADIOMIC_PREFIXES)])
    detected: Dict[str, Any] = {
        "feature_csv": feature_csv,
        "n_feature_cases": int(len(feature_df)),
        "n_features": n_features,
    }

    # 2. 临床文件
    if not clinical:
        candidates = _find_clinical_candidates(
            project_path, feature_ids, exclude_path=feature_csv)
        if not candidates:
            return {"status": "error",
                    "message": "未在项目内找到可用的临床表格（需含 0/1 标签列且 "
                               "ID 与特征匹配），请通过 clinical 指定路径",
                    "detected": detected}
        if len(candidates) > 1:
            rel = [os.path.relpath(c, project_path) for c in candidates]
            return {"status": "need_clarification",
                    "questions": [{"field": "clinical",
                                   "question": "找到多个可能的临床表格，请指定使用哪一个",
                                   "candidates": rel}],
                    "detected": detected}
        clinical = candidates[0]
    try:
        clinical_df = _load_table(clinical)
    except (FileNotFoundError, ValueError) as e:
        return {"status": "error", "message": str(e), "detected": detected}
    except Exception as e:
        return {"status": "error",
                "message": f"读取临床表格失败: {e}",
                "detected": detected}
    detected["clinical"] = clinical

    questions: List[Dict[str, Any]] = []

    # 3. ID 列（与特征 patient_id 交集最大者）
    counts = _id_match_counts(clinical_df, feature_ids)
    if id_col:
        if id_col not in clinical_df.columns:
            return {"status": "error",
                    "message": f"指定的 ID 列 '{id_col}' 不存在",
                    "detected": detected}
        if counts.get(id_col, 0) == 0:
            feat_examples = sorted(feature_ids)[:3]
            clin_examples = sorted({_norm_id(v) for v in clinical_df[id_col].dropna()})[:3]
            return {"status": "error",
                    "message": f"指定的 ID 列 '{id_col}' 与特征 patient_id 无任何匹配"
                               f"（特征 ID 示例: {feat_examples}; 临床 ID 示例: {clin_examples}）",
                    "detected": detected}
    else:
        best = max(counts, key=counts.get) if counts else None
        best_n = counts.get(best, 0) if best else 0
        if best is None or best_n == 0:
            questions.append({
                "field": "id_col",
                "question": "临床表中没有任何列能与特征 patient_id 匹配，"
                            "请指定 ID 列（或检查是否选错临床表）",
                "candidates": list(clinical_df.columns),
            })
        else:
            ties = sorted([c for c, n in counts.items() if n == best_n])
            if len(ties) > 1:
                questions.append({
                    "field": "id_col",
                    "question": f"多列与特征 patient_id 的匹配数相同（{best_n} 例），"
                                "请指定 ID 列",
                    "candidates": ties,
                })
            else:
                id_col = best
    if id_col:
        detected["id_col"] = id_col
        detected["n_matched"] = counts.get(id_col, 0)

    # 4. 标签列
    if label_col:
        if label_col not in clinical_df.columns:
            return {"status": "error",
                    "message": f"指定的标签列 '{label_col}' 不存在",
                    "detected": detected}
        values = _binary_values(clinical_df[label_col])
        if values is None:
            return {"status": "error",
                    "message": f"标签列 '{label_col}' 必须为 0/1 二分类",
                    "detected": detected}
    else:
        binary_cols = _binary_columns(clinical_df, exclude=id_col or None)
        named = [c for c in binary_cols if c.lower() == "label"]
        if named:
            label_col = named[0]
        elif len(binary_cols) == 1:
            label_col = binary_cols[0]
        elif len(binary_cols) > 1:
            questions.append({
                "field": "label_col",
                "question": "临床表中有多个 0/1 列，哪一列是分组标签？",
                "candidates": binary_cols,
            })
        else:
            questions.append({
                "field": "label_col",
                "question": "未找到 0/1 二分类标签列，请指定 label_col",
                "candidates": list(clinical_df.columns),
            })
    if label_col:
        detected["label_col"] = label_col

    if questions:
        return {"status": "need_clarification",
                "questions": questions, "detected": detected}

    # 5. 协变量与输出目录
    valid_covariates = _infer_covariates(
        clinical_df, id_col, label_col, covariates or [])
    if not output_dir:
        output_dir = os.path.join(project_path, "radiomics_analysis")
    available = [c for c in clinical_df.columns if c not in {id_col, label_col}]

    return {"status": "ready", "resolved": {
        "feature_csv": feature_csv,
        "clinical": clinical,
        "id_col": id_col,
        "label_col": label_col,
        "covariates": valid_covariates,
        "output_dir": output_dir,
        "n_feature_cases": detected["n_feature_cases"],
        "n_features": n_features,
        "n_matched": counts.get(id_col, 0),
        "available_clinical_columns": available,
    }}
