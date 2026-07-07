import pytest

from app.utils import parse_covariates


def test_parse_covariates_empty_string():
    assert parse_covariates("") == []


def test_parse_covariates_none():
    assert parse_covariates(None) == []


def test_parse_covariates_single_value():
    assert parse_covariates("Age") == ["Age"]


def test_parse_covariates_multiple_values_with_extra_spaces():
    assert parse_covariates("Age, Sex, BMI") == ["Age", "Sex", "BMI"]


def test_parse_covariates_trailing_comma():
    assert parse_covariates("Age, Sex,") == ["Age", "Sex"]


def test_parse_covariates_leading_and_trailing_spaces():
    assert parse_covariates("  Age  ,  Sex  ") == ["Age", "Sex"]
