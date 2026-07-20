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

from app.curves import plot_calibration_curve, plot_dca, plot_roc_curve
from app.utils import (
    _load_feature_csv,
    _merge_feature_clinical,
    _infer_covariates,
    _norm_match_id,
    fmt_num,
    fmt_p,
    resolve_id_matches,
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

    Note: This function may load and scan CSV/XLSX files in the project
    directory. It is designed to be called from a worker thread (the
    LangGraph sync node executor already runs sync nodes in a thread pool).
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
        if counts.get(id_col, 0) == 0 and not resolve_id_matches(
                clinical_df[id_col].tolist(),
                feature_df["patient_id"].tolist())["mapping"]:
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
        # 精确匹配之外，复合 ID（住院号_拼音）可按唯一部分匹配计入；
        # 歧义 ID 被排除并记录，供上层向用户报告。
        resolution = resolve_id_matches(
            clinical_df[id_col].tolist(), feature_df["patient_id"].tolist())
        detected["n_matched"] = len(resolution["mapping"])
        detected["ambiguous_ids"] = resolution["ambiguous"]

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
        if len(values) < 2:
            return {"status": "error",
                    "message": f"标签列 '{label_col}' 必须同时包含 0 和 1（当前仅含 {sorted(values)}）",
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
        "n_matched": detected["n_matched"],
        "ambiguous_ids": detected.get("ambiguous_ids", []),
        "available_clinical_columns": available,
    }}


