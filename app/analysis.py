import logging
import os
from typing import List, Dict, Any, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, LassoCV
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold
from sklearn import metrics
from scipy import stats

from app.metrics import calculate_metrics


def bootstrap_auc_ci(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    random_state: int = 42,
) -> List[float]:
    """Compute a percentile bootstrap confidence interval for AUC.

    Resamples `y_true`/`y_prob` with replacement and recalculates the ROC AUC
    for each resample. Resamples that contain only one class are skipped.

    Args:
        y_true: Ground-truth binary labels (0 or 1).
        y_prob: Predicted probabilities for the positive class.
        n_bootstrap: Number of bootstrap iterations.
        confidence: Confidence level for the interval.
        random_state: Seed for reproducible resampling.

    Returns:
        A two-element list ``[lower_bound, upper_bound]``. If no valid
        bootstrap scores are obtained, both bounds are ``float("nan")``.
    """
    rng = np.random.RandomState(random_state)
    scores = []
    for _ in range(n_bootstrap):
        idx = rng.randint(0, len(y_true), len(y_true))
        if len(np.unique(y_true[idx])) < 2:
            continue
        scores.append(metrics.roc_auc_score(y_true[idx], y_prob[idx]))
    if not scores:
        return [float("nan"), float("nan")]
    alpha = 1 - confidence
    return [float(np.percentile(scores, alpha / 2 * 100)), float(np.percentile(scores, (1 - alpha / 2) * 100))]


logger = logging.getLogger(__name__)


