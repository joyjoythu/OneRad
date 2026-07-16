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

    # 手工计算：pred=[0,1,1,1]，TP=2，FP=1，n=4，pt/(1-pt)=1 → 2/4 - 1/4×1 = 0.25
    y2 = np.array([0.0, 0.0, 1.0, 1.0])
    p2 = np.array([0.1, 0.6, 0.7, 0.9])
    model_nb2, _ = _dca_arrays(y2, p2, np.array([0.5]))
    assert abs(model_nb2[0] - 0.25) < 1e-9
