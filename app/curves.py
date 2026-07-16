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
    try:
        ax.plot(fpr, tpr, lw=2,
                label=f"AUC = {auc:.3f} (95% CI {auc_ci[0]:.3f}\u2013{auc_ci[1]:.3f})")
        ax.plot([0, 1], [0, 1], "k--", lw=1)
        ax.set_xlabel("1 - Specificity")
        ax.set_ylabel("Sensitivity")
        ax.set_title("ROC Curve (out-of-fold)")
        ax.legend(loc="lower right")
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    finally:
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
    try:
        ax.plot([0, 1], [0, 1], "k--", lw=1, label="Perfectly calibrated")
        ax.plot(mean_pred, frac_pos, "o-", lw=2, label="Model")
        ax.set_xlabel("Mean predicted probability")
        ax.set_ylabel("Observed fraction of positives")
        ax.set_title("Calibration Curve (out-of-fold)")
        ax.legend(loc="upper left")
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    finally:
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
    try:
        ax.plot(thresholds, model_nb, lw=2, label="Model")
        ax.plot(thresholds, treat_all_nb, color="gray", lw=1, label="Treat all")
        ax.axhline(0.0, color="k", lw=1, label="Treat none")
        ax.set_ylim(bottom=min(-0.05, min(model_nb) - 0.05))
        ax.set_xlabel("Threshold probability")
        ax.set_ylabel("Net benefit")
        ax.set_title("Decision Curve Analysis (out-of-fold)")
        ax.legend(loc="upper right")
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
    finally:
        plt.close(fig)
    return out_path