class AnalysisAgent:
    """Binary classification analysis agent based on LASSO + logistic regression.

    The agent performs the following steps on a merged radiomic/clinical
    DataFrame:

    1. Validates the input, label column, and label values.
    2. Identifies radiomic feature columns and requested clinical covariates.
    3. Runs a stratified k-fold cross-validation loop:
       - Standardizes features per fold.
       - Selects radiomic features with ``LassoCV``.
       - Retains all requested clinical covariates.
       - Trains a logistic regression model on the selected features.
       - Accumulates out-of-fold predicted probabilities.
    4. Intersects the per-fold selected radiomic features to obtain a stable
       feature set. If the intersection is empty and no clinical covariates
       were requested, the run fails early.
    5. Fits a final logistic regression model on the stable features and
       reports coefficients, odds ratios, confidence intervals, and p-values.
    6. Computes classification metrics and a bootstrap AUC confidence interval.
    """

    def __init__(self, covariates: Optional[List[str]] = None, n_splits: int = 5,
                 random_state: int = 42, output_dir: Optional[str] = None):
        """Initialize the analysis agent.

        Args:
            covariates: List of clinical column names to retain as covariates.
            n_splits: Number of cross-validation folds.
            random_state: Random seed for reproducibility.
            output_dir: Optional directory for future outputs.
        """
        self.covariates = covariates or []
        self.n_splits = n_splits
        self.random_state = random_state
        self.output_dir = output_dir

    def run(self, merged_df: pd.DataFrame, label_col: str,
            output_dir: Optional[str] = None) -> Dict[str, Any]:
        """Run the binary classification analysis pipeline.

        Args:
            merged_df: Input DataFrame containing labels, radiomic features, and
                optionally clinical covariates.
            label_col: Name of the binary label column (values must be 0/1).
            output_dir: Optional output directory override.

        Returns:
            A dictionary with ``success``/``message`` and, on success, the
            selected features, model coefficients, odds ratios, and metrics.
            The confusion matrix is returned as ``[[tn, fp], [fn, tp]]``.
        """
        if merged_df is None or merged_df.empty:
            return {"success": False, "message": "merged_df 为空"}
        if label_col not in merged_df.columns:
            return {"success": False, "message": f"Label 列 '{label_col}' 不存在"}

        y = merged_df[label_col].values.astype(int)
        if not set(np.unique(y)).issubset({0, 1}):
            return {"success": False, "message": f"Label 值域非 0/1: {np.unique(y)}"}

        radiomic_cols = [c for c in merged_df.columns
                         if any(c.startswith(p) for p in ["original_", "wavelet-", "log-sigma_"])]
        clinical_covs = [c for c in self.covariates if c in merged_df.columns]
        feature_cols = radiomic_cols + clinical_covs

        if not feature_cols:
            return {"success": False, "message": "未找到可用特征列"}

        X_raw = merged_df[feature_cols].copy()
        # 缺失值填充
        for col in X_raw.columns:
            if pd.api.types.is_numeric_dtype(X_raw[col]):
                X_raw[col] = X_raw[col].fillna(X_raw[col].median())
            else:
                X_raw[col] = X_raw[col].fillna(X_raw[col].mode()[0] if not X_raw[col].mode().empty else "Unknown")

        X = X_raw.values.astype(float)

        # 5 折 CV
        skf = StratifiedKFold(n_splits=self.n_splits, shuffle=True, random_state=self.random_state)
        val_probs = np.zeros(len(y))
        fold_selected_features = []
        plot_paths = []

        for fold_idx, (train_idx, val_idx) in enumerate(skf.split(X, y)):
            X_train, X_val = X[train_idx], X[val_idx]
            y_train = y[train_idx]

            scaler = StandardScaler()
            X_train_s = scaler.fit_transform(X_train)
            X_val_s = scaler.transform(X_val)

            # LASSO 只在影像组学特征上
            if len(radiomic_cols) > 0:
                X_train_radio = X_train_s[:, :len(radiomic_cols)]
                lasso = LassoCV(cv=3, random_state=self.random_state, max_iter=10000).fit(X_train_radio, y_train)
                radio_mask = np.abs(lasso.coef_) > 1e-6
                save_dir = output_dir or self.output_dir
                if save_dir and len(radiomic_cols) > 0:
                    os.makedirs(save_dir, exist_ok=True)
                    alphas_path, coefs_path, _ = LassoCV.path(
                        X_train_radio, y_train, random_state=self.random_state, max_iter=10000
                    )
                    plt.figure(figsize=(6, 4))
                    plt.semilogx(alphas_path, coefs_path.T)
                    plt.axvline(lasso.alpha_, color="black", linestyle="--")
                    plt.xlabel("Alpha")
                    plt.ylabel("Coefficient")
                    plt.title(f"LASSO Path - Fold {fold_idx + 1}")
                    plot_path = os.path.join(save_dir, f"lasso_path_fold{fold_idx + 1}.png")
                    plt.savefig(plot_path, dpi=150, bbox_inches="tight")
                    plt.close()
                    plot_paths.append(plot_path)
            else:
                radio_mask = np.zeros(len(radiomic_cols), dtype=bool)

            # 保留临床协变量
            clinical_mask = np.ones(len(clinical_covs), dtype=bool) if clinical_covs else np.zeros(0, dtype=bool)
            mask = np.concatenate([radio_mask, clinical_mask])

            if not np.any(mask):
                return {"success": False, "message": "LASSO 未选中任何特征且未指定协变量"}

            fold_selected_features.append(set(np.array(feature_cols)[mask]))

            X_train_sel = X_train_s[:, mask]
            X_val_sel = X_val_s[:, mask]

            lr = LogisticRegression(max_iter=10000, random_state=self.random_state)
            lr.fit(X_train_sel, y_train)
            val_probs[val_idx] = lr.predict_proba(X_val_sel)[:, 1]

        # 用稳定出现的特征作为最终选中特征
        selected_features = list(set.intersection(*fold_selected_features) if fold_selected_features else set())
        if not selected_features and clinical_covs:
            selected_features = clinical_covs.copy()

        if not selected_features:
            return {"success": False, "message": "各折 LASSO 选中的特征交集为空，且未指定协变量"}

        # 最终全量模型
        scaler_final = StandardScaler()
        X_s = scaler_final.fit_transform(X)
        final_mask = np.array([c in selected_features for c in feature_cols])
        X_final = X_s[:, final_mask]

        final_lr = LogisticRegression(max_iter=10000, random_state=self.random_state)
        final_lr.fit(X_final, y)

        # 计算 OR / CI / p
        coefs = final_lr.coef_[0]
        intercept = final_lr.intercept_[0]
        final_feature_names = [c for c in feature_cols if c in selected_features]

        try:
            X_const = np.column_stack([np.ones(X_final.shape[0]), X_final])
            pred_probs = final_lr.predict_proba(X_final)[:, 1]
            W = np.diag(pred_probs * (1 - pred_probs))
            cov_matrix = np.linalg.inv(X_const.T @ W @ X_const)
            se = np.sqrt(np.diag(cov_matrix))[1:]
        except Exception:
            se = np.zeros(len(coefs))

        model_results = {
            "intercept": float(intercept),
            "coefficients": {},
            "odds_ratios": {},
            "ci_lower": {},
            "ci_upper": {},
            "p_values": {},
        }
        for i, feat in enumerate(final_feature_names):
            coef = coefs[i]
            or_val = np.exp(coef)
            model_results["coefficients"][feat] = float(coef)
            model_results["odds_ratios"][feat] = float(or_val)
            if i < len(se) and se[i] > 0:
                z = coef / se[i]
                p = 2 * (1 - stats.norm.cdf(abs(z)))
                ci_lo = np.exp(coef - 1.96 * se[i])
                ci_hi = np.exp(coef + 1.96 * se[i])
            else:
                p = 1.0
                ci_lo = ci_hi = np.nan
            model_results["p_values"][feat] = float(p)
            model_results["ci_lower"][feat] = float(ci_lo) if not np.isnan(ci_lo) else None
            model_results["ci_upper"][feat] = float(ci_hi) if not np.isnan(ci_hi) else None

        metrics_result = calculate_metrics(y, val_probs)

        return {
            "success": True,
            "message": "分析完成",
            "task_type": "binary_classification",
            "selected_features": selected_features,
            "model_results": model_results,
            "metrics": {
                "auc": float(metrics_result.auc),
                "auc_ci": bootstrap_auc_ci(y, val_probs),
                "accuracy": float(metrics_result.accuracy),
                "sensitivity": float(metrics_result.sensitivity),
                "specificity": float(metrics_result.specificity),
                "threshold": float(metrics_result.best_threshold),
                # Confusion matrix layout: [[tn, fp], [fn, tp]]
                "confusion_matrix": [[int(metrics_result.tn), int(metrics_result.fp)],
                                      [int(metrics_result.fn), int(metrics_result.tp)]],
            },
            "n_samples": len(y),
            "plot_paths": plot_paths,
        }
