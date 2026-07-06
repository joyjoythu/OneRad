from pathlib import Path
from app.discovery import DiscoveryAgent, extract_patient_id


def test_extract_patient_id():
    assert extract_patient_id("P001_image") == "P001"
    assert extract_patient_id("P001_mask") == "P001"
    assert extract_patient_id("1001") == "1001"


def test_classify_and_pair(tmp_path):
    # 创建临时文件
    (tmp_path / "P001_image.nii.gz").write_text("")
    (tmp_path / "P001_mask.nii.gz").write_text("")
    (tmp_path / "P002_image.nii.gz").write_text("")

    agent = DiscoveryAgent()
    result = agent.run(str(tmp_path))
    assert result["success"] is True
    assert len(result["pairs"]) == 1
    assert result["pairs"][0]["patient_id"] == "P001"
