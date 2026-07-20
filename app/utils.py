from typing import Any, Dict, List, Optional, Tuple

import os
import re

import pandas as pd


def parse_covariates(covs: str) -> List[str]:
    """Parse a comma-separated covariates string into a cleaned list."""
    return [c.strip() for c in (covs or "").split(",") if c.strip()]


def parse_float_tuple(value: str, expected_length: int = 3) -> Optional[Tuple[float, ...]]:
    """Parse a comma-separated float string into a tuple.

    Returns ``None`` for empty/whitespace input. Raises ``ValueError`` when
    the string cannot be parsed or does not contain exactly ``expected_length``
    values.
    """
    if not value or not value.strip():
        return None
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != expected_length:
        raise ValueError(f"需要 {expected_length} 个数值, 得到 {len(parts)}: {value}")
    return tuple(float(p) for p in parts)


def _load_feature_csv(path: str) -> pd.DataFrame:
    """Load a pre-extracted radiomic feature CSV.

    Supports either a ``patient_id`` column or a ``patient_id`` index. The
    returned DataFrame always has a regular ``patient_id`` column.

    Args:
        path: Path to the CSV file.

    Returns:
        A DataFrame with a ``patient_id`` column and radiomic feature columns.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If no patient identifier can be found.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"特征文件不存在: {path}")

    df = pd.read_csv(path)

    if "patient_id" in df.columns:
        return df

    # Try common ID column names
    for col in df.columns:
        if col.lower() in {"patientid", "patient_id", "id", "patient id"}:
            return df.rename(columns={col: "patient_id"})

    # Use index if it is named like an ID
    if df.index.name and df.index.name.lower() in {"patientid", "patient_id", "id"}:
        return df.reset_index().rename(columns={df.index.name: "patient_id"})

    # Last resort: if the first column is textual and uniquely identifies rows,
    # treat it as the patient ID. Numeric feature columns must not be mistaken
    # for an ID just because they happen to be unique.
    first_col = df.columns[0]
    if df[first_col].dtype == object and df[first_col].nunique() == len(df):
        return df.rename(columns={first_col: "patient_id"})

    raise ValueError(f"特征文件缺少 patient_id 列或索引: {path}")


def _load_clinical_for_analysis(path: str, label_col: Optional[str] = None) -> Tuple[pd.DataFrame, str, str]:
    """Load a clinical table and identify ID / label columns.

    Args:
        path: Path to a CSV or Excel clinical table.
        label_col: Optional explicit label column name.

    Returns:
        A tuple of ``(clinical_df, id_col, label_col)``.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the ID or label column cannot be identified.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"临床文件不存在: {path}")

    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        try:
            df = pd.read_csv(path, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="gbk")
    elif ext in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        raise ValueError(f"不支持的临床文件格式: {ext}")

    if df.empty:
        raise ValueError("临床表格为空")

    # Identify ID column
    id_col = None
    for col in df.columns:
        if col.lower() in {"patient_id", "patientid", "id", "patient id"}:
            id_col = col
            break
    if id_col is None:
        # Fallback: first column with all unique non-null values
        for col in df.columns:
            if df[col].notna().all() and df[col].nunique() == len(df):
                id_col = col
                break
    if id_col is None:
        raise ValueError("无法识别临床表格中的患者 ID 列")

    # Identify label column
    if label_col:
        if label_col not in df.columns:
            raise ValueError(f"指定的标签列 '{label_col}' 不存在")
    else:
        # Prefer exact "Label" (case-insensitive)
        for col in df.columns:
            if col.lower() == "label":
                label_col = col
                break
        # Otherwise find a binary 0/1 column
        if label_col is None:
            for col in df.columns:
                if col == id_col:
                    continue
                vals = df[col].dropna()
                try:
                    unique = set(pd.to_numeric(vals, errors="raise").unique())
                except (ValueError, TypeError):
                    continue
                if unique == {0, 1}:
                    label_col = col
                    break
    if label_col is None:
        raise ValueError("无法识别临床表格中的标签列（需为 0/1 二分类），可用 --label-col 指定")

    # Validate label values
    label_vals = df[label_col].dropna()
    try:
        unique = set(pd.to_numeric(label_vals, errors="raise").unique())
    except (ValueError, TypeError):
        unique = None
    if unique is None or not unique.issubset({0, 1}):
        raise ValueError(f"标签列 '{label_col}' 必须仅包含 0/1")

    # Rename ID column to patient_id for downstream consistency
    if id_col != "patient_id":
        df = df.rename(columns={id_col: "patient_id"})
        id_col = "patient_id"

    return df, id_col, label_col


_COMPOUND_ID_SEPARATORS = re.compile(r"[_\-]")


def _norm_match_id(value) -> str:
    """Normalize an ID for matching: strip, and collapse integral floats
    like "1.0" to "1"."""
    s = str(value).strip()
    if s.endswith(".0"):
        head = s[:-2]
        if head.lstrip("-").isdigit():
            return head
    return s


