"""读取队列影像的像素间距(spacing)分布,为重采样参数确认提供依据。"""

import statistics
from pathlib import Path
from typing import Dict, List, Optional

import SimpleITK as sitk

_CASES_DETAIL_LIMIT = 50


def inspect_spacing(project_path: str, image_paths: Optional[List[str]] = None) -> Dict:
    """统计影像 spacing 分布并给出 resampledPixelSpacing 建议值。

    image_paths 为 None 时扫描项目 images/ 目录下的 .nii.gz;
    传入时必须是项目内的绝对路径(沙箱校验由调用方负责)。
    只读 NIfTI 头信息,不加载像素数据。
    """
    root = Path(project_path)
    if image_paths is None:
        images_dir = root / "images"
        if not images_dir.is_dir():
            return {"success": False, "error": "影像目录不存在: images/"}
        paths = sorted(images_dir.rglob("*.nii.gz"))
    else:
        paths = [Path(p) for p in image_paths]
    if not paths:
        return {"success": False, "error": "未找到任何 .nii.gz 影像"}

    cases = []
    failed = []
    for p in paths:
        rel = _relative_display(root, p)
        try:
            reader = sitk.ImageFileReader()
            reader.SetFileName(str(p))
            reader.ReadImageInformation()
            spacing = tuple(float(s) for s in reader.GetSpacing())
            if len(spacing) != 3:
                raise ValueError(f"非 3D 影像(维度={len(spacing)})")
            cases.append({"path": rel, "spacing": [round(s, 6) for s in spacing]})
        except Exception as e:
            failed.append({"path": rel, "error": str(e)})

    if not cases:
        return {"success": False, "error": "没有可读取的影像", "failed": failed}

    axes = list(zip(*(c["spacing"] for c in cases)))
    summary = {
        "axis_labels": ["x", "y", "z"],
        "median": [round(statistics.median(a), 4) for a in axes],
        "min": [round(min(a), 4) for a in axes],
        "max": [round(max(a), 4) for a in axes],
        "n_distinct": len({tuple(c["spacing"]) for c in cases}),
    }
    result = {
        "success": True,
        "n_cases": len(cases),
        "summary": summary,
        "suggested_spacing": summary["median"],
        "failed": failed,
    }
    if len(cases) <= _CASES_DETAIL_LIMIT:
        result["cases"] = cases
    else:
        result["cases_truncated"] = True
    return result


def _relative_display(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(p)
