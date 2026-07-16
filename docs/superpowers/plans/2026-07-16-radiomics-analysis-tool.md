# 影像组学分析 Agent 工具实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为对话式 agent 新增 `run_radiomics_analysis` 工具：自动识别特征 CSV 与临床表的对应关系（有歧义时在对话中澄清），确认后执行 LASSO+逻辑回归五折交叉验证分析，导出 ROC/校准/DCA 曲线、每病例预测概率、特征系数表，并生成 Word + Markdown 报告。

**Architecture:** 新增两个独立模块——`app/curves.py`（纯绘图）与 `app/radiomics_analysis.py`（输入识别 `inspect_analysis_inputs` + 编排 `run_radiomics_cv_analysis`），复用现有 `AnalysisAgent`（方法学不变，仅返回新增 `oof_probabilities` 字段）、`app/utils.py` 加载合并函数、`ReportAgent`。agent 接入按现有 pending 确认模式改 `tools.py`/`state.py`/`nodes.py`/`api/agent.py`，前端新增 `AnalysisPanel.vue` 确认面板。

**Tech Stack:** Python 3、scikit-learn、pandas、numpy、matplotlib(Agg)、python-docx、pytest；Vue 3 + TypeScript + Pinia + Element Plus + vitest。

**参考设计:** `docs/superpowers/specs/2026-07-16-radiomics-analysis-tool-design.md`

**运行命令约定:** 后端测试在项目根目录执行（Git Bash）：`.venv/Scripts/python -m pytest <args>`（若虚拟环境已激活，`python -m pytest` 亦可）。前端测试在 `frontend/` 下执行 `npm run test:unit -- <file>`、`npm run type-check`。

---

### Task 1: AnalysisAgent 返回 oof_probabilities

`AnalysisAgent.run`（`app/analysis.py`）已经累积了每例 out-of-fold 概率（局部变量 `val_probs`），但未返回。本任务把它加进返回字典——纯新增字段，不改任何逻辑。

**Files:**
- Modify: `app/analysis.py`（`run` 的返回字典，约 319-338 行；docstring）
- Test: `tests/test_analysis.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_analysis.py` 末尾追加（文件已有 `_make_df` 辅助函数和 `AnalysisAgent` import）：

```python
def test_oof_probabilities_returned():
    """run 返回按 merged_df 行序排列的每例 out-of-fold 预测概率。"""
    df = _make_df(n=50, n_signal=5, n_noise=5, seed=42)
    agent = AnalysisAgent(covariates=[])
    result = agent.run(df, label_col="Label")
    assert result["success"] is True
    probs = result["oof_probabilities"]
    assert len(probs) == len(df)
    assert all(isinstance(p, float) for p in probs)
    assert all(0.0 <= p <= 1.0 for p in probs)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_analysis.py::test_oof_probabilities_returned -v`
Expected: FAIL，`KeyError: 'oof_probabilities'`

- [ ] **Step 3: 实现**

`app/analysis.py` 的 `run` 方法返回字典中，`"n_samples": len(y),` 一行之后插入：

```python
            "oof_probabilities": [float(p) for p in val_probs],
```

同时把 `run` 的 docstring 中 `Returns:` 段落末尾一行

```
            The confusion matrix is returned as ``[[tn, fp], [fn, tp]]``.
```

改为：

```
            The confusion matrix is returned as ``[[tn, fp], [fn, tp]]``.
            ``oof_probabilities`` holds the out-of-fold predicted probability
            for every row of ``merged_df`` (in row order).
```

- [ ] **Step 4: 运行测试确认通过 + 全量回归本文件**

Run: `.venv/Scripts/python -m pytest tests/test_analysis.py -v`
Expected: 全部 PASS（含既有用例）

- [ ] **Step 5: Commit**

```bash
git add app/analysis.py tests/test_analysis.py
git commit -m "feat: AnalysisAgent 返回每例 out-of-fold 预测概率"
```

---

### Task 2: 新增 app/curves.py（ROC / 校准 / DCA 曲线）

**Files:**
- Create: `app/curves.py`
- Test: `tests/test_curves.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_curves.py`：

```python
import os

import numpy as np

from app.curves import (
    _calibration_points,
    _dca_arrays,
    plot_calibration_curve,
    plot_dca,
    plot_roc_curve,
)


def _data(n=60, seed=0):
    rng = np.random.RandomState(seed)
    y = rng.randint(0, 2, n).astype(float)
    p = np.clip(0.2 + 0.6 * y + 0.1 * rng.randn(n), 0.0, 1.0)
    return y, p


def test_plot_roc_curve_saves_png(tmp_path):
    y, p = _data()
    out = str(tmp_path / "roc_curve.png")
    result = plot_roc_curve(y, p, auc=0.85, auc_ci=[0.70, 0.95], out_path=out)
    assert result == out
    assert os.path.exists(out) and os.path.getsize(out) > 0


def test_plot_calibration_curve_saves_png(tmp_path):
    y, p = _data()
    out = str(tmp_path / "calibration_curve.png")
    result = plot_calibration_curve(y, p, out)
    assert result == out
    assert os.path.exists(out) and os.path.getsize(out) > 0


def test_plot_dca_saves_png(tmp_path):
    y, p = _data()
    out = str(tmp_path / "dca_curve.png")
    result = plot_dca(y, p, out)
    assert result == out
    assert os.path.exists(out) and os.path.getsize(out) > 0


def test_calibration_points_ranges():
    y, p = _data()
    mean_pred, frac_pos = _calibration_points(y, p, n_bins=10)
    assert 0 < len(mean_pred) <= 10
    assert len(mean_pred) == len(frac_pos)
    assert all(0.0 <= v <= 1.0 for v in mean_pred)
    assert all(0.0 <= v <= 1.0 for v in frac_pos)


def test_dca_net_benefit_math():
    """pt 很小时 treat-all 净获益 ≈ 流行率；treat-none 恒为 0（由绘图代码保证）。"""
    y, p = _data()
    thresholds = np.array([0.01, 0.5])
    model_nb, treat_all_nb = _dca_arrays(y, p, thresholds)
    prevalence = float(np.mean(y))
    assert abs(treat_all_nb[0] - (prevalence - (1 - prevalence) * 0.01 / 0.99)) < 1e-9
    assert len(model_nb) == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_curves.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.curves'`

- [ ] **Step 3: 实现**

创建 `app/curves.py`：

