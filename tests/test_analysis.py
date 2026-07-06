import pandas as pd
import numpy as np
import pytest

import app.analysis as analysis_module
from app.analysis import AnalysisAgent, bootstrap_auc_ci


def _make_df(n=50, n_signal=5, n_noise=5, seed=42, label_col="Label"):
    rng = np.random.RandomState(seed)
    df = pd.DataFrame({
        "patient_id": [f"P{i:03d}" for i in range(n)],
        label_col: rng.randint(0, 2, n),
    })
    for i in range(n_signal):
        df[f"original_signal_{i}"] = rng.randn(n) + df[label_col] * 2.0
    for i in range(n_noise):
        df[f"original_noise_{i}"] = rng.randn(n)
    return df


def test_analysis_agent_basic():
    df = _make_df(n=50, n_signal=5, n_noise=5, seed=42)
    agent = AnalysisAgent(covariates=[])
    result = agent.run(df, label_col="Label")
    assert result["success"] is True
    assert "auc" in result["metrics"]
    assert "odds_ratios" in result["model_results"]


def test_empty_dataframe_returns_error():
    agent = AnalysisAgent()
    result = agent.run(pd.DataFrame(), label_col="Label")
    assert result["success"] is False
    assert "merged_df 为空" in result["message"]


def test_missing_label_column_returns_error():
    df = _make_df()
    agent = AnalysisAgent()
    result = agent.run(df, label_col="NonExistent")
    assert result["success"] is False
    assert "不存在" in result["message"]


def test_non_binary_labels_returns_error():
    df = _make_df()
    df["Label"] = np.random.choice([1, 2, 3], size=len(df))
    agent = AnalysisAgent()
    result = agent.run(df, label_col="Label")
    assert result["success"] is False
    assert "值域非 0/1" in result["message"]


def test_no_feature_columns_returns_error():
    df = pd.DataFrame({"patient_id": ["P001", "P002"], "Label": [0, 1]})
    agent = AnalysisAgent()
    result = agent.run(df, label_col="Label")
    assert result["success"] is False
    assert "未找到可用特征列" in result["message"]


def test_clinical_covariates_retained():
    df = _make_df(n=50, n_signal=3, n_noise=2, seed=42)
    df["Age"] = np.random.randn(len(df))
    agent = AnalysisAgent(covariates=["Age"])
    result = agent.run(df, label_col="Label")
    assert result["success"] is True
    assert "Age" in result["selected_features"]
    assert "Age" in result["model_results"]["coefficients"]


def test_empty_intersection_returns_error(monkeypatch):
    """When LASSO selects a different feature in every fold, the intersection is empty."""
    rng = np.random.RandomState(7)
    n_splits = 5
    n = 50
    df = pd.DataFrame({
        "patient_id": [f"P{i:03d}" for i in range(n)],
        "Label": rng.randint(0, 2, n),
    })
    # Mostly-noise radiomic features.
    for j in range(20):
        df[f"original_noise_{j}"] = rng.randn(n)

    class _MockLassoCV:
        _call_count = 0

        def __init__(self, *args, **kwargs):
            pass

        def fit(self, X, y):
            n_features = X.shape[1]
            coef = np.zeros(n_features)
            # Select a different feature on every fold-level call.
            idx = _MockLassoCV._call_count % n_features
            coef[idx] = 1.0
            self.coef_ = coef
            _MockLassoCV._call_count += 1
            return self

    monkeypatch.setattr(analysis_module, "LassoCV", _MockLassoCV)

    agent = AnalysisAgent(n_splits=n_splits, random_state=42)
    result = agent.run(df, label_col="Label")
    assert result["success"] is False
    assert "交集为空" in result["message"]


def test_bootstrap_auc_ci_empty_scores():
    y_true = np.array([0, 0, 0])
    y_prob = np.array([0.1, 0.2, 0.3])
    ci = bootstrap_auc_ci(y_true, y_prob, n_bootstrap=10, random_state=1)
    assert np.isnan(ci[0]) and np.isnan(ci[1])
