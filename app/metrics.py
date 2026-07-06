from dataclasses import dataclass
from typing import Optional
import numpy as np
from sklearn import metrics


@dataclass
class MetricsResult:
    accuracy: float = 0.0
    sensitivity: float = 0.0
    specificity: float = 0.0
    auc: float = 0.0
    best_threshold: float = 0.5
    tp: int = 0
    tn: int = 0
    fn: int = 0
    fp: int = 0


def calculate_metrics(y_true: np.ndarray, y_prob: np.ndarray, threshold: Optional[float] = None) -> MetricsResult:
    result = MetricsResult()

    if len(np.unique(y_true)) < 2:
        result.auc = 0.0
    else:
        result.auc = metrics.roc_auc_score(y_true, y_prob)

    fpr, tpr, thresholds = metrics.roc_curve(y_true, y_prob)
    youden_index = tpr + (1 - fpr)
    result.best_threshold = thresholds[np.argmax(youden_index)]

    if result.best_threshold > 1:
        result.best_threshold = 0.5
    if threshold is not None:
        result.best_threshold = threshold

    y_pred = (y_prob >= result.best_threshold).astype(int)

    result.tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    result.tn = int(np.sum((y_true == 0) & (y_pred == 0)))
    result.fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    result.fn = int(np.sum((y_true == 1) & (y_pred == 0)))

    result.sensitivity = result.tp / (result.tp + result.fn + 1e-16)
    result.specificity = result.tn / (result.tn + result.fp + 1e-16)
    result.accuracy = (result.tp + result.tn) / (result.tp + result.tn + result.fp + result.fn + 1e-16)

    return result