def _render_markdown_report(analysis_result: Dict[str, Any],
                            outputs: Dict[str, Any],
                            n_matched: int,
                            covariates: List[str],
                            output_dir: str,
                            n_splits: int = 5) -> str:
    """Render a Markdown report next to the Word one; returns its path."""
    m = analysis_result["metrics"]
    lines = [
        "# 影像组学分析报告",
        "",
        "## 1. 方法",
        "",
        f"共纳入 {analysis_result['n_samples']} 例患者"
        f"（特征与临床表匹配 {n_matched} 例）。"
        f"采用分层 {n_splits} 折交叉验证：每折内对特征标准化后用 LassoCV 选择影像组学特征，"
        "再以逻辑回归训练并预测留出折，汇总得到每例的 out-of-fold 预测概率；"
        "各折选中特征取交集作为稳定特征集，并在全量数据上拟合最终模型。",
    ]
    if covariates:
        lines.append(f"临床协变量：{', '.join(covariates)}。")
    lines += [
        "",
        "## 2. 模型性能",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| AUC | {m['auc']:.3f} (95% CI {m['auc_ci'][0]:.3f}\u2013{m['auc_ci'][1]:.3f}) |",
        f"| 准确率 | {m['accuracy']:.3f} |",
        f"| 敏感度 | {m['sensitivity']:.3f} |",
        f"| 特异度 | {m['specificity']:.3f} |",
        f"| PPV | {fmt_num(m.get('ppv'))} |",
        f"| NPV | {fmt_num(m.get('npv'))} |",
        f"| F1 | {fmt_num(m.get('f1'))} |",
        f"| 最佳阈值 | {m['threshold']:.3f} |",
        "",
        f"混淆矩阵（[[TN, FP], [FN, TP]]）：`{m['confusion_matrix']}`",
    ]
    cv = analysis_result.get("cv_metrics")
    if cv and cv.get("folds"):
        lines += [
            "",
            f"{n_splits} 折交叉验证逐折指标：",
            "",
            "| 折 | AUC | 准确率 | 敏感度 | 特异度 | PPV | NPV | F1 | 阈值 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for f in cv["folds"]:
            lines.append(
                f"| {f['fold']} | {fmt_num(f['auc'])} | {fmt_num(f['accuracy'])} "
                f"| {fmt_num(f['sensitivity'])} | {fmt_num(f['specificity'])} "
                f"| {fmt_num(f['ppv'])} | {fmt_num(f['npv'])} | {fmt_num(f['f1'])} "
                f"| {fmt_num(f['threshold'])} |")
        mean, std = cv["mean"], cv["std"]
        lines.append(
            f"| 均值±标准差 | {fmt_num(mean['auc'])}±{fmt_num(std['auc'])} "
            f"| {fmt_num(mean['accuracy'])}±{fmt_num(std['accuracy'])} "
            f"| {fmt_num(mean['sensitivity'])}±{fmt_num(std['sensitivity'])} "
            f"| {fmt_num(mean['specificity'])}±{fmt_num(std['specificity'])} "
            f"| {fmt_num(mean['ppv'])}±{fmt_num(std['ppv'])} "
            f"| {fmt_num(mean['npv'])}±{fmt_num(std['npv'])} "
            f"| {fmt_num(mean['f1'])}±{fmt_num(std['f1'])} "
            f"| {fmt_num(mean['threshold'])}±{fmt_num(std['threshold'])} |")
    lines += [
        "",
        "## 3. 稳定特征与回归系数",
        "",
        "| 特征 | 系数 | OR | 95%CI | p |",
        "|---|---|---|---|---|",
    ]
    mr = analysis_result["model_results"]
    for feat in sorted(analysis_result["selected_features"]):
        ci_lo = mr["ci_lower"].get(feat)
        ci_hi = mr["ci_upper"].get(feat)
        ci = f"{ci_lo:.3f}\u2013{ci_hi:.3f}" if ci_lo is not None and ci_hi is not None else "-"
        lines.append(
            f"| {feat} | {fmt_num(mr['coefficients'].get(feat, 0))} "
            f"| {fmt_num(mr['odds_ratios'].get(feat, 0))} | {ci} "
            f"| {fmt_p(mr['p_values'].get(feat, 1))} |")
    lines += ["", "## 4. 图表", ""]
    for key, caption in (("roc_curve", "ROC 曲线"),
                         ("calibration_curve", "校准曲线"),
                         ("dca_curve", "决策曲线")):
        path = outputs.get(key)
        if path:
            lines.append(f"![{caption}]({os.path.basename(path)})")
            lines.append("")
    lines.append(f"注：预测概率为 {n_splits} 折交叉验证的 out-of-fold 概率，"
                 "用于无偏评估模型性能。")
    report_path = os.path.join(output_dir, "report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return report_path


def run_radiomics_cv_analysis(
    feature_csv: str,
    clinical: str,
    output_dir: str,
    id_col: Optional[str] = None,
    label_col: Optional[str] = None,
    covariates: Optional[List[str]] = None,
    max_lasso_features: int = 100,
    n_splits: int = 5,
    random_state: int = 42,
    llm_client=None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """Run LASSO + logistic regression CV analysis and export all artifacts.

    The caller is expected to have resolved ``id_col``/``label_col`` first
    (see ``inspect_analysis_inputs``). Returns a dict with ``success``,
    ``message``, and on success ``analysis_result`` (the raw AnalysisAgent
    result), ``n_matched`` and ``outputs`` (artifact paths).
    """
    from app.analysis import AnalysisAgent
    from app.report import ReportAgent

    def _cancelled() -> bool:
        return should_cancel is not None and should_cancel()

    try:
        feature_df = _load_feature_csv(feature_csv)
        clinical_df = _load_table(clinical)
    except (FileNotFoundError, ValueError) as e:
        return {"success": False, "message": str(e)}

    if id_col is None:
        return {"success": False,
                "message": "id_col 未指定（请先经 inspect_analysis_inputs 识别）"}
    if not id_col:
        return {"success": False,
                "message": "id_col 未指定（请先经 inspect_analysis_inputs 识别）"}
    if id_col:
        if id_col not in clinical_df.columns:
            return {"success": False, "message": f"ID 列 '{id_col}' 不存在"}
        if id_col != "patient_id":
            clinical_df = clinical_df.rename(columns={id_col: "patient_id"})
    if label_col is None:
        return {"success": False,
                "message": "label_col 未指定（请先经 inspect_analysis_inputs 识别）"}
    if label_col not in clinical_df.columns:
        return {"success": False, "message": f"标签列 '{label_col}' 不存在"}

    label_values = _binary_values(clinical_df[label_col])
    if label_values is None:
        return {"success": False, "message": f"标签列 '{label_col}' 必须仅包含 0/1"}

    # ID 解析：复合临床 ID（如 住院号_拼音）按唯一部分匹配到特征
    # patient_id；歧义 ID 被排除并在结果中报告。合并前把两侧 ID 统一为
    # 归一化键，避免 dtype（int/str）或格式差异导致漏配。
    resolution = resolve_id_matches(
        clinical_df["patient_id"].tolist(), feature_df["patient_id"].tolist())
    id_map = resolution["mapping"]
    ambiguous_ids = resolution["ambiguous"]
    feature_df = feature_df.copy()
    clinical_df = clinical_df.copy()
    feature_df["patient_id"] = feature_df["patient_id"].map(_norm_match_id)
    clinical_df["patient_id"] = clinical_df["patient_id"].map(
        lambda v: id_map.get(str(v), _norm_match_id(v)))

    try:
        merged_df = _merge_feature_clinical(feature_df, clinical_df, id_col="patient_id")
    except ValueError as e:
        return {"success": False, "message": str(e)}

    if merged_df[label_col].isna().any():
        return {"success": False, "message": f"标签列 '{label_col}' 存在缺失值"}
    if merged_df[label_col].nunique() < 2:
        return {"success": False, "message": f"标签列 '{label_col}' 必须同时包含 0 和 1"}

    y = merged_df[label_col].astype(int)
    min_class = int(y.value_counts().min()) if y.nunique() > 1 else 0
    if min_class < n_splits:
        return {"success": False,
                "message": f"某类样本数（{min_class}）小于折数 {n_splits}，"
                           "请减少折数或检查标签"}

    covariates = _infer_covariates(clinical_df, "patient_id", label_col,
                                   covariates or [])
    n_features = len([c for c in feature_df.columns
                      if any(c.startswith(p) for p in _RADIOMIC_PREFIXES)])

    if _cancelled():
        return {"success": False, "cancelled": True, "message": "用户取消了分析"}

    os.makedirs(output_dir, exist_ok=True)
    agent = AnalysisAgent(
        covariates=covariates,
        max_lasso_features=max_lasso_features,
        n_splits=n_splits,
        random_state=random_state,
        output_dir=output_dir,
    )
    analysis_result = agent.run(merged_df, label_col=label_col)
    if not analysis_result.get("success"):
        return {"success": False,
                "message": f"分析失败: {analysis_result.get('message', '未知错误')}"}

    if _cancelled():
        return {"success": False, "cancelled": True, "message": "用户取消了分析"}

    outputs: Dict[str, Any] = {"lasso_paths": analysis_result.get("plot_paths", [])}

    # 每病例预测概率
    oof = analysis_result.get("oof_probabilities", [])
    threshold = analysis_result["metrics"]["threshold"]
    case_df = pd.DataFrame({
        "patient_id": merged_df["patient_id"].values,
        "y_true": y.values,
        "oof_prob": np.round(np.asarray(oof, dtype=float), 3),
        "y_pred": [int(p >= threshold) for p in oof],
    })
    case_path = os.path.join(output_dir, "case_predictions.csv")
    case_df.to_csv(case_path, index=False)
    outputs["case_predictions"] = case_path

    # 稳定特征系数表（p_value 保留原始精度，其余数值列 3 位小数）
    mr = analysis_result["model_results"]
    selected = analysis_result["selected_features"]
    feat_df = pd.DataFrame({
        "feature": selected,
        "coefficient": [mr["coefficients"].get(f) for f in selected],
        "odds_ratio": [mr["odds_ratios"].get(f) for f in selected],
        "ci_lower": [mr["ci_lower"].get(f) for f in selected],
        "ci_upper": [mr["ci_upper"].get(f) for f in selected],
        "p_value": [mr["p_values"].get(f) for f in selected],
    })
    feat_df = feat_df.round(
        {"coefficient": 3, "odds_ratio": 3, "ci_lower": 3, "ci_upper": 3})
    feat_path = os.path.join(output_dir, "selected_features.csv")
    feat_df.to_csv(feat_path, index=False)
    outputs["selected_features"] = feat_path

    # 曲线（单张失败只记 warning，不中断）
    new_plots: List[str] = []
    y_arr = y.values.astype(float)
    oof_arr = np.asarray(oof, dtype=float)
    curve_specs: Tuple[Tuple[str, Callable, Dict[str, Any]], ...] = (
        ("roc_curve", plot_roc_curve,
         {"auc": analysis_result["metrics"]["auc"],
          "auc_ci": analysis_result["metrics"]["auc_ci"]}),
        ("calibration_curve", plot_calibration_curve, {}),
        ("dca_curve", plot_dca, {}),
    )
    for key, func, kwargs in curve_specs:
        try:
            out_path = os.path.join(output_dir, f"{key}.png")
            path = func(y_arr, oof_arr, out_path=out_path, **kwargs)
            outputs[key] = path
            new_plots.append(path)
        except Exception:
            logger.warning("绘制 %s 失败", key, exc_info=True)
            outputs[key] = None

    if _cancelled():
        return {"success": False, "cancelled": True, "message": "用户取消了分析"}

    # Word 报告（现有 ReportAgent，新图随 plot_paths 一并嵌入）
    report_result = ReportAgent().run(
        analysis_result=analysis_result,
        output_dir=output_dir,
        modality="auto",
        n_features=n_features,
        covariates=covariates,
        plot_paths=analysis_result.get("plot_paths", []) + new_plots,
        llm_client=llm_client,
    )
    if not report_result.get("success"):
        return {"success": False,
                "message": f"报告生成失败: {report_result.get('message', '未知错误')}"}
    outputs["report_docx"] = report_result["report_path"]

    outputs["report_md"] = _render_markdown_report(
        analysis_result, outputs, int(len(merged_df)), covariates, output_dir,
        n_splits=n_splits)

    message = "分析完成"
    if ambiguous_ids:
        message += (f"；{len(ambiguous_ids)} 例临床 ID 存在歧义未纳入分析: "
                    + ", ".join(ambiguous_ids))
    return {
        "success": True,
        "message": message,
        "analysis_result": analysis_result,
        "n_matched": int(len(merged_df)),
        "ambiguous_ids": ambiguous_ids,
        "outputs": outputs,
    }
