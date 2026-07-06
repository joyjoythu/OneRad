import numpy as np
from app.metrics import calculate_metrics


def test_calculate_metrics():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.1, 0.4, 0.6, 0.9])
    m = calculate_metrics(y_true, y_prob)
    assert m.auc == 1.0
    assert m.accuracy == 1.0
