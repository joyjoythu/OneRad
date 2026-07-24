"""DICOM 序列扫描与 NIfTI（.nii.gz）转换，基于 SimpleITK/GDCM。

递归识别任意文件夹结构：任何含 .dcm 的目录视为转换单元，
同一目录内按 SeriesInstanceUID 分组，每个序列各输出一个 .nii.gz。
"""
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Union

import SimpleITK as sitk

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


@dataclass
class SeriesInfo:
    """一个待转换的 DICOM 序列。"""
    series_id: str        # GDCM SeriesID（SeriesInstanceUID）
    directory: str        # 相对输入根目录的目录路径，根目录本身为 "."
    description: str      # SeriesDescription，缺失时回退 "series{N}"
    num_slices: int
    output_relpath: str   # 相对输出根目录的 .nii.gz 路径

    def to_dict(self) -> dict:
        return asdict(self)


def _sanitize_filename(name: str) -> str:
    cleaned = _INVALID_CHARS.sub("_", name).strip().strip(".")
    cleaned = _WHITESPACE.sub("_", cleaned)
    return cleaned or "unnamed"


def _read_series_description(first_file: Path) -> str:
    reader = sitk.ImageFileReader()
    reader.SetFileName(str(first_file))
    try:
        reader.ReadImageInformation()
    except RuntimeError:
        return ""
    key = "0008|103e"  # Series Description
    if reader.HasMetaDataKey(key):
        return reader.GetMetaData(key).strip()
    return ""


def scan_dicom_series(root: Union[str, Path]) -> List[SeriesInfo]:
    """递归扫描 root，返回所有可转换的 DICOM 序列（按目录、SeriesID 排序）。"""
    root = Path(root)
    reader = sitk.ImageSeriesReader()
    found: List[SeriesInfo] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if not any(f.lower().endswith(".dcm") for f in filenames):
            continue
        series_ids = sorted(reader.GetGDCMSeriesIDs(dirpath) or [])
        if not series_ids:
            continue
        rel_dir = Path(dirpath).relative_to(root)
        dir_label = root.name if rel_dir == Path(".") else rel_dir.name
        used_names = set()
        for idx, sid in enumerate(series_ids, start=1):
            files = reader.GetGDCMSeriesFileNames(dirpath, sid)
            if not files:
                continue
            desc = _read_series_description(Path(files[0])) or f"series{idx}"
            stem = _sanitize_filename(f"{dir_label}_{desc}")
            if stem in used_names:
                n = 2
                while f"{stem}_{n}" in used_names:
                    n += 1
                stem = f"{stem}_{n}"
            used_names.add(stem)
            if rel_dir == Path("."):
                output_relpath = f"{stem}.nii.gz"
            else:
                output_relpath = str(rel_dir / f"{stem}.nii.gz")
            found.append(SeriesInfo(
                series_id=sid,
                directory="." if rel_dir == Path(".") else str(rel_dir),
                description=desc,
                num_slices=len(files),
                output_relpath=output_relpath,
            ))
    found.sort(key=lambda s: (s.directory, s.series_id))
    return found
