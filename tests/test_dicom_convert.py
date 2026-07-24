"""dcm → nii.gz 转换核心逻辑的测试。合成 DICOM 由 SimpleITK 生成。"""
import json
from pathlib import Path

import SimpleITK as sitk

from app.dicom_convert import scan_dicom_series


def _write_dicom_series(dir_path: Path, series_uid: str, description: str = "",
                        n_slices: int = 3) -> None:
    """在 dir_path 下生成一个最小 DICOM 序列（8x8 x n_slices）。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    writer = sitk.ImageFileWriter()
    writer.KeepOriginalImageUIDOn()
    for i in range(n_slices):
        img = sitk.Image(8, 8, sitk.sitkInt16)
        img.SetMetaData("0008|0008", "DERIVED\\SECONDARY")   # Image Type
        img.SetMetaData("0008|0021", "20260101")             # Series Date
        img.SetMetaData("0008|0031", "120000")               # Series Time
        img.SetMetaData("0020|000d", "1.2.3.4.1")            # Study Instance UID
        img.SetMetaData("0020|000e", series_uid)             # Series Instance UID
        img.SetMetaData("0020|0032", f"0\\0\\{i}")           # Image Position Patient
        img.SetMetaData("0020|0013", str(i))                 # Instance Number
        if description:
            img.SetMetaData("0008|103e", description)        # Series Description
        # 文件名带上序列 UID 尾号，避免同目录多序列相互覆盖
        writer.SetFileName(str(dir_path / f"slice_{series_uid.split('.')[-1]}_{i:03d}.dcm"))
        writer.Execute(img)


def test_scan_flat_directory_single_series(tmp_path):
    _write_dicom_series(tmp_path, "1.2.3.4.100", "T1", n_slices=4)
    series = scan_dicom_series(tmp_path)
    assert len(series) == 1
    info = series[0]
    assert info.series_id == "1.2.3.4.100"
    assert info.directory == "."
    assert info.description == "T1"
    assert info.num_slices == 4
    assert Path(info.output_relpath) == Path(f"{tmp_path.name}_T1.nii.gz")


def test_scan_nested_directory_mirrors_relpath(tmp_path):
    _write_dicom_series(tmp_path / "patient01" / "seq", "1.2.3.4.100", "T2")
    series = scan_dicom_series(tmp_path)
    assert len(series) == 1
    info = series[0]
    assert Path(info.directory) == Path("patient01/seq")
    assert Path(info.output_relpath) == Path("patient01/seq/seq_T2.nii.gz")


def test_scan_multiple_series_in_one_directory(tmp_path):
    d = tmp_path / "seq"
    _write_dicom_series(d, "1.2.3.4.100", "T1", n_slices=2)
    _write_dicom_series(d, "1.2.3.4.200", "T2", n_slices=5)
    series = scan_dicom_series(d)
    assert len(series) == 2
    by_desc = {s.description: s for s in series}
    assert by_desc["T1"].num_slices == 2
    assert by_desc["T2"].num_slices == 5
    stems = {Path(s.output_relpath).name for s in series}
    assert stems == {"seq_T1.nii.gz", "seq_T2.nii.gz"}


def test_scan_missing_description_falls_back_to_series_n(tmp_path):
    _write_dicom_series(tmp_path / "seq", "1.2.3.4.100", description="")
    series = scan_dicom_series(tmp_path)
    assert len(series) == 1
    assert series[0].description == "series1"
    assert Path(series[0].output_relpath).name == "seq_series1.nii.gz"


def test_scan_duplicate_descriptions_get_unique_names(tmp_path):
    d = tmp_path / "seq"
    _write_dicom_series(d, "1.2.3.4.100", "T1", n_slices=2)
    _write_dicom_series(d, "1.2.3.4.200", "T1", n_slices=3)
    stems = sorted(Path(s.output_relpath).name for s in scan_dicom_series(d))
    assert stems == ["seq_T1.nii.gz", "seq_T1_2.nii.gz"]


def test_scan_empty_directory_returns_empty(tmp_path):
    (tmp_path / "empty").mkdir()
    assert scan_dicom_series(tmp_path) == []