```python
"""Classification evaluation curves: ROC, calibration, and decision curve analysis.

All functions save a PNG and return its path. Pure matplotlib/numpy/sklearn,
no new dependencies.
"""

from typing import List, Sequence, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import numpy as np
from sklearn import metrics as sk_metrics


def plot_roc_curve(y_true, y_prob, auc: float, auc_ci: Sequence[float], out_path: str) -> str:
    """Plot the ROC curve for out-of-fold probabilities with AUC and 95% CI."""
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    fpr, tpr, _ = sk_metrics.roc_curve(y_true, y_prob)
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot(fpr, tpr, lw=2,
            label=f"AUC = {auc:.3f} (95% CI {auc_ci[0]:.3f}\u2013{auc_ci[1]:.3f})")
    ax.plot([0, 1], [0, 1], "k--", lw=1)
    ax.set_xlabel("1 - Specificity")
    ax.set_ylabel("Sensitivity")
    ax.set_title("ROC Curve (out-of-fold)")
    ax.legend(loc="lower right")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _calibration_points(y_true, y_prob, n_bins: int = 10) -> Tuple[List[float], List[float]]:
    """Equal-frequency binning: mean predicted probability vs observed fraction."""
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    order = np.argsort(y_prob)
    mean_pred: List[float] = []
    frac_pos: List[float] = []
    for idx in np.array_split(order, n_bins):
        if len(idx) == 0:
            continue
        mean_pred.append(float(np.mean(y_prob[idx])))
        frac_pos.append(float(np.mean(y_true[idx])))
    return mean_pred, frac_pos


def plot_calibration_curve(y_true, y_prob, out_path: str, n_bins: int = 10) -> str:
    """Plot a calibration curve (binned observed vs predicted) with diagonal."""
    mean_pred, frac_pos = _calibration_points(y_true, y_prob, n_bins=n_bins)
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="Perfectly calibrated")
    ax.plot(mean_pred, frac_pos, "o-", lw=2, label="Model")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed fraction of positives")
    ax.set_title("Calibration Curve (out-of-fold)")
    ax.legend(loc="upper left")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def _dca_arrays(y_true, y_prob, thresholds) -> Tuple[List[float], List[float]]:
    """Net benefit of the model and of treat-all at each threshold.

    Net benefit = TP/n - FP/n * pt/(1-pt). Treat-none is identically 0 and is
    drawn by the caller as a horizontal line.
    """
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    n = len(y_true)
    prevalence = float(np.mean(y_true))
    model_nb: List[float] = []
    treat_all_nb: List[float] = []
    for pt in thresholds:
        pred = y_prob >= pt
        tp = float(np.sum((pred == 1) & (y_true == 1)))
        fp = float(np.sum((pred == 1) & (y_true == 0)))
        model_nb.append(tp / n - fp / n * (pt / (1 - pt)))
        treat_all_nb.append(prevalence - (1 - prevalence) * (pt / (1 - pt)))
    return model_nb, treat_all_nb


def plot_dca(y_true, y_prob, out_path: str) -> str:
    """Plot the decision curve: model net benefit vs treat-all / treat-none."""
    thresholds = np.linspace(0.01, 0.99, 99)
    model_nb, treat_all_nb = _dca_arrays(y_true, y_prob, thresholds)
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot(thresholds, model_nb, lw=2, label="Model")
    ax.plot(thresholds, treat_all_nb, color="gray", lw=1, label="Treat all")
    ax.axhline(0.0, color="k", lw=1, label="Treat none")
    ax.set_ylim(bottom=min(-0.05, min(model_nb) - 0.05))
    ax.set_xlabel("Threshold probability")
    ax.set_ylabel("Net benefit")
    ax.set_title("Decision Curve Analysis (out-of-fold)")
    ax.legend(loc="upper right")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_curves.py -v`
Expected: 5 个用例全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/curves.py tests/test_curves.py
git commit -m "feat: 新增 ROC/校准/DCA 曲线绘制模块"
```

---

### Task 3: 新增 app/radiomics_analysis.py — inspect_analysis_inputs（输入识别）

识别特征文件、临床文件、ID 列、标签列；有歧义返回 `need_clarification`，齐全返回 `ready`。本任务只写识别部分，编排函数在 Task 4。

**Files:**
- Create: `app/radiomics_analysis.py`
- Test: `tests/test_radiomics_analysis.py`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_radiomics_analysis.py`：

```python
import numpy as np
import pandas as pd
import pytest

from app.radiomics_analysis import inspect_analysis_inputs


def _write_feature_csv(path, ids, n=8, seed=42):
    rng = np.random.RandomState(seed)
    df = pd.DataFrame({"patient_id": ids})
    label = np.array([i % 2 for i in range(len(ids))])
    for j in range(6):
        df[f"original_sig_{j}"] = rng.randn(len(ids)) + label * 1.5
    for j in range(2):
        df[f"wavelet-HHH_noise_{j}"] = rng.randn(len(ids))
    df.to_csv(path, index=False)
    return label


def _write_clinical_csv(path, ids, label, label_name="Label", extra_binary=False):
    rng = np.random.RandomState(1)
    df = pd.DataFrame({"patient_id": ids, label_name: label,
                       "age": rng.randint(30, 80, len(ids))})
    if extra_binary:
        df["group2"] = rng.randint(0, 2, len(ids))
    df.to_csv(path, index=False)


IDS = [f"P{i:03d}" for i in range(60)]


def test_inspect_ready_with_explicit_paths(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))
    assert result["status"] == "ready"
    resolved = result["resolved"]
    assert resolved["id_col"] == "patient_id"
    assert resolved["label_col"] == "Label"
    assert resolved["n_matched"] == 60
    assert resolved["n_features"] == 8
    assert resolved["output_dir"] == str(tmp_path / "radiomics_analysis")


def test_inspect_auto_discovers_clinical(tmp_path):
    feat_dir = tmp_path / "radiomics_features"
    feat_dir.mkdir()
    label = _write_feature_csv(feat_dir / "radiomics_features.csv", IDS)
    _write_clinical_csv(tmp_path / "clinical.csv", IDS, label)
    result = inspect_analysis_inputs(str(tmp_path))
    assert result["status"] == "ready"
    assert result["resolved"]["clinical"] == str(tmp_path / "clinical.csv")


def test_inspect_missing_feature_csv_returns_error(tmp_path):
    result = inspect_analysis_inputs(str(tmp_path))
    assert result["status"] == "error"
    assert "特征" in result["message"]


def test_inspect_multiple_clinical_candidates_asks(tmp_path):
    feat = tmp_path / "features.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(tmp_path / "a.csv", IDS, label)
    _write_clinical_csv(tmp_path / "b.csv", IDS, label)
    result = inspect_analysis_inputs(str(tmp_path), feature_csv=str(feat))
    assert result["status"] == "need_clarification"
    assert result["questions"][0]["field"] == "clinical"
    assert len(result["questions"][0]["candidates"]) == 2


def test_inspect_multiple_binary_columns_asks_label(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label, extra_binary=True)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))
    assert result["status"] == "need_clarification"
    fields = [q["field"] for q in result["questions"]]
    assert "label_col" in fields


def test_inspect_no_id_match_asks_id(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, [f"X{i:03d}" for i in range(60)], label)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin))
    assert result["status"] == "need_clarification"
    fields = [q["field"] for q in result["questions"]]
    assert "id_col" in fields


def test_inspect_invalid_explicit_label_returns_error(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label)
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin),
        label_col="age")
    assert result["status"] == "error"
    assert "0/1" in result["message"]


def test_inspect_explicit_label_and_covariates(tmp_path):
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, IDS)
    _write_clinical_csv(clin, IDS, label, label_name="group")
    result = inspect_analysis_inputs(
        str(tmp_path), feature_csv=str(feat), clinical=str(clin),
        label_col="group", covariates=["age", "not_a_column"])
    assert result["status"] == "ready"
    assert result["resolved"]["label_col"] == "group"
    assert result["resolved"]["covariates"] == ["age"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_radiomics_analysis.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.radiomics_analysis'`

