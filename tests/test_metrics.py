import numpy as np
import pytest
from app.metrics import calculate_metrics


def test_calculate_metrics_perfect_separation():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.1, 0.4, 0.6, 0.9])
    m = calculate_metrics(y_true, y_prob)
    assert m.auc == 1.0
    assert m.accuracy == 1.0
    assert m.sensitivity == 1.0
    assert m.specificity == 1.0
    assert m.tp == 2
    assert m.tn == 2
    assert m.fp == 0
    assert m.fn == 0


def test_calculate_metrics_threshold_override():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.1, 0.4, 0.6, 0.9])
    m = calculate_metrics(y_true, y_prob, threshold=0.5)
    assert m.best_threshold == 0.5
    assert m.tp == 2
    assert m.tn == 2
    assert m.fp == 0
    assert m.fn == 0


def test_calculate_metrics_imperfect_separation():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.2, 0.6, 0.4, 0.8])
    m = calculate_metrics(y_true, y_prob)
    assert m.auc < 1.0
    assert m.auc > 0.5

    # Threshold by Youden's index picks the highest threshold that maximizes
    # tpr - fpr; here both 0.8 and 0.4 give the same maximum, so the first
    # (0.8) is selected. Positives are prob >= 0.8.
    assert m.best_threshold == pytest.approx(0.8)
    assert m.tp == 1
    assert m.tn == 2
    assert m.fp == 0
    assert m.fn == 1
    assert m.sensitivity == 0.5
    assert m.specificity == 1.0
    assert m.accuracy == 0.75


def test_calculate_metrics_single_class():
    y_true = np.array([1, 1, 1, 1])
    y_prob = np.array([0.2, 0.4, 0.6, 0.8])
    m = calculate_metrics(y_true, y_prob)
    assert m.auc == 0.0
    assert m.best_threshold == 0.5
    # Default threshold 0.5 -> predictions [0, 0, 1, 1]
    assert m.tp == 2
    assert m.fn == 2
    assert m.tn == 0
    assert m.fp == 0
    assert m.sensitivity == 0.5
    assert m.specificity == 0.0
    assert m.accuracy == 0.5


def test_calculate_metrics_single_class_with_threshold_override():
    y_true = np.array([0, 0, 0, 0])
    y_prob = np.array([0.2, 0.4, 0.6, 0.8])
    m = calculate_metrics(y_true, y_prob, threshold=0.5)
    assert m.auc == 0.0
    assert m.best_threshold == 0.5
    # Default threshold 0.5 -> predictions [0, 0, 1, 1]
    assert m.tn == 2
    assert m.fp == 2
    assert m.tp == 0
    assert m.fn == 0
    assert m.specificity == 0.5
    assert m.sensitivity == 0.0
    assert m.accuracy == 0.5


def test_calculate_metrics_out_of_range_probability():
    y_true = np.array([0, 1])
    y_prob = np.array([-0.1, 1.1])
    with pytest.warns(UserWarning, match="outside \\[0, 1\\]"):
        calculate_metrics(y_true, y_prob)


def test_calculate_metrics_empty_inputs():
    y_true = np.array([], dtype=int)
    y_prob = np.array([], dtype=float)
    m = calculate_metrics(y_true, y_prob)
    assert m.auc == 0.0
    assert m.best_threshold == 0.5
    assert m.accuracy == 0.0
    assert m.sensitivity == 0.0
    assert m.specificity == 0.0
    assert m.tp == 0
    assert m.tn == 0
    assert m.fp == 0
    assert m.fn == 0


def test_calculate_metrics_mismatched_lengths():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.1, 0.4, 0.6])
    with pytest.raises(ValueError, match="same length"):
        calculate_metrics(y_true, y_prob)


def test_calculate_metrics_non_binary_labels():
    y_true = np.array([0, 1, 2, 1])
    y_prob = np.array([0.1, 0.4, 0.6, 0.9])
    with pytest.raises(ValueError, match="only 0 and 1"):
        calculate_metrics(y_true, y_prob)


def test_calculate_metrics_ppv_npv_f1():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.2, 0.6, 0.4, 0.8])
    m = calculate_metrics(y_true, y_prob)
    # Youden threshold 0.8: tp=1, fn=1, tn=2, fp=0
    assert m.ppv == pytest.approx(1.0)
    assert m.npv == pytest.approx(2 / 3)
    assert m.f1 == pytest.approx(2 * 1.0 * 0.5 / (1.0 + 0.5))


def test_calculate_metrics_perfect_separation_ppv_npv_f1():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.1, 0.4, 0.6, 0.9])
    m = calculate_metrics(y_true, y_prob)
    assert m.ppv == pytest.approx(1.0)
    assert m.npv == pytest.approx(1.0)
    assert m.f1 == pytest.approx(1.0)
