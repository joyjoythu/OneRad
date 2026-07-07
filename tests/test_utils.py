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


def test_parse_float_tuple_valid():
    from app.utils import parse_float_tuple
    assert parse_float_tuple("0.5,0.5,0.5") == (0.5, 0.5, 0.5)
    assert parse_float_tuple("  1 , 2 , 3  ") == (1.0, 2.0, 3.0)


def test_parse_float_tuple_empty():
    from app.utils import parse_float_tuple
    assert parse_float_tuple(None) is None
    assert parse_float_tuple("") is None
    assert parse_float_tuple("   ") is None


def test_parse_float_tuple_wrong_length():
    from app.utils import parse_float_tuple
    with pytest.raises(ValueError, match="需要 3 个数值"):
        parse_float_tuple("0.5,0.5")
    with pytest.raises(ValueError, match="需要 3 个数值"):
        parse_float_tuple("0.5,0.5,0.5,0.5")


def test_parse_float_tuple_invalid_value():
    from app.utils import parse_float_tuple
    with pytest.raises(ValueError):
        parse_float_tuple("0.5,abc,0.5")
