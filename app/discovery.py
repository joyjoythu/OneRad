import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import List, Tuple, Optional


SUPPORTED_EXTENSIONS = (".nii.gz", ".nii", ".nrrd", ".mha", ".mhd", ".dcm", ".img", ".hdr")
MASK_KEYWORDS = ("mask", "seg", "segmentation", "label", "roi", "gt", "annotation", "tumor")

MODALITY_KEYWORDS = {
    "CT": ["ct", "computed_tomography", "computedtomography"],
    "MRI": ["mr", "mri", "magnetic", "t1", "t2", "t1c", "t2flair", "dwi", "adc", "flair"],
    "PET": ["pet", "positron"],
}

# Sort mask keywords by descending length so longer keywords (e.g. "segmentation")
# are matched before their prefixes (e.g. "seg").
_MASK_KEYWORDS_PATTERN = "|".join(re.escape(kw) for kw in sorted(MASK_KEYWORDS, key=len, reverse=True))

# Collect modality tokens for the mask+modality suffix heuristic.
_MODALITY_TOKENS = sorted(
    {kw.upper() for keywords in MODALITY_KEYWORDS.values() for kw in keywords},
    key=len,
    reverse=True,
)
_MODALITY_PATTERN = "|".join(re.escape(tok) for tok in _MODALITY_TOKENS)


def get_base_name(fpath: Path) -> str:
    """Return the file name without extension, treating ``.nii.gz`` as a single extension."""
    name = fpath.name
    if name.lower().endswith(".nii.gz"):
        return name[:-7]
    return fpath.stem


def remove_mask_suffix(name: str) -> str:
    """Remove a trailing mask keyword and optional separator + trailing token.

    Examples:
        * ``P001_mask_T1`` → ``P001``
        * ``brain.mask.T1`` → ``brain``
        * ``P001_label`` → ``P001``
    """
    pattern = r"(?:^|[_\-\.])(?:" + _MASK_KEYWORDS_PATTERN + r")(?:[_\-\.][A-Za-z0-9]+)?$"
    return re.sub(pattern, "", name, flags=re.IGNORECASE)


def extract_patient_id(base_name: str, id_pattern: Optional[str] = None) -> str:
    """Extract a patient identifier from a file base name.

    The heuristic order is:
    1. Custom ``id_pattern`` if provided.
    2. A contiguous run of at least two digits.
    3. A letter prefix followed by digits (e.g. ``P001``).
    4. The cleaned base name, falling back to the original base name.
    """
    clean = remove_mask_suffix(base_name).strip("_-")
    if id_pattern:
        m = re.search(id_pattern, clean)
        if m:
            return m.group(0)
    num = re.search(r"\b\d{2,}\b", clean)
    if num:
        return num.group(0)
    alphanum = re.search(r"[A-Za-z]+[_\-]?\d+", clean)
    if alphanum:
        return alphanum.group(0)
    return clean or base_name


def infer_modality(base_name: str) -> str:
    """Infer the imaging modality from a file base name.

    Returns one of ``CT``, ``MRI``, ``PET``, or ``UNKNOWN``.
    """
    name = base_name.lower()
    for modality, keywords in MODALITY_KEYWORDS.items():
        for kw in keywords:
            pattern = r"(?:^|[_\-\.])" + re.escape(kw) + r"(?:$|[_\-\.])"
            if re.search(pattern, name):
                return modality
    return "UNKNOWN"


class DiscoveryAgent:
    """Scan a directory, classify images and masks, and pair them by patient ID."""

    def __init__(self, llm_client=None, id_pattern: Optional[str] = None, recursive: bool = True):
        """Initialize the DiscoveryAgent.

        Args:
            llm_client: Optional client for LLM-enhanced discovery.
            id_pattern: Optional custom regex for patient ID extraction.
            recursive: Whether to scan subdirectories recursively.
        """
        self.llm_client = llm_client
        self.id_pattern = id_pattern
        self.recursive = recursive

    def run(self, directory: str) -> dict:
        """Scan *directory* and return paired images/masks.

        The returned dict has keys ``success``, ``message``, ``pairs``,
        ``unpaired_images``, and ``unpaired_masks``.
        """
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            return {"success": False, "message": f"目录不存在: {directory}", "pairs": []}

        if self.id_pattern is not None:
            try:
                re.compile(self.id_pattern)
            except re.error as e:
                return {"success": False, "message": f"患者ID正则无效: {e}", "pairs": []}

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
        """Recursively collect supported files, skipping hidden/system directories."""
        skip_dirs = {".git", "__pycache__", "node_modules", ".venv"}
        files: List[Path] = []

        def recurse(current: Path) -> None:
            try:
                entries = list(current.iterdir())
            except (OSError, PermissionError):
                return
            for item in entries:
                if item.is_dir():
                    if item.name.startswith(".") or item.name in skip_dirs:
                        continue
                    if self.recursive:
                        recurse(item)
                elif item.is_file():
                    s = str(item).lower()
                    if s.endswith(".nii.gz"):
                        files.append(item)
                    elif any(s.endswith(ext) for ext in SUPPORTED_EXTENSIONS if ext != ".nii.gz"):
                        files.append(item)

        recurse(dir_path)
        return sorted(files)

    def _classify_files(self, files: List[Path]) -> Tuple[List[dict], List[dict]]:
        """Classify files into images and masks based on filename keywords."""
        images, masks = [], []
        for f in files:
            base = get_base_name(f)
            pid = extract_patient_id(base, self.id_pattern)
            modality = infer_modality(base)
            entry = {
                "file_path": str(f),
                "patient_id": pid,
                "modality": modality,
            }
            if self._is_mask_name(base):
                masks.append(entry)
            else:
                images.append(entry)
        return images, masks

    def _is_mask_name(self, name: str) -> bool:
        """Return True when *name* contains a mask keyword as a filename suffix.

        A keyword counts as a mask indicator when it is at the end of the base name
        (e.g. ``brain_mask``) or when it is followed by a known modality token
        (e.g. ``brain_mask_T1``). This avoids false positives such as
        ``tumor_volume`` where an anatomical word happens to be in the keyword list.
        """
        name_lower = name.lower()

        # Bare keyword suffix: brain_mask, brain.label, etc.
        if re.search(r"(?:^|[_\-\.])(?:" + _MASK_KEYWORDS_PATTERN + r")$", name_lower):
            return True

        # Keyword followed by a modality token: brain_mask_T1, brain.mask.T1, etc.
        if _MODALITY_PATTERN and re.search(
            r"(?:^|[_\-\.])(?:"
            + _MASK_KEYWORDS_PATTERN
            + r")[_\-\.](?:"
            + _MODALITY_PATTERN
            + r")$",
            name_lower,
        ):
            return True

        return False

    def _pair_images_masks(self, images: List[dict], masks: List[dict]):
        """Pair images with masks by patient ID.

        When a patient has multiple masks, the mask whose base name is most similar
        to the image base name is chosen. A single mask may be shared by multiple
        images when it is the only mask available for that patient.
        """
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
                img_base = get_base_name(Path(img["file_path"])).lower()
                best = None
                best_score = -1.0
                for m in candidates:
                    mask_base = get_base_name(Path(m["file_path"]))
                    mask_clean = remove_mask_suffix(mask_base).lower()
                    score = SequenceMatcher(None, img_base, mask_clean).ratio()
                    if score > best_score:
                        best_score = score
                        best = m
                chosen = best

            # When multiple masks exist, remove the chosen one to avoid reusing it.
            # Otherwise, keep the single mask so it can be shared by multiple images.
            if len(candidates) > 1:
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
