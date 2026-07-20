import os
import h5py
import numpy as np
import pytest
from unittest.mock import patch
from app.feature import FeatureAgent
from app.utils import _load_feature_csv, rebuild_features_csv_from_h5


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


def _mock_extractor(image_path, mask_path, yaml_path):
    if "p1" in image_path:
        return {"f1": 1.0, "f2": 2.0}
    if "p3" in image_path:
        raise RuntimeError("mock extraction failure")
    return {"f1": 2.0, "f2": 3.0}


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

    out_dir = tmp_path / "features"
    result = FeatureAgent(extractor=_mock_extractor).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=str(out_dir)
    )

    assert result["success"] is True
    assert result["feature_df"].shape == (2, 4)
    assert set(result["feature_df"]["patient_id"]) == {"p1", "p2"}
    assert set(result["feature_names"]) == {"f1", "f2"}
    assert result["failed_ids"] == []
    assert result["settings_used"]["yaml_path"] == str(yaml_path)
    assert result["feature_path"] == str(out_dir / "radiomics_features.csv")
    assert os.path.exists(result["feature_path"])
    assert result["failed_path"] is None
    assert result["n_samples"] == 2
    assert result["n_success"] == 2
    assert result["n_failed"] == 0
    assert result["h5_dir"] == str(out_dir / "h5")


def test_feature_agent_overrides_resampled_pixel_spacing(tmp_path):
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("setting:\n  resampledPixelSpacing: [0.35, 0.35, 0.35]\n")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2")]

    received_yaml_path = None
    written_config = None

    def side_effect(image_path, mask_path, yaml_path):
        nonlocal received_yaml_path, written_config
        received_yaml_path = yaml_path
        if written_config is None:
            import yaml
            with open(yaml_path, "r", encoding="utf-8") as f:
                written_config = yaml.safe_load(f)
        if "p1" in image_path:
            return {"f1": 1.0, "f2": 2.0}
        return {"f1": 2.0, "f2": 3.0}

    result = FeatureAgent(extractor=side_effect).run(
        pairs,
        yaml_path=str(yaml_path),
        n_jobs=1,
        resampled_pixel_spacing=(0.5, 0.5, 0.5),
    )

    assert result["success"] is True
    assert result["settings_used"]["resampled_pixel_spacing"] == [0.5, 0.5, 0.5]
    assert received_yaml_path != str(yaml_path)
    assert written_config is not None
    assert written_config["setting"]["resampledPixelSpacing"] == [0.5, 0.5, 0.5]


