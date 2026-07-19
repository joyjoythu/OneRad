import argparse

import pandas as pd
import pytest

from main import _parse_args, _should_run_server


def test_parse_args_with_image_dir_and_clinical():
    args = _parse_args(["--image-dir", "./img", "--clinical", "./cli.csv"])
    assert _should_run_server(args) is False
    assert args.image_dir == "./img"
    assert args.clinical == "./cli.csv"


def test_parse_args_no_args_defaults_to_server():
    args = _parse_args([])
    assert _should_run_server(args) is True
    assert args.image_dir is None
    assert args.clinical is None


def test_parse_args_covariates_parsing():
    args = _parse_args(["--covariates", "Age, Sex"])
    assert args.covariates == "Age, Sex"


def test_parse_args_resampled_pixel_spacing():
    args = _parse_args(["--resampled-pixel-spacing", "0.5,0.5,0.5"])
    assert args.resampled_pixel_spacing == "0.5,0.5,0.5"


def test_parse_args_base_url_default():
    args = _parse_args([])
    assert args.base_url == "https://api.deepseek.com/v1"


def test_parse_args_rejects_removed_model_option():
    with pytest.raises(SystemExit):
        _parse_args(["--model", "deepseek-v4-pro"])


def test_parse_args_host_port_defaults():
    args = _parse_args([])
    assert args.host == "0.0.0.0"
    assert args.port == 8000


def test_parse_args_help_includes_host_and_port(capsys):
    with pytest.raises(SystemExit) as exc_info:
        _parse_args(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "--host" in captured.out
    assert "--port" in captured.out


def test_should_run_server_no_args():
    args = _parse_args([])
    assert _should_run_server(args) is True


def test_should_run_server_with_image_dir():
    args = _parse_args(["--image-dir", "foo"])
    assert _should_run_server(args) is False


def test_should_run_server_with_feature_csv():
    args = _parse_args(["--feature-csv", "foo.csv"])
    assert _should_run_server(args) is False


def test_main_cli_pipeline_error(monkeypatch, capsys):
    from unittest.mock import MagicMock, patch

    from main import main

    mock_args = MagicMock()
    mock_args.image_dir = "./img"
    mock_args.clinical = "./cli.csv"
    mock_args.feature_csv = None
    mock_args.label_col = None
    mock_args.output_dir = "./out"
    mock_args.modality = "auto"
    mock_args.covariates = ""
    mock_args.max_lasso_features = 100
    mock_args.n_splits = 5
    mock_args.resampled_pixel_spacing = None
    mock_args.api_key = ""
    mock_args.base_url = "https://api.deepseek.com/v1"
    mock_args.host = "0.0.0.0"
    mock_args.port = 8000
    monkeypatch.setattr("main._parse_args", lambda argv=None: mock_args)

    mock_orch = MagicMock()
    mock_orch.run.side_effect = RuntimeError("pipeline failed")
    with patch("app.orchestrator.Orchestrator", return_value=mock_orch), patch("app.orchestrator.register_default_handlers"):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "pipeline failed" in captured.err or "流水线执行失败" in captured.err


def test_main_feature_csv_direct_analysis(tmp_path, monkeypatch):
    """End-to-end test for running LASSO + logistic regression from feature CSV."""
    import numpy as np
    from main import main

    rng = np.random.RandomState(42)
    n = 40
    feature_df = pd.DataFrame({
        "patient_id": [f"P{i:03d}" for i in range(n)],
    })
    for j in range(20):
        feature_df[f"original_feat_{j}"] = rng.randn(n)
    # Add a weak signal so LASSO can select something
    label = rng.randint(0, 2, n)
    feature_df["original_feat_0"] += label * 1.5

    clinical_df = pd.DataFrame({
        "patient_id": [f"P{i:03d}" for i in range(n)],
        "Label": label,
    })

    feature_csv = tmp_path / "features.csv"
    clinical_csv = tmp_path / "clinical.csv"
    feature_df.to_csv(feature_csv, index=False)
    clinical_df.to_csv(clinical_csv, index=False)

    output_dir = tmp_path / "out"

    monkeypatch.setattr("main._parse_args", lambda argv=None: argparse.Namespace(
        image_dir=None,
        clinical=str(clinical_csv),
        feature_csv=str(feature_csv),
        label_col=None,
        output_dir=str(output_dir),
        modality="auto",
        covariates="",
        max_lasso_features=20,
        n_splits=3,
        resampled_pixel_spacing=None,
        api_key=None,
        base_url="https://api.deepseek.com/v1",
        host="0.0.0.0",
        port=8000,
    ))

    main()

    report_files = list(output_dir.glob("*.docx"))
    assert len(report_files) == 1, f"Expected one DOCX report, found {report_files}"


def test_main_uses_cached_features_csv_when_available(tmp_path, monkeypatch):
    """If output_dir/radiomics_features.csv exists, --image-dir runs should reuse it."""
    import numpy as np
    from main import main

    rng = np.random.RandomState(7)
    n = 40
    label = rng.randint(0, 2, n)
    feature_df = pd.DataFrame({
        "patient_id": [f"P{i:03d}" for i in range(n)],
    })
    for j in range(20):
        feature_df[f"original_feat_{j}"] = rng.randn(n)
    feature_df["original_feat_0"] += label * 1.5

    clinical_df = pd.DataFrame({
        "patient_id": [f"P{i:03d}" for i in range(n)],
        "Label": label,
    })

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    cached_feature_csv = output_dir / "radiomics_features.csv"
    clinical_csv = tmp_path / "clinical.csv"
    feature_df.to_csv(cached_feature_csv, index=False)
    clinical_df.to_csv(clinical_csv, index=False)

    monkeypatch.setattr("main._parse_args", lambda argv=None: argparse.Namespace(
        image_dir="./nonexistent_images",  # should not be touched
        clinical=str(clinical_csv),
        feature_csv=None,
        label_col=None,
        output_dir=str(output_dir),
        modality="auto",
        covariates="",
        max_lasso_features=20,
        n_splits=3,
        resampled_pixel_spacing=None,
        api_key=None,
        base_url="https://api.deepseek.com/v1",
        host="0.0.0.0",
        port=8000,
    ))

    main()

    report_files = list(output_dir.glob("*.docx"))
    assert len(report_files) == 1, f"Expected one DOCX report, found {report_files}"
