from typing import List, Optional, Tuple

import os

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
                unique = set(df[col].dropna().astype(int).unique())
                if unique.issubset({0, 1}) and len(unique) == 2:
                    label_col = col
                    break
    if label_col is None:
        raise ValueError("无法识别临床表格中的标签列（需为 0/1 二分类），可用 --label-col 指定")

    # Validate label values
    if not set(df[label_col].dropna().astype(int).unique()).issubset({0, 1}):
        raise ValueError(f"标签列 '{label_col}' 必须仅包含 0/1")

    # Rename ID column to patient_id for downstream consistency
    if id_col != "patient_id":
        df = df.rename(columns={id_col: "patient_id"})
        id_col = "patient_id"

    return df, id_col, label_col


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