def test_feature_agent_invalid_resampled_pixel_spacing(tmp_path):
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("setting:\n  resampledPixelSpacing: [0.35, 0.35, 0.35]\n")
    pairs = [_make_pair(tmp_path, "p1")]

    result = FeatureAgent(extractor=_mock_extractor).run(
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

    out_dir = tmp_path / "features"
    with patch("app.feature.cir_get_features") as mock_cir:
        mock_cir.side_effect = _mock_extractor
        result = FeatureAgent().run(pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=str(out_dir))

    assert result["success"] is True
    assert result["feature_df"].shape == (2, 4)
    assert set(result["feature_df"]["patient_id"]) == {"p1", "p2"}
    assert result["failed_ids"] == ["p3"]
    assert result["feature_path"] == str(out_dir / "radiomics_features.csv")
    assert os.path.exists(result["feature_path"])
    assert result["failed_path"] == str(out_dir / "failed_cases.csv")
    assert os.path.exists(result["failed_path"])
    assert result["n_samples"] == 3
    assert result["n_success"] == 2
    assert result["n_failed"] == 1
    assert result["failed_examples"] == ["p3"]


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
    assert result["feature_df"].shape == (2, 3)


def test_feature_agent_malformed_pair(tmp_path):
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [{"patient_id": "p1", "image_path": str(tmp_path / "img.nii")}]  # missing mask_path

    result = FeatureAgent().run(pairs, yaml_path=str(yaml_path), n_jobs=1)

    assert result["success"] is False
    assert "pair 缺少必要字段" in result["message"]
    assert "mask_path" in result["message"]


def test_get_extractor_imports_real_cir_get_features():
    """The default extractor must be importable without patching."""
    agent = FeatureAgent()
    extractor = agent._get_extractor()
    assert extractor is not None
    assert callable(extractor)


def test_feature_agent_progress_callback_reports_each_case(tmp_path):
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2")]

    events = []
    result = FeatureAgent(extractor=_mock_extractor).run(
        pairs,
        yaml_path=str(yaml_path),
        n_jobs=1,
        output_dir=str(tmp_path / "features"),
        progress_callback=events.append,
    )

    assert result["success"] is True
    assert events[0] == {"stage": "start", "current": 0, "total": 2}
    extracting = [e for e in events if e["stage"] == "extracting"]
    assert [(e["current"], e["patient_id"]) for e in extracting] == [(1, "p1"), (2, "p2")]
    assert any(e["stage"] == "finalizing" for e in events)


def test_feature_agent_cancel_event_aborts_after_current_case(tmp_path):
    """取消事件置位后，当前病例跑完即停止，已完成的 partial 结果仍保存。"""
    import threading

    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2")]
    cancel_event = threading.Event()
    calls = []

    def extractor(image_path, mask_path, yaml_path):
        calls.append(image_path)
        cancel_event.set()  # 模拟用户在第一例提取期间点击停止
        return {"f1": 1.0, "f2": 2.0}

    out_dir = tmp_path / "features"
    result = FeatureAgent(extractor=extractor).run(
        pairs,
        yaml_path=str(yaml_path),
        n_jobs=1,
        output_dir=str(out_dir),
        cancel_event=cancel_event,
    )

    assert len(calls) == 1  # 第二例未再提取
    assert result["success"] is True
    assert result["cancelled"] is True
    assert "已取消" in result["message"]
    assert result["n_success"] == 1
    assert set(result["feature_df"]["patient_id"]) == {"p1"}
    assert os.path.exists(result["feature_path"])


def test_feature_agent_cancel_before_start_returns_no_results(tmp_path):
    import threading

    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [_make_pair(tmp_path, "p1")]
    cancel_event = threading.Event()
    cancel_event.set()

    result = FeatureAgent(extractor=_mock_extractor).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, cancel_event=cancel_event
    )

    assert result["success"] is False
    assert result["cancelled"] is True
    assert "已取消" in result["message"]


def _counting_extractor(calls, base=_mock_extractor):
    def extractor(image_path, mask_path, yaml_path):
        calls.append(image_path)
        return base(image_path, mask_path, yaml_path)
    return extractor


def test_resume_skips_cached_cases(tmp_path):
    """第二次运行时，已有 h5 缓存的病例不再提取，只提新病例。"""
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2")]
    out_dir = str(tmp_path / "features")

    first = FeatureAgent(extractor=_mock_extractor).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=out_dir)
    assert first["success"] is True

    calls = []
    pairs2 = pairs + [_make_pair(tmp_path, "p4")]
    second = FeatureAgent(extractor=_counting_extractor(calls)).run(
        pairs2, yaml_path=str(yaml_path), n_jobs=1, output_dir=out_dir)

    assert second["success"] is True
    assert len(calls) == 1  # 只有 p4 被真正提取
    assert "p4" in calls[0]
    assert second["resumed"] is True
    assert second["n_skipped"] == 2
    assert second["feature_df"].shape[0] == 3
    assert set(second["feature_df"]["patient_id"]) == {"p1", "p2", "p4"}
    assert "缓存 2 例" in second["message"]
    # 缓存行的特征值来自第一次运行
    row_p1 = second["feature_df"].set_index("patient_id").loc["p1"]
    assert row_p1["f1"] == 1.0 and row_p1["f2"] == 2.0


