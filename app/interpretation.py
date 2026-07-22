"""LLM 结果解读：聚合分析数值摘要、调用 LLM 生成中文解读并注入报告。

三个入口：

- ``build_summary``：把 analysis_result 与 shap/ 下的逐折 SHAP CSV 聚合为
  纯数值摘要 dict（指标、逐折稳定性、选中特征系数、SHAP 重要性）。
- ``interpret``：用摘要调用 LLM（system prompt 来自
  ``skills/result-interpretation``），按约定分隔标记解析为
  ``{"performance", "features", "shap"}`` 三段中文 markdown。
- ``apply_to_reports``：用解读结果重新生成 report.md 与 report.docx；
  幂等，重复调用不会叠加小节。
"""

import glob
import json
import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.skills import load_skill

logger = logging.getLogger(__name__)

# LLM 输出三段解读的约定分隔标记（与 skills/result-interpretation 的 prompt 一致）。
SECTION_MARKERS = {
    "performance": "【模型性能解读】",
    "features": "【特征意义解读】",
    "shap": "【SHAP可解释性解读】",
}
SECTION_ORDER = ("performance", "features", "shap")

_TOP_SHAP_FEATURES = 15


def parse_feature_name(name: str) -> Dict[str, str]:
    """把特征名拆为 滤波器/特征类/特征名 三段。

    如 ``wavelet-LLH_glcm_Contrast`` →
    ``{"filter": "wavelet-LLH", "feature_class": "glcm", "feature_name": "Contrast"}``。
    段数不足时缺失段置空字符串。
    """
    parts = str(name).split("_", 2)
    if len(parts) == 3:
        return {"filter": parts[0], "feature_class": parts[1],
                "feature_name": parts[2]}
    if len(parts) == 2:
        return {"filter": "", "feature_class": parts[0], "feature_name": parts[1]}
    return {"filter": "", "feature_class": "", "feature_name": str(name)}


def _direction(value) -> Optional[str]:
    """数值符号 → "positive" / "negative" / "zero"；无法判断时 None。"""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    value = float(value)
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "zero"


