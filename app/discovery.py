import os
import re
from pathlib import Path
from typing import List, Tuple, Optional


SUPPORTED_EXTENSIONS = (".nii.gz", ".nii", ".nrrd", ".mha", ".mhd", ".dcm", ".img", ".hdr")
MASK_KEYWORDS = ("mask", "seg", "segmentation", "label", "roi", "gt", "annotation", "tumor")


def get_base_name(fpath: Path) -> str:
    name = fpath.name
    if name.lower().endswith(".nii.gz"):
        return name[:-7]
    return fpath.stem


def remove_mask_suffix(name: str) -> str:
    pattern = r'[_\-\.](mask|seg|segmentation|label|roi|gt|annotation|tumor)$'
    return re.sub(pattern, '', name, flags=re.IGNORECASE)


def extract_patient_id(base_name: str, id_pattern: Optional[str] = None) -> str:
    clean = remove_mask_suffix(base_name).strip('_-')
    if id_pattern:
        m = re.search(id_pattern, clean)
        if m:
            return m.group(0)
    num = re.search(r'\b\d{2,}\b', clean)
    if num:
        return num.group(0)
    alphanum = re.search(r'[A-Za-z]+[_\-]?\d+', clean)
    if alphanum:
        return alphanum.group(0)
    return clean or base_name


def infer_modality(base_name: str) -> str:
    name = base_name.lower()
    if any(kw in name for kw in ["ct", "computed"]):
        return "CT"
    if any(kw in name for kw in ["mr", "mri", "t1", "t2", "dwi", "flair", "adc"]):
        return "MRI"
    if "pet" in name:
        return "PET"
    return "UNKNOWN"


class DiscoveryAgent:
    def __init__(self, llm_client=None, id_pattern: Optional[str] = None, recursive: bool = True):
        self.llm_client = llm_client
        self.id_pattern = id_pattern
        self.recursive = recursive

    def run(self, directory: str) -> dict:
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            return {"success": False, "message": f"目录不存在: {directory}", "pairs": []}

        files = self._scan_files(dir_path)
        if not files:
            return {"success": False, "message": "未找到支持的影像文件", "pairs": []}

        images, masks = self._classify_files(files)
        if not images:
            return {"success": False, "message": "未找到 Image 文件", "pairs": []}

        pairs, unpaired_images, unpaired_masks = self._pair_images_masks(images, masks)

        return {
            "success": True,
            "message": f"发现 {len(pairs)} 对配对",
            "pairs": pairs,
            "unpaired_images": unpaired_images,
            "unpaired_masks": unpaired_masks,
        }

    def _scan_files(self, dir_path: Path) -> List[Path]:
        iterator = dir_path.rglob("*") if self.recursive else dir_path.iterdir()
        files = []
        for f in iterator:
            if not f.is_file():
                continue
            s = str(f).lower()
            if s.endswith(".nii.gz"):
                files.append(f)
            elif any(s.endswith(ext) for ext in SUPPORTED_EXTENSIONS if ext != ".nii.gz"):
                files.append(f)
        return sorted(files)

    def _classify_files(self, files: List[Path]) -> Tuple[List[dict], List[dict]]:
        images, masks = [], []
        for f in files:
            base = get_base_name(f)
            name_lower = base.lower()
            is_mask = any(kw in name_lower for kw in MASK_KEYWORDS)
            pid = extract_patient_id(base, self.id_pattern)
            modality = infer_modality(base)
            entry = {
                "file_path": str(f),
                "patient_id": pid,
                "modality": modality,
            }
            if is_mask:
                masks.append(entry)
            else:
                images.append(entry)
        return images, masks

    def _pair_images_masks(self, images: List[dict], masks: List[dict]):
        from difflib import SequenceMatcher
        mask_map = {}
        for m in masks:
            mask_map.setdefault(m["patient_id"], []).append(m)

        pairs = []
        used_image_indices = set()

        for idx, img in enumerate(images):
            pid = img["patient_id"]
            candidates = mask_map.get(pid, [])
            if not candidates:
                continue

            if len(candidates) == 1:
                chosen = candidates[0]
            else:
                best = None
                best_score = -1
                for m in candidates:
                    score = SequenceMatcher(None, get_base_name(Path(img["file_path"])).lower(),
                                            get_base_name(Path(m["file_path"])).lower()).ratio()
                    if score > best_score:
                        best_score = score
                        best = m
                chosen = best

            mask_map[pid].remove(chosen)
            used_image_indices.add(idx)
            pairs.append({
                "patient_id": pid,
                "image_path": img["file_path"],
                "mask_path": chosen["file_path"],
                "modality": img["modality"],
            })

        unpaired_images = [img["file_path"] for i, img in enumerate(images) if i not in used_image_indices]
        unpaired_masks = [m["file_path"] for lst in mask_map.values() for m in lst]
        return pairs, unpaired_images, unpaired_masks
