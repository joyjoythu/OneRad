import pytest
from unittest.mock import patch
from app.feature import FeatureAgent


def _make_pair(tmp_path, patient_id, image_name="img.nii", mask_name="mask.nii"):
    d = tmp_path / patient_id
    d.mkdir()
    img_path = d / image_name
    mask_path = d / mask_name
    img_path.write_text("")
    mask_path.write_text("")
    return {
        "patient_id": patient_id,
        "image_path": str(img_path),
        "mask_path": str(mask_path),
    }


def test_feature_agent_empty_pairs():
    agent = FeatureAgent()
    result = agent.run([])
    assert result["success"] is False
    assert result["message"] == "pairs 为空"


def test_feature_agent_missing_yaml(tmp_path):
    agent = FeatureAgent()
    pairs = [_make_pair(tmp_path, "p1")]
    result = agent.run(pairs, yaml_path=str(tmp_path / "missing.yaml"), n_jobs=1)
    assert result["success"] is False
    assert "YAML 配置不存在" in result["message"]


def test_feature_agent_two_valid_pairs(tmp_path):
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("setting:\n  resampledPixelSpacing: [0.35, 0.35, 0.35]\n")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2")]

    def side_effect(image_path, mask_path, yaml_path):
        if "p1" in image_path:
            return {"f1": 1.0, "f2": 2.0}
        return {"f1": 2.0, "f2": 3.0}

    with patch("app.feature.cir_get_features") as mock_cir:
        mock_cir.side_effect = side_effect
        result = FeatureAgent().run(pairs, yaml_path=str(yaml_path), n_jobs=1)

    assert result["success"] is True
    assert result["feature_df"].shape == (2, 2)
    assert list(result["feature_df"].index) == ["p1", "p2"]
    assert set(result["feature_names"]) == {"f1", "f2"}
    assert result["failed_ids"] == []
    assert result["settings_used"]["yaml_path"] == str(yaml_path)


def test_feature_agent_overrides_resampled_pixel_spacing(tmp_path):
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("setting:\n  resampledPixelSpacing: [0.35, 0.35, 0.35]\n")
    pairs = [_make_pair(tmp_path, "p1")]

    received_yaml_path = None

    def side_effect(image_path, mask_path, yaml_path):
        nonlocal received_yaml_path
        received_yaml_path = yaml_path
        return {"f1": 1.0}

    with patch("app.feature.cir_get_features") as mock_cir:
        mock_cir.side_effect = side_effect
        result = FeatureAgent().run(
            pairs,
            yaml_path=str(yaml_path),
            n_jobs=1,
            resampled_pixel_spacing=(0.5, 0.5, 0.5),
        )

    assert result["success"] is True
    assert result["settings_used"]["resampled_pixel_spacing"] == [0.5, 0.5, 0.5]
    assert received_yaml_path != str(yaml_path)
    assert os.path.exists(received_yaml_path)
    import yaml
    with open(received_yaml_path, "r", encoding="utf-8") as f:
        written = yaml.safe_load(f)
    assert written["setting"]["resampledPixelSpacing"] == [0.5, 0.5, 0.5]


def test_feature_agent_invalid_resampled_pixel_spacing(tmp_path):
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("setting:\n  resampledPixelSpacing: [0.35, 0.35, 0.35]\n")
    pairs = [_make_pair(tmp_path, "p1")]

    result = FeatureAgent().run(
        pairs,
        yaml_path=str(yaml_path),
        n_jobs=1,
        resampled_pixel_spacing=(0.5, 0.5),  # wrong length
    )

    assert result["success"] is False
    assert "准备 YAML 失败" in result["message"] or "需要 3 个数值" in result["message"]


def test_feature_agent_one_failing_pair(tmp_path):
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [
        _make_pair(tmp_path, "p1"),
        _make_pair(tmp_path, "p2"),
        _make_pair(tmp_path, "p3"),
    ]

    def side_effect(image_path, mask_path, yaml_path):
        if "p3" in image_path:
            raise RuntimeError("mock extraction failure")
        if "p1" in image_path:
            return {"f1": 1.0, "f2": 2.0}
        return {"f1": 2.0, "f2": 3.0}

    with patch("app.feature.cir_get_features") as mock_cir:
        mock_cir.side_effect = side_effect
        result = FeatureAgent().run(pairs, yaml_path=str(yaml_path), n_jobs=1)

    assert result["success"] is True
    assert result["feature_df"].shape == (2, 2)
    assert set(result["feature_df"].index) == {"p1", "p2"}
    assert result["failed_ids"] == ["p3"]


def test_feature_agent_all_pairs_failing(tmp_path):
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2")]

    with patch("app.feature.cir_get_features") as mock_cir:
        mock_cir.side_effect = RuntimeError("mock extraction failure")
        result = FeatureAgent().run(pairs, yaml_path=str(yaml_path), n_jobs=1)

    assert result["success"] is False
    assert "所有样本特征提取均失败" in result["message"]


def test_feature_agent_zero_variance_feature(tmp_path):
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2")]

    def side_effect(image_path, mask_path, yaml_path):
        if "p1" in image_path:
            return {"constant": 5.0, "varying": 1.0}
        return {"constant": 5.0, "varying": 2.0}

    with patch("app.feature.cir_get_features") as mock_cir:
        mock_cir.side_effect = side_effect
        result = FeatureAgent().run(pairs, yaml_path=str(yaml_path), n_jobs=1)

    assert result["success"] is True
    assert "constant" not in result["feature_names"]
    assert "varying" in result["feature_names"]
    assert result["zero_variance_features"] == ["constant"]
    assert result["feature_df"].shape == (2, 1)


def test_feature_agent_malformed_pair(tmp_path):
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [{"patient_id": "p1", "image_path": str(tmp_path / "img.nii")}]  # missing mask_path

    result = FeatureAgent().run(pairs, yaml_path=str(yaml_path), n_jobs=1)

    assert result["success"] is False
    assert "pair 缺少必要字段" in result["message"]
    assert "mask_path" in result["message"]
