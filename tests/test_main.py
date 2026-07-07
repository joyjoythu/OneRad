import pytest

from main import _parse_args


def test_parse_args_with_image_dir_and_clinical():
    args = _parse_args(["--image-dir", "./img", "--clinical", "./cli.csv"])
    assert args.ui is False
    assert args.image_dir == "./img"
    assert args.clinical == "./cli.csv"


def test_parse_args_ui_flag():
    args = _parse_args(["--ui"])
    assert args.ui is True


def test_parse_args_no_args_defaults_to_ui():
    args = _parse_args([])
    assert args.ui is False
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


def test_parse_args_model_default():
    args = _parse_args([])
    assert args.model == "deepseek-chat"


def test_main_cli_pipeline_error(monkeypatch, capsys):
    from unittest.mock import MagicMock, patch

    from main import main

    mock_args = MagicMock()
    mock_args.ui = False
    mock_args.image_dir = "./img"
    mock_args.clinical = "./cli.csv"
    mock_args.output_dir = "./out"
    mock_args.modality = "auto"
    mock_args.covariates = ""
    mock_args.resampled_pixel_spacing = None
    mock_args.api_key = ""
    mock_args.base_url = "https://api.deepseek.com/v1"
    mock_args.model = "deepseek-chat"
    monkeypatch.setattr("main._parse_args", lambda argv=None: mock_args)

    mock_orch = MagicMock()
    mock_orch.run.side_effect = RuntimeError("pipeline failed")
    with patch("app.orchestrator.Orchestrator", return_value=mock_orch), patch("app.orchestrator.register_default_handlers"):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "pipeline failed" in captured.err or "流水线执行失败" in captured.err
