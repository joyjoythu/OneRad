from unittest.mock import MagicMock

from app.discovery import DiscoveryAgent, extract_patient_id, infer_modality
from app.llm import LLMClient


def test_extract_patient_id():
    assert extract_patient_id("P001_image") == "P001"
    assert extract_patient_id("P001_mask") == "P001"
    assert extract_patient_id("1001") == "1001"


def test_classify_and_pair(tmp_path):
    (tmp_path / "P001_image.nii.gz").write_text("")
    (tmp_path / "P001_mask.nii.gz").write_text("")
    (tmp_path / "P002_image.nii.gz").write_text("")

    agent = DiscoveryAgent()
    result = agent.run(str(tmp_path))
    assert result["success"] is True
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["patient_id"] == "P001"


def test_false_positive_tumor_volume_is_image(tmp_path):
    (tmp_path / "P001_tumor_volume.nii.gz").write_text("")
    (tmp_path / "P001_mask.nii.gz").write_text("")

    agent = DiscoveryAgent()
    result = agent.run(str(tmp_path))

    assert result["success"] is True
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["image_path"] == str(tmp_path / "P001_tumor_volume.nii.gz")
    assert result["pairs"][0]["mask_path"] == str(tmp_path / "P001_mask.nii.gz")


def test_mask_with_modality_suffix_is_classified(tmp_path):
    (tmp_path / "P001_T1.nii.gz").write_text("")
    (tmp_path / "P001_mask_T1.nii.gz").write_text("")

    agent = DiscoveryAgent()
    result = agent.run(str(tmp_path))

    assert result["success"] is True
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["image_path"] == str(tmp_path / "P001_T1.nii.gz")
    assert result["pairs"][0]["mask_path"] == str(tmp_path / "P001_mask_T1.nii.gz")


def test_hidden_directories_are_skipped(tmp_path):
    visible = tmp_path / "visible"
    visible.mkdir()
    hidden = tmp_path / ".hidden"
    hidden.mkdir()

    (visible / "P001_image.nii.gz").write_text("")
    (hidden / "P001_hidden.nii.gz").write_text("")
    (tmp_path / "P001_mask.nii.gz").write_text("")

    agent = DiscoveryAgent(recursive=True)
    result = agent.run(str(tmp_path))

    assert result["success"] is True
    all_paths = {
        p["image_path"] for p in result["pairs"]
    } | {
        p["mask_path"] for p in result["pairs"]
    }
    assert str(hidden / "P001_hidden.nii.gz") not in all_paths
    assert str(visible / "P001_image.nii.gz") in {p["image_path"] for p in result["pairs"]}


def test_invalid_id_pattern_returns_error(tmp_path):
    (tmp_path / "P001_image.nii.gz").write_text("")

    agent = DiscoveryAgent(id_pattern="[invalid")
    result = agent.run(str(tmp_path))

    assert result["success"] is False
    assert "患者ID正则无效" in result["message"]
    assert result["pairs"] == []


def test_multiple_images_share_one_mask(tmp_path):
    (tmp_path / "P001_CT.nii.gz").write_text("")
    (tmp_path / "P001_MRI.nii.gz").write_text("")
    (tmp_path / "P001_mask.nii.gz").write_text("")

    agent = DiscoveryAgent()
    result = agent.run(str(tmp_path))

    assert result["success"] is True
    assert len(result["pairs"]) == 2
    assert all(p["mask_path"] == str(tmp_path / "P001_mask.nii.gz") for p in result["pairs"])
    assert {p["modality"] for p in result["pairs"]} == {"CT", "MRI"}


def test_infer_modality():
    assert infer_modality("P001_CT") == "CT"
    assert infer_modality("brain_mri_scan") == "MRI"
    assert infer_modality("P001_PET") == "PET"
    assert infer_modality("P001_brain") == "UNKNOWN"


def test_non_existent_directory():
    agent = DiscoveryAgent()
    result = agent.run("/this/path/does/not/exist")

    assert result["success"] is False
    assert "目录不存在" in result["message"]
    assert result["pairs"] == []


def test_discovery_with_llm_id_inference(tmp_path):
    (tmp_path / "SUB_001_image.nii.gz").write_text("")
    (tmp_path / "SUB_001_mask.nii.gz").write_text("")

    mock_llm = LLMClient()
    mock_llm.call = MagicMock(
        return_value='{"pattern": "SUB_\\\\d+", "explanation": "test"}'
    )

    agent = DiscoveryAgent(llm_client=mock_llm)
    result = agent.run(str(tmp_path))

    assert result["success"] is True
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["patient_id"] == "SUB_001"
    mock_llm.call.assert_called_once()
    assert agent.id_pattern is None