- [ ] **Step 3: 实现**

创建 `app/radiomics_analysis.py`：

```python
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


def _binary_columns(df: pd.DataFrame, exclude: Optional[str] = None) -> List[str]:
    """Columns whose non-null values are exactly {0, 1}."""
    cols = []
    for col in df.columns:
        if col == exclude:
            continue
        try:
            unique = set(df[col].dropna().astype(int).unique())
        except (ValueError, TypeError):
            continue
        if unique == {0, 1}:
            cols.append(col)
    return cols


def _id_match_counts(df: pd.DataFrame, feature_ids: set) -> Dict[str, int]:
    """Per-column count of values present in ``feature_ids`` (string compare)."""
    counts = {}
    for col in df.columns:
        values = set(df[col].dropna().astype(str))
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
    exclude_abs = os.path.abspath(exclude_path) if exclude_path else ""
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
            if os.path.abspath(path) == exclude_abs:
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
                "message": f"{e}。请先提取特征或通过 feature_csv 指定路径"}
    feature_ids = set(feature_df["patient_id"].astype(str))
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
    detected["clinical"] = clinical

    questions: List[Dict[str, Any]] = []

    # 3. ID 列（与特征 patient_id 交集最大者）
    counts = _id_match_counts(clinical_df, feature_ids)
    if id_col:
        if id_col not in clinical_df.columns:
            return {"status": "error",
                    "message": f"指定的 ID 列 '{id_col}' 不存在",
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
        try:
            values = set(clinical_df[label_col].dropna().astype(int).unique())
        except (ValueError, TypeError):
            values = set()
        if not values or not values.issubset({0, 1}):
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
        "n_matched": detected["n_matched"],
        "available_clinical_columns": available,
    }}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_radiomics_analysis.py -v`
Expected: 8 个用例全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/radiomics_analysis.py tests/test_radiomics_analysis.py
git commit -m "feat: 分析输入智能识别（特征/临床/ID/标签列 + 澄清问题）"
```

---

### Task 4: run_radiomics_cv_analysis 编排 + Markdown 报告

在 `app/radiomics_analysis.py` 中追加编排函数与 Markdown 渲染。

**Files:**
- Modify: `app/radiomics_analysis.py`
- Test: `tests/test_radiomics_analysis.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_radiomics_analysis.py` 的 import 处把 `run_radiomics_cv_analysis` 加入：

```python
from app.radiomics_analysis import inspect_analysis_inputs, run_radiomics_cv_analysis
```

并在文件末尾追加：

```python
def _make_run_inputs(tmp_path, n=60, seed=42):
    ids = [f"P{i:03d}" for i in range(n)]
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    label = _write_feature_csv(feat, ids, seed=seed)
    _write_clinical_csv(clin, ids, label)
    return str(feat), str(clin)


def test_run_analysis_end_to_end(tmp_path):
    feat, clin = _make_run_inputs(tmp_path)
    out_dir = str(tmp_path / "analysis_out")
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin, output_dir=out_dir,
        id_col="patient_id", label_col="Label")
    assert result["success"] is True
    outputs = result["outputs"]
    for key in ("case_predictions", "selected_features", "roc_curve",
                "calibration_curve", "dca_curve", "report_docx", "report_md"):
        assert outputs[key], f"missing output {key}"
        import os
        assert os.path.exists(outputs[key]), f"{key} not on disk"

    case_df = pd.read_csv(outputs["case_predictions"])
    assert list(case_df.columns) == ["patient_id", "y_true", "oof_prob", "y_pred"]
    assert len(case_df) == 60

    feat_df = pd.read_csv(outputs["selected_features"])
    assert list(feat_df.columns) == ["feature", "coefficient", "odds_ratio",
                                     "ci_lower", "ci_upper", "p_value"]
    assert len(feat_df) >= 1

    md = open(outputs["report_md"], encoding="utf-8").read()
    assert "AUC" in md
    assert result["n_matched"] == 60


def test_run_analysis_fails_when_class_too_small(tmp_path):
    ids = [f"P{i:03d}" for i in range(30)]
    feat = tmp_path / "features.csv"
    clin = tmp_path / "clinical.csv"
    _write_feature_csv(feat, ids)
    # 阳性仅 2 例，小于 5 折
    df = pd.DataFrame({"patient_id": ids,
                       "Label": [1, 1] + [0] * 28})
    df.to_csv(clin, index=False)
    result = run_radiomics_cv_analysis(
        feature_csv=str(feat), clinical=str(clin),
        output_dir=str(tmp_path / "out"),
        id_col="patient_id", label_col="Label")
    assert result["success"] is False
    assert "折数" in result["message"]


def test_run_analysis_cancelled_before_start(tmp_path):
    feat, clin = _make_run_inputs(tmp_path)
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin,
        output_dir=str(tmp_path / "out"),
        id_col="patient_id", label_col="Label",
        should_cancel=lambda: True)
    assert result["success"] is False
    assert result["cancelled"] is True