def test_resume_rebuilds_csv_from_h5(tmp_path):
    """CSV 被删除/覆盖后，可从 h5 缓存完整重建，零提取调用。"""
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2")]
    out_dir = str(tmp_path / "features")

    FeatureAgent(extractor=_mock_extractor).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=out_dir)
    os.remove(os.path.join(out_dir, "radiomics_features.csv"))

    calls = []
    result = FeatureAgent(extractor=_counting_extractor(calls)).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=out_dir)

    assert result["success"] is True
    assert calls == []
    assert result["n_skipped"] == 2
    assert os.path.exists(result["feature_path"])
    assert result["feature_df"].shape == (2, 4)


def test_settings_change_triggers_full_rerun(tmp_path):
    """YAML 内容变化后，忽略 h5 缓存全量重提。"""
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2")]
    out_dir = str(tmp_path / "features")

    FeatureAgent(extractor=_mock_extractor).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=out_dir)

    yaml_path.write_text("setting:\n  binWidth: 10\n")  # 修改设置

    calls = []
    result = FeatureAgent(extractor=_counting_extractor(calls)).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=out_dir)

    assert result["success"] is True
    assert len(calls) == 2
    assert result["n_skipped"] == 0


def test_force_rerun_ignores_cache(tmp_path):
    """resume=False 时即使有缓存也全部重新提取。"""
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2")]
    out_dir = str(tmp_path / "features")

    FeatureAgent(extractor=_mock_extractor).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=out_dir)

    calls = []
    result = FeatureAgent(extractor=_counting_extractor(calls)).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=out_dir,
        resume=False)

    assert result["success"] is True
    assert len(calls) == 2
    assert result["n_skipped"] == 0


def test_failed_case_retried_on_resume(tmp_path):
    """上次失败的病例没有 h5 缓存，续提时会自动重试。"""
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2"),
             _make_pair(tmp_path, "p3")]  # p3 在 _mock_extractor 中会失败
    out_dir = str(tmp_path / "features")

    first = FeatureAgent(extractor=_mock_extractor).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=out_dir)
    assert first["failed_ids"] == ["p3"]

    calls = []
    second = FeatureAgent(extractor=_counting_extractor(calls)).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=out_dir)

    assert len(calls) == 1
    assert "p3" in calls[0]
    assert second["failed_ids"] == ["p3"]
    assert second["n_success"] == 2


def test_load_feature_csv_rebuilds_from_h5(tmp_path):
    """CSV 删除后，_load_feature_csv 自动从 h5 缓存重建（含 patient_id）。"""
    yaml_path = tmp_path / "params.yaml"
    yaml_path.write_text("")
    pairs = [_make_pair(tmp_path, "p1"), _make_pair(tmp_path, "p2")]
    out_dir = str(tmp_path / "features")

    FeatureAgent(extractor=_mock_extractor).run(
        pairs, yaml_path=str(yaml_path), n_jobs=1, output_dir=out_dir)
    csv_path = os.path.join(out_dir, "radiomics_features.csv")
    os.remove(csv_path)

    df = _load_feature_csv(csv_path)
    assert os.path.exists(csv_path)  # 重建后落盘
    assert set(df["patient_id"]) == {"p1", "p2"}
    assert {"f1", "f2"} <= set(df.columns)
    row_p1 = df.set_index("patient_id").loc["p1"]
    assert row_p1["f1"] == 1.0 and row_p1["f2"] == 2.0


def test_rebuild_skips_legacy_h5_without_patient_id(tmp_path):
    """旧版 h5（无 patient_id）无法重建，_load_feature_csv 仍报文件不存在。"""
    h5_dir = tmp_path / "features" / "h5"
    h5_dir.mkdir(parents=True)
    with h5py.File(h5_dir / "legacy.h5", "w") as hf:
        hf.create_dataset("f_values", data=np.array([[1.0, 2.0]]))
        hf.create_dataset(
            "feature_names",
            data=np.array(["f1", "f2"], dtype=h5py.string_dtype("utf-8")))

    csv_path = str(tmp_path / "features" / "radiomics_features.csv")
    assert rebuild_features_csv_from_h5(str(h5_dir), csv_path) is None
    with pytest.raises(FileNotFoundError, match="特征文件不存在"):
        _load_feature_csv(csv_path)
