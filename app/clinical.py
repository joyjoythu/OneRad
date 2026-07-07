import difflib
import os
import re
from typing import Optional, List, Dict, Any

import pandas as pd

import logging
logger = logging.getLogger(__name__)


class ClinicalAgent:
    """Agent for identifying and validating clinical data table columns."""

    SUPPORTED_EXTS = {".csv", ".xlsx", ".xls"}

    def __init__(self, llm_client=None, max_retries: int = 2):
        """Initialize the clinical agent.

        Args:
            llm_client: Optional client for calling the LLM to identify columns.
            max_retries: Number of retries on top of the first LLM call attempt.
        """
        self.llm_client = llm_client
        self.max_retries = max_retries

    def run(self, clinical_path: str, task_hint: str = "") -> dict:
        """Read a clinical table and identify the ID, label and feature columns.

        Args:
            clinical_path: Path to a CSV or Excel clinical table.
            task_hint: Optional task description passed to the LLM.

        Returns:
            A dictionary with keys including ``success``, ``message``, ``df``,
            ``id_col``, ``label_col``, ``feature_cols``, ``id_dtype`` and
            ``n_samples`` on success, or ``success`` / ``message`` on failure.
        """
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

        # ID column uniqueness check (null IDs are excluded from both sides)
        id_non_null = df.dropna(subset=[id_col])
        if id_non_null[id_col].nunique(dropna=True) != len(id_non_null):
            return {"success": False, "message": f"ID 列 '{id_col}' 存在重复值"}

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
        """Build a structured description of each column for the LLM prompt.

        Args:
            df: Input DataFrame.
            task_hint: Optional task description.

        Returns:
            Dictionary containing row/column counts, task hint and column metadata.
        """
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
        """Ask the LLM to identify columns, retrying on failure.

        Args:
            context: Column context built by ``_build_column_context``.

        Returns:
            Parsed JSON dict from the LLM, or an error dict on failure.
        """
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
        """Validate and normalize LLM-identified column selections.

        Normalizes boolean / float 0/1 labels to integers, rejects empty labels,
        and rejects label values outside the allowed set.

        Args:
            df: Input DataFrame.
            parsed: Parsed LLM response with ``id_col``, ``label_col`` and
                ``feature_cols``.

        Returns:
            Normalized result dict with ``id_col``, ``label_col`` and
            ``feature_cols`` on success, or an error dict on failure.
        """
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

        # label value validation: normalize booleans/floats 0/1 to int and reject
        # columns that are all null or contain values outside the allowed set.
        allowed = {0, 1, True, False, 0.0, 1.0}
        labels = df[label_col]
        valid_labels = labels.dropna()
        if valid_labels.empty:
            return {"success": False, "message": f"Label 列 '{label_col}' 全部缺失"}

        if not set(valid_labels).issubset(allowed):
            return {
                "success": False,
                "message": f"Label 列 '{label_col}' 值域非 0/1: {valid_labels.unique().tolist()}",
            }

        # Normalize in-place to int 0/1
        df[label_col] = labels.map(lambda x: int(x) if pd.notna(x) else x)

        return {
            "success": True,
            "id_col": id_col,
            "label_col": label_col,
            "feature_cols": feature_cols,
        }


def _normalize_id(id_str: str) -> str:
    if not isinstance(id_str, str):
        id_str = str(id_str)
    s = id_str.strip()
    s = re.sub(r"\.(nii\.gz|nii|dcm|mha|mhd|raw|nrrd)$", "", s, flags=re.IGNORECASE)
    return s.lower()


def run_matching(discovery_pairs: List[Dict[str, Any]], clinical_df: pd.DataFrame, id_col: str,
                 fuzzy_threshold: float = 0.8, enable_fuzzy: bool = True) -> dict:
    """Match image discovery pairs against clinical records by patient ID.

    Normalized IDs are used for comparison: lower-cased, stripped, and with
    common image extensions removed.  The returned ``matched_df`` uses the
    original image-side ``patient_id`` in its ``patient_id`` column, while
    ``match_method`` reports ``"exact"`` or ``"fuzzy"`` and ``fuzzy_map``
    records any image -> clinical normalized-ID mappings produced by fuzzy
    matching.

    Args:
        discovery_pairs: List of dicts with ``patient_id``, ``image_path`` and
            ``mask_path``.
        clinical_df: Clinical DataFrame containing ``id_col``.
        id_col: Name of the clinical ID column.
        fuzzy_threshold: Minimum similarity ratio for fuzzy matches.
        enable_fuzzy: Whether to enable fuzzy matching for unmatched IDs.

    Returns:
        Dict with ``success``, ``message``, and on success ``matched_df``,
        ``matched_ids``, ``unmatched_image_ids``, ``unmatched_clinical_ids``,
        ``match_method``, ``match_stats`` and ``fuzzy_map``.
    """
    if not discovery_pairs:
        return {"success": False, "message": "Discovery pairs 为空"}
    if clinical_df is None or clinical_df.empty:
        return {"success": False, "message": "临床表格为空"}
    if id_col not in clinical_df.columns:
        return {"success": False, "message": f"ID 列 '{id_col}' 不存在"}

    image_ids = set()
    img_norm_to_orig = {}
    for p in discovery_pairs:
        pid = p.get("patient_id")
        if pid is None:
            return {"success": False, "message": "pair 缺少 patient_id"}
        norm = _normalize_id(pid)
        image_ids.add(norm)
        img_norm_to_orig[norm] = pid

    clinical_norm_series = clinical_df[id_col].astype(str).apply(_normalize_id)

    # Detect distinct original clinical IDs that collapse to the same normalized key.
    norm_to_originals = {}
    for norm, orig in zip(clinical_norm_series, clinical_df[id_col].astype(str)):
        norm_to_originals.setdefault(norm, set()).add(orig)
    duplicate_norms = [norm for norm, origs in norm_to_originals.items() if len(origs) > 1]
    if duplicate_norms:
        return {
            "success": False,
            "message": f"临床 ID 列归一化后存在重复: {duplicate_norms}",
        }

    clinical_ids = set(clinical_norm_series)
    clinical_norm_to_orig = dict(zip(clinical_norm_series, clinical_df[id_col].astype(str)))

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
    norm_to_original = dict(zip(clinical_df["__norm_id__"], clinical_df[id_col].astype(str)))

    rows = []
    for norm_id in matched:
        pair = norm_to_pair.get(norm_id)
        if pair is None:
            continue
        target_norm = fuzzy_map.get(norm_id, norm_id)
        original_id = norm_to_original.get(target_norm)
        if original_id is None:
            continue
        row_df = clinical_df[clinical_df[id_col].astype(str) == original_id]
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

    unmatched_image_ids = sorted({img_norm_to_orig[n] for n in unmatched_img})
    unmatched_clinical_ids = sorted({clinical_norm_to_orig[n] for n in unmatched_cli})

    return {
        "success": True,
        "message": f"匹配完成: {len(matched_df)} 例",
        "matched_df": matched_df,
        "matched_ids": matched_df["patient_id"].tolist(),
        "unmatched_image_ids": unmatched_image_ids,
        "unmatched_clinical_ids": unmatched_clinical_ids,
        "match_method": method,
        "fuzzy_map": fuzzy_map,
        "match_stats": {
            "total_images": len(discovery_pairs),
            "total_clinical": len(clinical_df),
            "matched": len(matched_df),
            "unmatched_images": len(unmatched_img),
            "unmatched_clinical": len(unmatched_cli),
        },
    }
