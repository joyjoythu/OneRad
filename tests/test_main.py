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


def test_parse_args_base_url_default():
    args = _parse_args([])
    assert args.base_url == "https://api.deepseek.com/v1"


def test_parse_args_model_default():
    args = _parse_args([])
    assert args.model == "deepseek-chat"