def test_llm_invalid_json_fallback(tmp_path):
    (tmp_path / "SUB_001_image.nii.gz").write_text("")
    (tmp_path / "SUB_001_mask.nii.gz").write_text("")

    mock_llm = LLMClient()
    mock_llm.call = MagicMock(return_value="not valid json")

    agent = DiscoveryAgent(llm_client=mock_llm)
    result = agent.run(str(tmp_path))

    assert result["success"] is True
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["patient_id"] == "SUB_001"
    mock_llm.call.assert_called_once()


def test_llm_invalid_regex_fallback(tmp_path):
    (tmp_path / "SUB_001_image.nii.gz").write_text("")
    (tmp_path / "SUB_001_mask.nii.gz").write_text("")

    mock_llm = LLMClient()
    mock_llm.call = MagicMock(
        return_value='{"pattern": "[invalid", "explanation": "test"}'
    )

    agent = DiscoveryAgent(llm_client=mock_llm)
    result = agent.run(str(tmp_path))

    assert result["success"] is True
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["patient_id"] == "SUB_001"
    mock_llm.call.assert_called_once()


def test_llm_exception_fallback(tmp_path):
    (tmp_path / "SUB_001_image.nii.gz").write_text("")
    (tmp_path / "SUB_001_mask.nii.gz").write_text("")

    mock_llm = LLMClient()
    mock_llm.call = MagicMock(side_effect=ValueError("LLM failed"))

    agent = DiscoveryAgent(llm_client=mock_llm)
    result = agent.run(str(tmp_path))

    assert result["success"] is True
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["patient_id"] == "SUB_001"
    mock_llm.call.assert_called_once()


def test_fewer_than_two_samples_no_llm_call(tmp_path):
    (tmp_path / "SUB_001_image.nii.gz").write_text("")

    mock_llm = LLMClient()
    mock_llm.call = MagicMock()

    agent = DiscoveryAgent(llm_client=mock_llm)
    result = agent.run(str(tmp_path))

    mock_llm.call.assert_not_called()
    assert result["success"] is False
    assert "未找到可配对的影像/掩码" in result["message"]
    assert result["pairs"] == []
    assert result["unpaired_images"] == [str(tmp_path / "SUB_001_image.nii.gz")]


def test_mismatched_patient_ids_return_failure(tmp_path):
    (tmp_path / "P001_image.nii.gz").write_text("")
    (tmp_path / "P002_mask.nii.gz").write_text("")

    agent = DiscoveryAgent()
    result = agent.run(str(tmp_path))

    assert result["success"] is False
    assert "未找到可配对的影像/掩码" in result["message"]
    assert result["pairs"] == []
    assert len(result["unpaired_images"]) == 1
    assert len(result["unpaired_masks"]) == 1


def test_extract_patient_id_strips_nnu_net_channel_suffix():
    from app.discovery import extract_patient_id
    assert extract_patient_id("P001_0000") == "P001"
    assert extract_patient_id("case_01_0001") == "case_01"
    assert extract_patient_id("P001_0000_mask") == "P001"


def test_label_folder_files_treated_as_masks(tmp_path):
    images_dir = tmp_path / "images"
    labels_dir = tmp_path / "labels"
    images_dir.mkdir()
    labels_dir.mkdir()

    (images_dir / "P001_0000.nii.gz").write_text("")
    (labels_dir / "P001.nii.gz").write_text("")

    agent = DiscoveryAgent()
    result = agent.run(str(tmp_path))

    assert result["success"] is True
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["patient_id"] == "P001"
    assert result["pairs"][0]["image_path"] == str(images_dir / "P001_0000.nii.gz")
    assert result["pairs"][0]["mask_path"] == str(labels_dir / "P001.nii.gz")


def test_label_folder_with_mask_keyword_suffix(tmp_path):
    images_dir = tmp_path / "imagesTr"
    labels_dir = tmp_path / "labelsTr"
    images_dir.mkdir()
    labels_dir.mkdir()

    (images_dir / "P001_0000.nii.gz").write_text("")
    (labels_dir / "P001_mask.nii.gz").write_text("")

    agent = DiscoveryAgent()
    result = agent.run(str(tmp_path))

    assert result["success"] is True
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["patient_id"] == "P001"