def resolve_id_matches(clinical_ids, feature_ids) -> Dict[str, Any]:
    """Resolve clinical-table IDs to feature-matrix patient_ids.

    Matching rules (conservative — rather miss than mismatch):

    1. Exact match after normalization (``_norm_match_id``).
    2. Compound IDs (containing ``_`` or ``-``) are split into parts; a
       clinical ID part-matches when exactly one of its parts equals a
       feature ID's full normalized form (or vice versa: a simple clinical
       ID equals one part of a compound feature ID), the candidate was not
       already taken by an exact match, and no other clinical ID claims it.
    3. Multiple candidates or multiple claimants → the clinical ID is
       listed in ``ambiguous`` and excluded, so callers can report it.

    Args:
        clinical_ids: IDs from the clinical table (any dtype).
        feature_ids: patient_ids from the feature matrix (any dtype).

    Returns:
        ``{"mapping": {临床原始ID字符串: 特征侧归一化ID}, "ambiguous": [...]}``
    """
    def _parts(norm: str) -> Tuple[str, ...]:
        return tuple(p for p in _COMPOUND_ID_SEPARATORS.split(norm) if p)

    feat_records = []  # (norm, parts)
    seen_norms = set()
    for v in feature_ids:
        norm = _norm_match_id(v)
        if norm in seen_norms:
            continue
        seen_norms.add(norm)
        feat_records.append((norm, set(_parts(norm))))

    clin_records = []  # (raw, norm, parts)
    for v in clinical_ids:
        norm = _norm_match_id(v)
        clin_records.append((str(v), norm, set(_parts(norm))))

    # 1. 精确匹配
    mapping: Dict[str, str] = {}
    used_feat_norms = set()
    remaining = []
    for raw, norm, parts in clin_records:
        if norm in seen_norms and norm not in used_feat_norms:
            mapping[raw] = norm
            used_feat_norms.add(norm)
        else:
            remaining.append((raw, norm, parts))

    # 2. 部分匹配：候选唯一才接受
    cand_of: Dict[str, str] = {}   # clin_raw -> 唯一候选 feat_norm
    claims: Dict[str, List[str]] = {}  # feat_norm -> [clin_raw, ...]
    ambiguous = []
    for raw, norm, parts in remaining:
        candidates = set()
        for fnorm, fparts in feat_records:
            if fnorm in used_feat_norms:
                continue
            if (len(parts) > 1 and fnorm in parts) or (
                    len(fparts) > 1 and norm in fparts):
                candidates.add(fnorm)
        if len(candidates) == 1:
            fnorm = next(iter(candidates))
            cand_of[raw] = fnorm
            claims.setdefault(fnorm, []).append(raw)
        elif len(candidates) > 1:
            ambiguous.append(raw)

    # 3. 同一特征 ID 被多个临床 ID 认领 → 全部视为歧义
    for raw, fnorm in cand_of.items():
        if len(claims[fnorm]) > 1:
            ambiguous.append(raw)
        else:
            mapping[raw] = fnorm

    return {"mapping": mapping, "ambiguous": sorted(ambiguous)}


def _merge_feature_clinical(
    feature_df: pd.DataFrame,
    clinical_df: pd.DataFrame,
    id_col: str = "patient_id",
) -> pd.DataFrame:
    """Inner-merge feature matrix with clinical table on the ID column.

    Args:
        feature_df: DataFrame containing the ID column and radiomic features.
        clinical_df: DataFrame containing the ID column and clinical info.
        id_col: Name of the ID column (default ``patient_id``).

    Returns:
        The merged DataFrame with ID, label, clinical covariates and features.

    Raises:
        ValueError: If the ID columns have no common values.
    """
    if id_col not in feature_df.columns:
        raise ValueError(f"特征矩阵缺少 ID 列: {id_col}")
    if id_col not in clinical_df.columns:
        raise ValueError(f"临床表格缺少 ID 列: {id_col}")

    merged = clinical_df.merge(feature_df, on=id_col, how="inner")
    if merged.empty:
        raise ValueError(
            f"特征矩阵与临床表格无共同患者 ID。"
            f"特征 ID 示例: {feature_df[id_col].head(3).tolist()}; "
            f"临床 ID 示例: {clinical_df[id_col].head(3).tolist()}"
        )
    return merged


def _infer_covariates(
    clinical_df: pd.DataFrame,
    id_col: str,
    label_col: str,
    explicit_covariates: List[str],
) -> List[str]:
    """Return the list of covariate columns to use in the regression.

    Explicit covariates are validated against the clinical table. If none are
    provided, an empty list is returned so that only LASSO-selected radiomic
    features are used.

    Args:
        clinical_df: Clinical DataFrame.
        id_col: Name of the ID column.
        label_col: Name of the label column.
        explicit_covariates: User-specified covariate names.

    Returns:
        A filtered list of covariate column names present in the table.
    """
    if not explicit_covariates:
        return []

    available = set(clinical_df.columns)
    valid = [c for c in explicit_covariates if c in available and c not in {id_col, label_col}]
    return valid