def test_run_analysis_fails_without_label_col(tmp_path):
    feat, clin = _make_run_inputs(tmp_path)
    result = run_radiomics_cv_analysis(
        feature_csv=feat, clinical=clin,
        output_dir=str(tmp_path / "out"),
        id_col="patient_id")
    assert result["success"] is False
    assert "label_col" in result["message"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_radiomics_analysis.py -v`
Expected: 新 4 个用例 FAIL（`ImportError: cannot import name 'run_radiomics_cv_analysis'`）

- [ ] **Step 3: 实现**

在 `app/radiomics_analysis.py` 顶部 import 区追加：

```python
from app.curves import plot_calibration_curve, plot_dca, plot_roc_curve
```

并在文件末尾追加：

```python
def _render_markdown_report(analysis_result: Dict[str, Any],
                            outputs: Dict[str, Any],
                            n_matched: int,
                            covariates: List[str],
                            output_dir: str) -> str:
    """Render a Markdown report next to the Word one; returns its path."""
    m = analysis_result["metrics"]
    lines = [
        "# 影像组学分析报告",
        "",
        "## 1. 方法",
        "",
        f"共纳入 {analysis_result['n_samples']} 例患者"
        f"（特征与临床表匹配 {n_matched} 例）。"
        "采用分层五折交叉验证：每折内对特征标准化后用 LassoCV 选择影像组学特征，"
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
        f"| 最佳阈值 | {m['threshold']:.3f} |",
        "",
        f"混淆矩阵（[[TN, FP], [FN, TP]]）：`{m['confusion_matrix']}`",
        "",
        "## 3. 稳定特征与回归系数",
        "",
        "| 特征 | 系数 | OR | 95%CI | p |",
        "|---|---|---|---|---|",
    ]
    mr = analysis_result["model_results"]
    for feat in analysis_result["selected_features"]:
        ci_lo = mr["ci_lower"].get(feat)
        ci_hi = mr["ci_upper"].get(feat)
        ci = f"{ci_lo:.3f}\u2013{ci_hi:.3f}" if ci_lo is not None and ci_hi is not None else "-"
        lines.append(
            f"| {feat} | {mr['coefficients'].get(feat, 0):.4f} "
            f"| {mr['odds_ratios'].get(feat, 0):.3f} | {ci} "
            f"| {mr['p_values'].get(feat, 1):.4f} |")
    lines += ["", "## 4. 图表", ""]
    for key, caption in (("roc_curve", "ROC 曲线"),
                         ("calibration_curve", "校准曲线"),
                         ("dca_curve", "决策曲线")):
        path = outputs.get(key)
        if path:
            lines.append(f"![{caption}]({os.path.basename(path)})")
            lines.append("")
    lines.append("注：预测概率为五折交叉验证的 out-of-fold 概率，"
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
    try:
        label_values = set(clinical_df[label_col].dropna().astype(int).unique())
    except (ValueError, TypeError):
        label_values = set()
    if not label_values or not label_values.issubset({0, 1}):
        return {"success": False, "message": f"标签列 '{label_col}' 必须仅包含 0/1"}

    try:
        merged_df = _merge_feature_clinical(feature_df, clinical_df, id_col="patient_id")
    except ValueError as e:
        return {"success": False, "message": str(e)}

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
        "oof_prob": oof,
        "y_pred": [int(p >= threshold) for p in oof],
    })
    case_path = os.path.join(output_dir, "case_predictions.csv")
    case_df.to_csv(case_path, index=False)
    outputs["case_predictions"] = case_path

    # 稳定特征系数表
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
            path = func(y_arr, oof_arr, os.path.join(output_dir, f"{key}.png"),
                        **kwargs)
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
        analysis_result, outputs, int(len(merged_df)), covariates, output_dir)

    return {
        "success": True,
        "message": "分析完成",
        "analysis_result": analysis_result,
        "n_matched": int(len(merged_df)),
        "outputs": outputs,
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_radiomics_analysis.py -v`
Expected: 12 个用例全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/radiomics_analysis.py tests/test_radiomics_analysis.py
git commit -m "feat: 分析编排（产物导出 + Word/Markdown 报告 + 取消支持）"
```

---

### Task 5: 注册 agent 工具 run_radiomics_analysis

**Files:**
- Modify: `app/agent/tools.py`（在 `extract_radiomics_features` 定义之后、注册区之前插入；注册区加一行）
- Test: `tests/test_agent_tools.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_agent_tools.py` 末尾追加（该文件已 import `json`、`build_tools`；pandas/numpy 需在文件顶部补 import）：

文件顶部 import 区补充：

```python
import numpy as np
import pandas as pd
```

末尾追加：

```python
def _make_analysis_project(tmp_path, n=60):
    """在项目目录内生成特征 CSV 与临床 CSV。"""
    ids = [f"P{i:03d}" for i in range(n)]
    rng = np.random.RandomState(42)
    label = np.array([i % 2 for i in range(n)])
    feat = pd.DataFrame({"patient_id": ids})
    for j in range(6):
        feat[f"original_sig_{j}"] = rng.randn(n) + label * 1.5
    feat.to_csv(tmp_path / "features.csv", index=False)
    pd.DataFrame({"patient_id": ids, "Label": label}).to_csv(
        tmp_path / "clinical.csv", index=False)


def test_run_radiomics_analysis_tool_registered(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    assert "run_radiomics_analysis" in tools


def test_run_radiomics_analysis_returns_pending_when_ready(tmp_path):
    _make_analysis_project(tmp_path)
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["run_radiomics_analysis"].invoke(
        {"feature_csv": "features.csv", "clinical": "clinical.csv"})
    data = json.loads(result)
    assert data["_pending_tool"] == "run_radiomics_analysis"
    meta = data["meta"]
    assert meta["id_col"] == "patient_id"
    assert meta["label_col"] == "Label"
    assert meta["n_matched"] == 60
    assert meta["output_dir"] == str(tmp_path / "radiomics_analysis")


def test_run_radiomics_analysis_returns_clarification_without_pending(tmp_path):
    _make_analysis_project(tmp_path)
    # 增加一个二值列使标签列产生歧义
    clin = pd.read_csv(tmp_path / "clinical.csv")
    rng = np.random.RandomState(7)
    clin["group2"] = rng.randint(0, 2, len(clin))
    clin.to_csv(tmp_path / "clinical.csv", index=False)
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["run_radiomics_analysis"].invoke(
        {"feature_csv": "features.csv", "clinical": "clinical.csv"})
    data = json.loads(result)
    assert "_pending_tool" not in data
    assert data["status"] == "need_clarification"
    fields = [q["field"] for q in data["questions"]]
    assert "label_col" in fields


def test_run_radiomics_analysis_path_escape_returns_error(tmp_path):
    tools = build_tools(str(tmp_path), MagicMock())
    result = tools["run_radiomics_analysis"].invoke(
        {"feature_csv": "../outside.csv"})
    data = json.loads(result)
    assert data["status"] == "error"
    assert "路径超出项目目录" in data["message"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_agent_tools.py -v`
Expected: 新用例 FAIL（`KeyError: 'run_radiomics_analysis'` / AssertionError）

- [ ] **Step 3: 实现**

在 `app/agent/tools.py` 的 `extract_radiomics_features` 定义之后（约 114 行后）插入：

```python
    @tool
    def run_radiomics_analysis(feature_csv: str = "", clinical: str = "",
                               id_col: str = "", label_col: str = "",
                               covariates: str = "", output_dir: str = "") -> str:
        """对已提取的影像组学特征和临床表做 LASSO + 逻辑回归五折交叉验证分析，
        生成 ROC/校准/DCA 曲线、预测概率表和 Word/Markdown 报告。
        执行前需要用户确认；若输入文件或列名识别有歧义，
        会先返回需要向用户澄清的问题（status=need_clarification），
        此时请向用户提问并用用户回答重新调用本工具。
        参数均可留空：feature_csv 缺省用 radiomics_features/radiomics_features.csv，
        clinical 缺省时自动在项目内搜索，id_col/label_col 缺省时自动识别，
        covariates 为逗号分隔的临床协变量列名。"""
        from app.radiomics_analysis import inspect_analysis_inputs
        try:
            if feature_csv:
                feature_csv = str(sandbox.resolve(feature_csv, must_exist=False))
            if clinical:
                clinical = str(sandbox.resolve(clinical, must_exist=False))
            if output_dir:
                output_dir = str(sandbox.resolve(output_dir, must_exist=False))
        except ValueError as e:
            return json.dumps({"status": "error", "message": f"路径超出项目目录: {e}"})
        cov_list = [c.strip() for c in covariates.split(",") if c.strip()]
        report = inspect_analysis_inputs(
            project_path,
            feature_csv=feature_csv,
            clinical=clinical,
            id_col=id_col,
            label_col=label_col,
            covariates=cov_list,
            output_dir=output_dir,
        )
        if report.get("status") != "ready":
            return json.dumps(report, ensure_ascii=False)
        return json.dumps(
            {"_pending_tool": "run_radiomics_analysis", "meta": report["resolved"]},
            ensure_ascii=False,
        )
```

注册区（`tools["extract_radiomics_features"] = extract_radiomics_features` 之后）加一行：

```python
    tools["run_radiomics_analysis"] = run_radiomics_analysis
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_agent_tools.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/agent/tools.py tests/test_agent_tools.py
git commit -m "feat: agent 注册 run_radiomics_analysis 工具（识别+待确认）"
```

---

### Task 6: AgentState 与初始状态新增 pending_radiomics_analysis

**Files:**
- Modify: `app/agent/state.py`
- Modify: `app/agent/__init__.py`

- [ ] **Step 1: 修改 state.py**

`app/agent/state.py` 中，`pending_radiomics_execution` 一行之后插入：

```python
    pending_radiomics_analysis: Optional[Dict[str, Any]]    # {"tool_call_id": str, ...analysis meta}
```

- [ ] **Step 2: 修改 build_initial_state**

`app/agent/__init__.py` 的 `build_initial_state` 返回字典中，`"pending_script": None,` 之后插入：

```python
        "pending_radiomics_analysis": None,
```

- [ ] **Step 3: 快速校验**

Run: `.venv/Scripts/python -m pytest tests/test_agent_graph.py tests/test_agent_nodes.py -q`
Expected: 全部 PASS（新字段为 Optional，不影响既有用例）

- [ ] **Step 4: Commit**

```bash
git add app/agent/state.py app/agent/__init__.py
git commit -m "feat: AgentState 新增 pending_radiomics_analysis 字段"
```

---

### Task 7: nodes.py 接线（确认分支 + 执行分支 + 清理）

**Files:**
- Modify: `app/agent/nodes.py`
- Test: `tests/test_radiomics_analysis_nodes.py`（新建）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_radiomics_analysis_nodes.py`：

```python
import json
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.nodes import process_tool_calls, execute_confirmed
from app.agent.state import AgentState


def _make_project(tmp_path, n=60, extra_binary=False):
    ids = [f"P{i:03d}" for i in range(n)]
    rng = np.random.RandomState(42)
    label = np.array([i % 2 for i in range(n)])
    feat = pd.DataFrame({"patient_id": ids})
    for j in range(6):
        feat[f"original_sig_{j}"] = rng.randn(n) + label * 1.5
    feat.to_csv(tmp_path / "features.csv", index=False)
    clin = pd.DataFrame({"patient_id": ids, "Label": label})
    if extra_binary:
        clin["group2"] = rng.randint(0, 2, n)
    clin.to_csv(tmp_path / "clinical.csv", index=False)


def _tool_call_state(tmp_path, args):
    return AgentState(
        messages=[AIMessage(content="", tool_calls=[{
            "id": "tc-a1",
            "name": "run_radiomics_analysis",
            "args": args,
        }])],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
    )


def _run_process(state):
    with patch("app.agent.nodes._resolve_api_key", return_value=""), \
         patch("app.agent.nodes.ChatOpenAI") as mock_llm_cls:
        mock_llm_cls.return_value = MagicMock()
        return process_tool_calls(state)


def test_process_run_radiomics_analysis_sets_interrupt(tmp_path):
    _make_project(tmp_path)
    state = _tool_call_state(tmp_path, {
        "feature_csv": "features.csv", "clinical": "clinical.csv"})
    result = _run_process(state)
    assert result["interrupt_type"] == "radiomics_analysis"
    pending = result["pending_radiomics_analysis"]
    assert pending["tool_call_id"] == "tc-a1"
    assert pending["label_col"] == "Label"
    assert pending["n_matched"] == 60
    assert result["messages"] == []  # 确认类工具不产生 ToolMessage


def test_process_run_radiomics_analysis_clarification_passthrough(tmp_path):
    _make_project(tmp_path, extra_binary=True)
    state = _tool_call_state(tmp_path, {
        "feature_csv": "features.csv", "clinical": "clinical.csv"})
    result = _run_process(state)
    assert result["interrupt_type"] is None
    assert "pending_radiomics_analysis" not in result
    assert len(result["messages"]) == 1
    content = json.loads(result["messages"][0].content)
    assert content["status"] == "need_clarification"


def test_execute_confirmed_radiomics_analysis(tmp_path):
    fake_result = {
        "success": True,
        "message": "分析完成",
        "n_matched": 60,
        "analysis_result": {
            "n_samples": 60,
            "selected_features": ["original_sig_0"],
            "metrics": {"auc": 0.9, "auc_ci": [0.8, 0.99]},
            "oof_probabilities": [0.1] * 60,  # 大数组不得进入摘要
        },
        "outputs": {"report_docx": "out/AutoRadiomics_Report.docx"},
    }
    state = AgentState(
        messages=[],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_analysis",
        confirmed=True,
        pending_radiomics_analysis={
            "tool_call_id": "tc-a1",
            "feature_csv": str(tmp_path / "features.csv"),
            "clinical": str(tmp_path / "clinical.csv"),
            "id_col": "patient_id",
            "label_col": "Label",
            "covariates": [],
            "output_dir": str(tmp_path / "radiomics_analysis"),
        },
    )
    with patch("app.agent.nodes.run_radiomics_cv_analysis",
               return_value=fake_result) as mock_run:
        result = execute_confirmed(state)

    assert mock_run.call_count == 1
    kwargs = mock_run.call_args.kwargs
    assert kwargs["label_col"] == "Label"
    content = json.loads(result["messages"][0].content)
    assert content["success"] is True
    assert content["metrics"]["auc"] == 0.9
    assert content["selected_features"] == ["original_sig_0"]
    assert "oof_probabilities" not in json.dumps(content)
    assert result["interrupt_type"] is None
    assert result["pending_radiomics_analysis"] is None


def test_execute_confirmed_radiomics_analysis_failure(tmp_path):
    state = AgentState(
        messages=[],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_analysis",
        confirmed=True,
        pending_radiomics_analysis={
            "tool_call_id": "tc-a1",
            "feature_csv": str(tmp_path / "features.csv"),
            "clinical": str(tmp_path / "clinical.csv"),
            "id_col": "patient_id",
            "label_col": "Label",
            "output_dir": str(tmp_path / "radiomics_analysis"),
        },
    )
    with patch("app.agent.nodes.run_radiomics_cv_analysis",
               side_effect=RuntimeError("boom")):
        result = execute_confirmed(state)
    content = json.loads(result["messages"][0].content)
    assert content["success"] is False
    assert "boom" in content["error"]
    assert result["interrupt_type"] is None


def test_execute_confirmed_radiomics_analysis_missing_pending(tmp_path):
    state = AgentState(
        messages=[AIMessage(content="", tool_calls=[{
            "id": "tc-a9", "name": "run_radiomics_analysis", "args": {}}])],
        project_path=str(tmp_path),
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-pro",
        api_key="",
        interrupt_type="radiomics_analysis",
        confirmed=True,
        pending_radiomics_analysis=None,
    )
    result = execute_confirmed(state)
    content = json.loads(result["messages"][0].content)
    assert "Missing pending radiomics analysis" in content["error"]
    assert result["interrupt_type"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_radiomics_analysis_nodes.py -v`
Expected: FAIL（`interrupt_type` 为 None 或 AttributeError 等）

- [ ] **Step 3: 实现 nodes.py 全部接线**

3a. `app/agent/nodes.py` 顶部 import 区（`from app.feature import FeatureAgent` 之后）加：

```python
from app.radiomics_analysis import run_radiomics_cv_analysis
```

3b. `process_tool_calls` 的 `needs_confirmation` 集合中加入工具名（约 113-119 行）：

```python
        needs_confirmation = name in {
            "list_directory",
            "find_files",
            "get_file_info",
            "plan_file_operations",
            "discover_radiomics_pairs",
            "extract_radiomics_features",
            "run_radiomics_analysis",
        } or (
```

3c. 同函数的 elif 链中，`elif name == "extract_radiomics_features":` 分支结束之后、`# 需要确认的工具不在此处生成 ToolMessage...` 注释之前，插入新分支：

```python
            elif name == "run_radiomics_analysis":
                if not isinstance(parsed, dict):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps({"error": f"Tool {name} returned invalid payload"}),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                if "_pending_tool" not in parsed:
                    # 识别阶段结果（need_clarification / error）直接回给 LLM，
                    # 由 LLM 在对话中向用户澄清后重新调用。
                    updates["messages"].append(ToolMessage(
                        content=tool_result,
                        tool_call_id=tool_call_id,
                    ))
                    continue
                if not isinstance(parsed.get("meta"), dict):
                    updates["messages"].append(ToolMessage(
                        content=json.dumps({"error": f"Tool {name} returned invalid payload"}),
                        tool_call_id=tool_call_id,
                    ))
                    continue
                interrupt_type = "radiomics_analysis"
                updates["pending_radiomics_analysis"] = {"tool_call_id": tool_call_id, **parsed["meta"]}
```

3d. `human_review` 的 `interrupt({...})` payload 中加一行：

```python
        "radiomics_analysis": state.get("pending_radiomics_analysis"),
```

其返回字典中 `"pending_radiomics_execution": state.get("pending_radiomics_execution"),` 之后加：

```python
        "pending_radiomics_analysis": state.get("pending_radiomics_analysis"),
```

3e. `_resolve_tool_call_id` 的 pending 元组中加一项：

```python
    for pending in (
        state.get("pending_plan"),
        state.get("pending_command"),
        state.get("pending_script"),
        state.get("pending_radiomics_plan"),
        state.get("pending_radiomics_execution"),
        state.get("pending_radiomics_analysis"),
    ):
```

3f. `execute_confirmed`：顶部 pending 变量区（`pending_radiomics_execution = ...` 之后）加：

```python
    pending_radiomics_analysis = state.get("pending_radiomics_analysis")
```

missing-guard elif 链中（`elif itype == "radiomics_execution":` 的 guard 之后、`else:` 之前）加：

```python
    elif itype == "radiomics_analysis":
        tool_call_id = (pending_radiomics_analysis or {}).get("tool_call_id", "") or _resolve_tool_call_id(state)
        if not pending_radiomics_analysis:
            if not tool_call_id:
                raise RuntimeError("Missing pending radiomics analysis and cannot resolve tool_call_id")
            return _clear_interrupt({
                "messages": [ToolMessage(
                    content=json.dumps({"error": "Missing pending radiomics analysis"}),
                    tool_call_id=tool_call_id,
                )]
            })
```

执行分支链中（`elif itype == "radiomics_execution":` 分支之后、`else:` 之前）加：

```python
    elif itype == "radiomics_analysis":
        ctx = agent_runtime.get(thread_id)
        cancel_event = ctx.cancel_event if ctx is not None else None
        results = _run_radiomics_analysis(
            state["pending_radiomics_analysis"],
            state["project_path"],
            cancel_event=cancel_event,
        )
```

3g. 在 `_run_radiomics_execution` 函数之后插入两个新函数：

```python
def _run_radiomics_analysis(
    pending: dict,
    project_path: str,
    cancel_event=None,
) -> dict:
    """执行已确认的影像组学分析任务。"""
    sandbox = Sandbox(project_path)
    try:
        feature_csv = _resolve_within_project(sandbox, pending.get("feature_csv"))
        clinical = _resolve_within_project(sandbox, pending.get("clinical"))
        output_dir = _resolve_within_project(
            sandbox,
            pending.get("output_dir") or str(Path(project_path) / "radiomics_analysis"),
        )
        should_cancel = (lambda: cancel_event.is_set()) if cancel_event is not None else None
        result = run_radiomics_cv_analysis(
            feature_csv=feature_csv,
            clinical=clinical,
            output_dir=output_dir,
            id_col=pending.get("id_col"),
            label_col=pending.get("label_col"),
            covariates=pending.get("covariates") or [],
            should_cancel=should_cancel,
        )
        return _json_safe_analysis_result(result)
    except PathEscapeError:
        return {"success": False, "error": "路径超出项目目录"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _json_safe_analysis_result(result: dict) -> dict:
    """分析结果转 JSON 安全摘要：指标/特征/产物路径，剔除 oof 大数组。"""
    analysis = result.get("analysis_result") or {}
    return {
        "success": result.get("success", False),
        "cancelled": result.get("cancelled", False),
        "message": result.get("message", ""),
        "n_samples": analysis.get("n_samples"),
        "n_matched": result.get("n_matched"),
        "selected_features": analysis.get("selected_features", []),
        "metrics": analysis.get("metrics", {}),
        "outputs": result.get("outputs", {}),
    }
```

3h. `_clear_interrupt` 的 `updates.update({...})` 中加一行：

```python
        "pending_radiomics_analysis": None,
```

- [ ] **Step 4: 运行测试确认通过 + 既有节点测试回归**

Run: `.venv/Scripts/python -m pytest tests/test_radiomics_analysis_nodes.py tests/test_radiomics_nodes.py tests/test_agent_nodes.py tests/test_agent_graph.py tests/test_radiomics_integration.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/agent/nodes.py tests/test_radiomics_analysis_nodes.py
git commit -m "feat: nodes 接线 radiomics_analysis 确认与执行分支"
```

---

### Task 8: API 层 _sync_payload 透出 pending_radiomics_analysis

**Files:**
- Modify: `app/api/agent.py`（`_sync_payload`，约 131-149 行）
- Test: `tests/test_api_agent.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_api_agent.py` 末尾追加：

```python
def test_sync_payload_includes_analysis_pending():
    """_sync_payload 必须返回分析待确认字段，否则前端无法渲染确认面板。"""
    from app.api.agent import _sync_payload

    values = {
        "messages": [],
        "interrupt_type": "radiomics_analysis",
        "operation_log": [],
        "pending_radiomics_analysis": {
            "tool_call_id": "tc-a1",
            "feature_csv": "features.csv",
            "clinical": "clinical.csv",
            "id_col": "patient_id",
            "label_col": "Label",
            "output_dir": "radiomics_analysis",
            "n_matched": 60,
        },
    }

    payload = _sync_payload(values, running=False)

    assert payload["interrupt_type"] == "radiomics_analysis"
    assert payload["pending_radiomics_analysis"]["n_matched"] == 60
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python -m pytest tests/test_api_agent.py::test_sync_payload_includes_analysis_pending -v`
Expected: FAIL，`KeyError: 'pending_radiomics_analysis'`

- [ ] **Step 3: 实现**

`app/api/agent.py` 的 `_sync_payload` 返回字典中，`"pending_radiomics_execution": ...` 之后加：

```python
        "pending_radiomics_analysis": values.get("pending_radiomics_analysis"),
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python -m pytest tests/test_api_agent.py -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/agent.py tests/test_api_agent.py
git commit -m "feat: _sync_payload 透出 pending_radiomics_analysis"
```

---

### Task 9: 前端类型与 store 同步

**Files:**
- Modify: `frontend/src/api/agent.ts`
- Modify: `frontend/src/stores/agent.ts`
- Test: `frontend/src/stores/__tests__/agent.spec.ts`

- [ ] **Step 1: 写失败测试**

在 `frontend/src/stores/__tests__/agent.spec.ts` 中，找到名为 `'tracks pending radiomics plan/execution from SSE state'` 的用例（约 336 行），在其后追加新用例：

```ts
  it('tracks pending radiomics analysis from SSE state', async () => {
    const store = useAgentStore()
    await store.ensureThread('project-1', 'sk-test', 'deepseek-v4-flash')
    const es = MockEventSource.instances[0]

    const analysis = {
      tool_call_id: 'tc-a1',
      feature_csv: 'features.csv',
      clinical: 'clinical.csv',
      id_col: 'patient_id',
      label_col: 'Label',
      covariates: [],
      output_dir: 'radiomics_analysis',
      n_feature_cases: 60,
      n_matched: 60,
      n_features: 8,
    }
    es.emit('agent', mockState({
      interrupt_type: 'radiomics_analysis',
      pending_radiomics_analysis: analysis,
    }))
    expect(store.pendingRadiomicsAnalysis).toEqual(analysis)
    expect(store.interrupt).toBe('radiomics_analysis')

    es.emit('agent', mockState({
      interrupt_type: null,
      pending_radiomics_analysis: null,
    }))
    expect(store.pendingRadiomicsAnalysis).toBeNull()
    expect(store.interrupt).toBeNull()
  })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd frontend && npm run test:unit -- src/stores/__tests__/agent.spec.ts`
Expected: FAIL，`expect(store.pendingRadiomicsAnalysis).toEqual(analysis)` 处（store 无此属性）

- [ ] **Step 3: 实现**

3a. `frontend/src/api/agent.ts`：在 `PendingRadiomicsExecution` 接口之后（约 81 行）插入：

```ts
export interface PendingRadiomicsAnalysis {
  tool_call_id: string
  feature_csv: string
  clinical: string
  id_col: string
  label_col: string
  covariates?: string[]
  output_dir: string
  n_feature_cases?: number
  n_matched?: number
  n_features?: number
  available_clinical_columns?: string[]
}
```

并在 `AgentState` 接口中 `pending_radiomics_execution?: PendingRadiomicsExecution | null` 之后加：

```ts
  pending_radiomics_analysis?: PendingRadiomicsAnalysis | null
```

3b. `frontend/src/stores/agent.ts`：
- 顶部类型 import 列表中 `PendingRadiomicsExecution,` 之后加 `PendingRadiomicsAnalysis,`
- `pendingRadiomicsExecution` ref 声明之后加：

```ts
  const pendingRadiomicsAnalysis = ref<PendingRadiomicsAnalysis | null>(null)
```

- `applyState` 中 `pending_radiomics_execution` 同步块之后加：

```ts
    if (state.pending_radiomics_analysis !== undefined) {
      pendingRadiomicsAnalysis.value = state.pending_radiomics_analysis
    }
```

- `resetInternalState` 中 `pendingRadiomicsExecution.value = null` 之后加：

```ts
    pendingRadiomicsAnalysis.value = null
```

- store 的 return 对象中 `pendingRadiomicsExecution,` 之后加 `pendingRadiomicsAnalysis,`

- [ ] **Step 4: 运行测试确认通过**

Run: `cd frontend && npm run test:unit -- src/stores/__tests__/agent.spec.ts`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/agent.ts frontend/src/stores/agent.ts frontend/src/stores/__tests__/agent.spec.ts
git commit -m "feat(frontend): store 同步 pending_radiomics_analysis"
```

---

### Task 10: 前端 AnalysisPanel 组件与 AgentView 接入

**Files:**
- Create: `frontend/src/components/AnalysisPanel.vue`
- Modify: `frontend/src/views/AgentView.vue`

- [ ] **Step 1: 创建 AnalysisPanel.vue**

```vue
<template>
  <div class="analysis-panel">
    <el-card shadow="never">
      <template #header>
        <div class="analysis-panel-header">
          <span class="analysis-title">待确认分析任务</span>
          <el-tag type="warning">需确认</el-tag>
        </div>
      </template>

      <div v-if="analysis" class="analysis-body">
        <div class="analysis-summary">
          <div>
            <span class="analysis-label">特征文件：</span>
            <code class="analysis-code">{{ analysis.feature_csv }}</code>
          </div>
          <div>
            <span class="analysis-label">临床表格：</span>
            <code class="analysis-code">{{ analysis.clinical }}</code>
          </div>
          <div>
            <span class="analysis-label">ID / 标签列：</span>
            {{ analysis.id_col }} / {{ analysis.label_col }}
          </div>
          <div>
            <span class="analysis-label">样本匹配：</span>
            特征 {{ analysis.n_feature_cases }} 例，匹配 {{ analysis.n_matched }} 例，
            特征数 {{ analysis.n_features }}
          </div>
          <div v-if="analysis.covariates && analysis.covariates.length > 0">
            <span class="analysis-label">协变量：</span>
            {{ analysis.covariates.join(', ') }}
          </div>
          <div>
            <span class="analysis-label">输出目录：</span>
            <code class="analysis-code">{{ analysis.output_dir }}</code>
          </div>
        </div>

        <div class="analysis-actions">
          <el-button type="primary" :icon="CircleCheck" @click="handleConfirm">
            确认分析
          </el-button>
          <el-button :icon="Close" @click="handleCancel">取消</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CircleCheck, Close } from '@element-plus/icons-vue'
import { useAgentStore } from '@/stores/agent'

const agentStore = useAgentStore()

const analysis = computed(() => agentStore.pendingRadiomicsAnalysis)

async function handleConfirm(): Promise<void> {
  try {
    await agentStore.confirm()
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}

async function handleCancel(): Promise<void> {
  try {
    await agentStore.cancel()
  } catch {
    // 错误已由 axios 拦截器统一提示
  }
}
</script>

<style scoped>
.analysis-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.analysis-title {
  font-weight: 500;
}

.analysis-body {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.analysis-summary {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
  font-size: 0.875rem;
}

.analysis-label {
  color: #606266;
  font-size: 0.875rem;
}

.analysis-code {
  font-family: 'Menlo', 'Monaco', 'Consolas', 'Courier New', monospace;
  font-size: 0.8125rem;
  padding: 0.125rem 0.375rem;
  background-color: #f5f7fa;
  border-radius: 4px;
  border: 1px solid #e4e7ed;
  word-break: break-all;
}

.analysis-actions {
  display: flex;
  gap: 0.75rem;
}
</style>
```

- [ ] **Step 2: 接入 AgentView.vue**

`frontend/src/views/AgentView.vue` 做三处修改：

2a. 模板中 `<RadiomicsPanel ... />` 块之后（约 43 行）插入：

```html
        <AnalysisPanel
          v-else-if="!agentStore.busy && agentStore.interrupt === 'radiomics_analysis' && agentStore.pendingRadiomicsAnalysis"
        />
```

2b. script 的 import 区（`import RadiomicsPanel from '@/components/RadiomicsPanel.vue'` 之后）加：

```ts
import AnalysisPanel from '@/components/AnalysisPanel.vue'
```

2c. `interruptTag` 的 switch 中 `case 'radiomics_execution':` 块之后加：

```ts
    case 'radiomics_analysis':
      return { label: '待确认分析任务', type: 'warning' as const }
```

- [ ] **Step 3: 类型检查 + lint**

Run: `cd frontend && npm run type-check && npm run lint`
Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AnalysisPanel.vue frontend/src/views/AgentView.vue
git commit -m "feat(frontend): AnalysisPanel 确认面板并接入 AgentView"
```

---

### Task 11: 全量回归

- [ ] **Step 1: 后端全量测试**

Run: `.venv/Scripts/python -m pytest tests/ -q`
Expected: 全部 PASS

- [ ] **Step 2: 前端全量测试**

Run: `cd frontend && npm run test:unit`
Expected: 全部 PASS

- [ ] **Step 3: 若前两步全绿，收尾提交（如有遗漏文件）**

```bash
git status --short
# 确认无未跟踪/未提交的本任务相关文件；若有则：
git add -A
git commit -m "chore: 分析工具收尾"
```

---

## Self-Review 记录

- **Spec 覆盖**：设计文档 §3 识别澄清 → Task 3/5；§4.1 oof 字段 → Task 1；§4.2 曲线 → Task 2；§4.3 编排+报告 → Task 4；§4.4 工具接入 → Task 5/6/7/8；§5 产物 → Task 4（产物名以代码实际为准：Word 报告为 `AutoRadiomics_Report.docx`，Markdown 为 `report.md`）；§6 前端 → Task 9/10；§7 错误处理 → Task 3/4/7（折数检查、路径沙箱、取消、单图失败降级）；§8 测试 → 各 Task 内。
- **与 spec 的两处有意微调**：① spec 中"无任何 ID 列匹配 → 报错"实现为 `need_clarification`（列出全部列供用户指定），与"有疑惑就问用户"的目标一致；② pending meta 增加了 `available_clinical_columns` 便于前端/LLM 展示可用协变量。
- **类型一致性**：`inspect_analysis_inputs` 返回的 `resolved` 键名与 `PendingRadiomicsAnalysis`（前端接口）、`_run_radiomics_analysis` 读取的 `pending.get(...)` 键名一致（feature_csv/clinical/id_col/label_col/covariates/output_dir）；`oof_probabilities` 在 Task 1 定义、Task 4 消费、Task 7 摘要从最终 JSON 剔除。
