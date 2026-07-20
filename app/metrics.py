from dataclasses import dataclass
from typing import Optional
import warnings
import numpy as np
from sklearn import metrics


@dataclass
class MetricsResult:
    """Container for binary classification performance metrics.

    Fields:
        accuracy: Proportion of correctly classified samples.
        sensitivity: True positive rate (recall for the positive class).
        specificity: True negative rate (recall for the negative class).
        ppv: Positive predictive value (precision).
        npv: Negative predictive value.
        f1: Harmonic mean of PPV and sensitivity.
        auc: Area under the ROC curve; 0.0 when only one class is present.
        best_threshold: Decision threshold used to binarize probabilities.
        tp: Count of true positives.
        tn: Count of true negatives.
        fn: Count of false negatives.
        fp: Count of false positives.
    """

    accuracy: float = 0.0
    sensitivity: float = 0.0
    specificity: float = 0.0
    ppv: float = 0.0
    npv: float = 0.0
    f1: float = 0.0
    auc: float = 0.0
    best_threshold: float = 0.5
    tp: int = 0
    tn: int = 0
    fn: int = 0
    fp: int = 0


def calculate_metrics(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: Optional[float] = None,
) -> MetricsResult:
    """Compute binary classification metrics and the ROC AUC.

    When only one class is present in `y_true`, the ROC AUC is undefined and
    returned as 0.0. The remaining metrics are still computed using the selected
    threshold (the explicit override if provided, otherwise 0.5).

    A small epsilon of ``1e-16`` is added to denominators to avoid division by
    zero when a class has no samples in the confusion matrix.

    Args:
        y_true: Ground-truth binary labels, expected to contain only 0 and 1.
        y_prob: Predicted probabilities for the positive class.
        threshold: Optional decision threshold. When provided, it overrides
            the threshold selected by Youden's index.

    Returns:
        MetricsResult containing accuracy, sensitivity, specificity, PPV,
        NPV, F1, AUC, best threshold, and confusion matrix counts.

    Raises:
        ValueError: If `y_true` and `y_prob` have different lengths, or if
            `y_true` contains values other than 0 and 1.
    """
    if len(y_true) != len(y_prob):
        raise ValueError("y_true and y_prob must have the same length")

    if not np.isin(y_true, [0, 1]).all():
        raise ValueError("y_true must contain only 0 and 1")

    if np.any(y_prob < 0) or np.any(y_prob > 1):
        warnings.warn("y_prob contains values outside [0, 1]")

    result = MetricsResult()

    # When only one class is present, no ROC curve can be computed; fall back
    # to the selected threshold for the confusion matrix.
    if len(np.unique(y_true)) < 2:
        result.auc = 0.0
        result.best_threshold = threshold if threshold is not None else 0.5
    else:
        result.auc = metrics.roc_auc_score(y_true, y_prob)

        fpr, tpr, thresholds = metrics.roc_curve(y_true, y_prob)
        youden_index = tpr - fpr
        result.best_threshold = thresholds[np.argmax(youden_index)]

        if threshold is not None:
            result.best_threshold = threshold

    y_pred = (y_prob >= result.best_threshold).astype(int)

    result.tp = int(np.sum((y_true == 1) & (y_pred == 1)))
    result.tn = int(np.sum((y_true == 0) & (y_pred == 0)))
    result.fp = int(np.sum((y_true == 0) & (y_pred == 1)))
    result.fn = int(np.sum((y_true == 1) & (y_pred == 0)))

    # 1e-16 is added to denominators to avoid division by zero when a class
    # has no samples in the confusion matrix.
    result.sensitivity = result.tp / (result.tp + result.fn + 1e-16)
    result.specificity = result.tn / (result.tn + result.fp + 1e-16)
    result.accuracy = (result.tp + result.tn) / (result.tp + result.tn + result.fp + result.fn + 1e-16)
    result.ppv = result.tp / (result.tp + result.fp + 1e-16)
    result.npv = result.tn / (result.tn + result.fn + 1e-16)
    result.f1 = 2 * result.ppv * result.sensitivity / (result.ppv + result.sensitivity + 1e-16)

    return result