def _round_floats(obj: Any, ndigits: int = 4) -> Any:
    """递归把数值压到 ndigits 位小数、numpy 标量转原生类型，控制 prompt 体量。"""
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return round(float(obj), ndigits)
    if isinstance(obj, dict):
        return {k: _round_floats(v, ndigits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round_floats(v, ndigits) for v in obj]
    return obj


def build_summary(analysis_result: Dict[str, Any], output_dir: str) -> Dict[str, Any]:
    """聚合纯数值摘要：指标、逐折稳定性、选中特征系数、SHAP 重要性。

    SHAP 部分读取 ``output_dir/shap/shap_values_fold*.csv``：每特征逐折
    mean|SHAP| 再跨折平均得到全局重要性（取 top 15），折覆盖次数为该特征
    在几折出现，方向取逐折 mean SHAP 符号，并与回归系数方向比对。
    CSV 缺失或部分折缺失时按可用折聚合，``n_folds`` 记录实际聚合折数。
    """
    metrics = analysis_result.get("metrics") or {}
    cm = metrics.get("confusion_matrix") or [[0, 0], [0, 0]]
    (tn, fp), (fn, tp) = cm[0], cm[1]

    mr = analysis_result.get("model_results") or {}
    coefficients = mr.get("coefficients") or {}
    features: List[Dict[str, Any]] = []
    for feat in analysis_result.get("selected_features") or []:
        coef = coefficients.get(feat)
        features.append({
            "feature": feat,
            **parse_feature_name(feat),
            "coefficient": coef,
            "coefficient_direction": _direction(coef),
            "odds_ratio": (mr.get("odds_ratios") or {}).get(feat),
            "ci_lower": (mr.get("ci_lower") or {}).get(feat),
            "ci_upper": (mr.get("ci_upper") or {}).get(feat),
            "p_value": (mr.get("p_values") or {}).get(feat),
        })

    summary = {
        "n_samples": analysis_result.get("n_samples"),
        "n_positive": int(fn) + int(tp),
        "n_negative": int(tn) + int(fp),
        "metrics": metrics,
        "cv_metrics": analysis_result.get("cv_metrics") or {},
        "features": features,
        "shap": _aggregate_shap(output_dir, coefficients),
    }
    return _round_floats(summary)


def _aggregate_shap(output_dir: str,
                    coefficients: Dict[str, Any]) -> Dict[str, Any]:
    """跨折聚合 shap/shap_values_fold*.csv，返回重要性 top 特征与折数。"""
    files = sorted(glob.glob(os.path.join(
        output_dir, "shap", "shap_values_fold*.csv")))
    per_feature: Dict[str, Dict[str, List[float]]] = {}
    n_loaded = 0
    for path in files:
        try:
            df = pd.read_csv(path)
        except Exception:
            logger.warning("读取 SHAP CSV 失败，已跳过: %s", path, exc_info=True)
            continue
        n_loaded += 1
        for col in df.columns:
            if col == "patient_id":
                continue
            vals = pd.to_numeric(df[col], errors="coerce").dropna()
            if vals.empty:
                continue
            entry = per_feature.setdefault(col, {"abs": [], "signed": []})
            entry["abs"].append(float(vals.abs().mean()))
            entry["signed"].append(float(vals.mean()))

    top: List[Dict[str, Any]] = []
    for feat, entry in per_feature.items():
        mean_abs = sum(entry["abs"]) / len(entry["abs"])
        mean_signed = sum(entry["signed"]) / len(entry["signed"])
        shap_dir = _direction(mean_signed)
        coef_dir = _direction(coefficients.get(feat))
        if shap_dir in ("positive", "negative") and coef_dir in ("positive", "negative"):
            consistent: Optional[bool] = shap_dir == coef_dir
        else:
            consistent = None
        top.append({
            "feature": feat,
            **parse_feature_name(feat),
            "mean_abs_shap": mean_abs,
            "mean_shap": mean_signed,
            "fold_coverage": len(entry["abs"]),
            "shap_direction": shap_dir,
            "coefficient_direction": coef_dir,
            "direction_consistent": consistent,
        })
    top.sort(key=lambda d: d["mean_abs_shap"], reverse=True)
    return {"n_folds": n_loaded, "top_features": top[:_TOP_SHAP_FEATURES]}


def interpret(summary: Dict[str, Any], llm_client) -> Dict[str, str]:
    """调用 LLM 生成三段中文解读，按约定分隔标记解析。

    返回 ``{"performance", "features", "shap"}``。LLM 调用失败或返回格式
    异常（缺标记、顺序错乱、段落为空）时抛异常，由调用方优雅回退。
    """
    system = load_skill("result-interpretation")
    user = ("以下是影像组学分析的数值摘要（JSON），请按系统要求输出三段解读：\n"
            + json.dumps(summary, ensure_ascii=False, indent=2))
    text = llm_client.call(system, user, temperature=0.3, max_tokens=2500)
    return _parse_sections(text or "")


def _parse_sections(text: str) -> Dict[str, str]:
    """按 SECTION_MARKERS 拆分 LLM 输出；任何标记缺失/乱序/空段都抛 ValueError。"""
    spans = []
    for key in SECTION_ORDER:
        marker = SECTION_MARKERS[key]
        idx = text.find(marker)
        if idx == -1:
            raise ValueError(f"LLM 返回缺少分隔标记 {marker}")
        spans.append((key, idx, idx + len(marker)))
    for (_, start, _), (_, next_start, _) in zip(spans, spans[1:]):
        if next_start <= start:
            raise ValueError("LLM 返回的分隔标记顺序异常")
    sections: Dict[str, str] = {}
    for i, (key, _, end) in enumerate(spans):
        stop = spans[i + 1][1] if i + 1 < len(spans) else len(text)
        sections[key] = text[end:stop].strip()
    empty = [k for k, v in sections.items() if not v]
    if empty:
        raise ValueError(f"LLM 返回的解读段落为空: {', '.join(empty)}")
    return sections


def apply_to_reports(analysis_result: Dict[str, Any], output_dir: str,
                     interpretation: Dict[str, str]) -> Dict[str, str]:
    """重新生成 report.md 与 report.docx 并注入解读小节。

    两份报告都是整体重写，重复调用结果一致（幂等）。重建所需的上下文
    （协变量、折数、特征总数、图表路径）从输出目录磁盘产物恢复：
    ``analysis_params.json`` + 标准命名的 PNG 文件。返回两份报告路径。
    """
    from app.radiomics_analysis import _render_markdown_report
    from app.report import ReportAgent

    ar = dict(analysis_result)
    ar.setdefault("success", True)
    ctx = _load_report_context(ar, output_dir)

    report_md = _render_markdown_report(
        ar, ctx["outputs"], ar.get("n_samples") or 0, ctx["covariates"],
        output_dir, n_splits=ctx["n_splits"], interpretation=interpretation)
    report_result = ReportAgent().run(
        analysis_result=ar,
        output_dir=output_dir,
        modality="auto",
        n_features=ctx["n_features"],
        covariates=ctx["covariates"],
        plot_paths=ctx["plot_paths"],
        interpretation=interpretation,
    )
    if not report_result.get("success"):
        raise RuntimeError(
            f"report.docx 重新生成失败: {report_result.get('message', '未知错误')}")
    return {"report_md": report_md, "report_docx": report_result["report_path"]}


def _load_report_context(analysis_result: Dict[str, Any],
                         output_dir: str) -> Dict[str, Any]:
    """从磁盘恢复报告重建上下文；任何缺失都回退缺省值，不阻断解读。"""
    params: Dict[str, Any] = {}
    params_path = os.path.join(output_dir, "analysis_params.json")
    if os.path.exists(params_path):
        try:
            with open(params_path, "r", encoding="utf-8") as f:
                params = json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("读取 analysis_params.json 失败，报告上下文用缺省值",
                           exc_info=True)

    covariates = list(params.get("covariates") or [])
    n_splits = params.get("n_splits")
    if not n_splits:
        folds = (analysis_result.get("cv_metrics") or {}).get("folds") or []
        n_splits = len(folds) or 5
    n_features = (_count_radiomic_features(output_dir, params)
                  or len(analysis_result.get("selected_features") or []))

    outputs = _probe_outputs(output_dir)
    # 与分析流程一致：fold1 LASSO path + 全部 SHAP 图 + ROC/校准/DCA 曲线
    plot_paths = list(outputs.get("lasso_paths") or [])[:1]
    plot_paths += list(outputs.get("shap_plots") or [])
    plot_paths += [outputs[k] for k in ("roc_curve", "calibration_curve", "dca_curve")
                   if outputs.get(k)]
    return {
        "covariates": covariates,
        "n_splits": int(n_splits),
        "n_features": int(n_features),
        "outputs": outputs,
        "plot_paths": plot_paths,
    }


def _count_radiomic_features(output_dir: str,
                             params: Dict[str, Any]) -> Optional[int]:
    """按参数快照里的特征 CSV 统计影像组学特征总数；失败返回 None。"""
    feature_csv = params.get("feature_csv")
    project_root = params.get("project_root")
    if not feature_csv or not project_root:
        return None
    path = os.path.normpath(os.path.join(output_dir, project_root, feature_csv))
    if not os.path.exists(path):
        return None
    try:
        from app.radiomics_analysis import _RADIOMIC_PREFIXES
        header = pd.read_csv(path, nrows=0)
    except Exception:
        logger.warning("统计特征总数失败: %s", path, exc_info=True)
        return None
    return len([c for c in header.columns
                if any(c.startswith(p) for p in _RADIOMIC_PREFIXES)])


def _probe_outputs(output_dir: str) -> Dict[str, Any]:
    """按标准文件名探测输出目录里已存在的图表，重建 outputs dict。"""
    outputs: Dict[str, Any] = {}
    for key in ("roc_curve", "calibration_curve", "dca_curve"):
        path = os.path.join(output_dir, f"{key}.png")
        if os.path.exists(path):
            outputs[key] = path
    lasso = sorted(glob.glob(os.path.join(
        output_dir, "lasso", "lasso_path_fold*.png")))
    if lasso:
        outputs["lasso_paths"] = lasso
    shap_plots = sorted(glob.glob(os.path.join(
        output_dir, "shap", "shap_summary_fold*.png")))
    shap_plots += sorted(glob.glob(os.path.join(
        output_dir, "shap", "shap_bar_fold*.png")))
    if shap_plots:
        outputs["shap_plots"] = shap_plots
    return outputs
