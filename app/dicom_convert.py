"""DICOM 序列扫描与 NIfTI（.nii.gz）转换，基于 SimpleITK/GDCM。

递归识别任意文件夹结构：任何含 .dcm 的目录视为转换单元，
同一目录内按 SeriesInstanceUID 分组，每个序列各输出一个 .nii.gz。
"""
import logging
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Union

import SimpleITK as sitk

logger = logging.getLogger(__name__)

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


def convert_dicom_tree(input_root: Union[str, Path],
                       output_root: Union[str, Path],
                       progress_callback=None) -> dict:
    """把 input_root 下所有 DICOM 序列转换为 .nii.gz，输出镜像输入相对结构。

    单个序列失败只记录错误不中断；已存在的输出文件直接覆盖。
    progress_callback 可选，扫描完成后收到
    {"stage": "converting", "current": 0, "total": N}，之后每开始转换一个
    序列收到 {"stage": "converting", "current": i, "total": N,
    "patient_id": 输出文件名}；回调异常不中断转换。
    返回 {"total": n, "converted": [relpath...], "failed": [{...}]}。
    """
    input_root = Path(input_root)
    output_root = Path(output_root)

    def report(payload: dict) -> None:
        """向调用方上报进度；回调异常不应中断转换。"""
        if progress_callback is None:
            return
        try:
            progress_callback(payload)
        except Exception:
            logger.debug("progress_callback 调用失败", exc_info=True)

    series = scan_dicom_series(input_root)
    report({"stage": "converting", "current": 0, "total": len(series)})
    converted: List[str] = []
    failed: List[dict] = []
    reader = sitk.ImageSeriesReader()
    for idx, info in enumerate(series, start=1):
        src_dir = input_root if info.directory == "." else input_root / info.directory
        out_path = output_root / info.output_relpath
        report({
            "stage": "converting",
            "current": idx,
            "total": len(series),
            "patient_id": Path(info.output_relpath).name,
        })
        try:
            file_names = reader.GetGDCMSeriesFileNames(str(src_dir), info.series_id)
            reader.SetFileNames(file_names)
            image = reader.Execute()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            sitk.WriteImage(image, str(out_path))
            converted.append(info.output_relpath)
        except Exception as exc:
            failed.append({
                "series_id": info.series_id,
                "directory": info.directory,
                "error": str(exc),
            })
    return {"total": len(series), "converted": converted, "failed": failed}
