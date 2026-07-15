import re
from pathlib import Path
from typing import Dict, Any, List, Optional

MASK_SUFFIXES = ("_mask", "_seg", "_label", "_roi")


def _stem(path: Path) -> str:
    """Return the file stem treating ``.nii.gz`` as a single extension."""
    name = path.name
    if name.lower().endswith(".nii.gz"):
        return name[:-7]
    return path.stem


def _tokens(name: str) -> List[str]:
    """Split a base name into non-empty tokens on ``_`` or ``-``."""
    return [token for token in re.split(r"[_\-]", name) if token]


def _scan_nii_gz(directory: Path) -> List[Path]:
    """Recursively collect ``.nii.gz`` files under *directory*."""
    if not directory.exists():
        return []
    return sorted(p for p in directory.rglob("*.nii.gz") if p.is_file())


def _patient_id(image_rel: Path) -> str:
    """Infer patient_id from the first directory component or filename token."""
    parts = image_rel.parts
    if len(parts) > 1:
        return parts[0]
    stem = _stem(image_rel)
    if "_" in stem:
        first_token = stem.split("_", 1)[0]
        if first_token:
            return first_token
    tokens = _tokens(stem)
    return tokens[0] if tokens else stem


def _sequence(image_path: Path) -> str:
    """Infer sequence from the image filename stem."""
    return _stem(image_path)


def _suffix_match(image_base: str, mask_base: str) -> bool:
    """Return True when the mask base equals the image base after stripping a mask suffix."""
    for suffix in MASK_SUFFIXES:
        if mask_base.lower().endswith(suffix):
            return mask_base[: -len(suffix)] == image_base
    return False


def _token_match(image_base: str, mask_base: str) -> bool:
    """Return True when image and mask share at least one non-empty token."""
    return bool(set(_tokens(image_base)) & set(_tokens(mask_base)))


def discover_pairs(project_path: str) -> Dict[str, Any]:
    """Discover image/mask pairs under *project_path*.

    Scans ``images/`` and ``masks/`` recursively for ``.nii.gz`` files and
    matches them with high, medium or low confidence.

    Returns a dict with keys ``success``, ``images_found``, ``masks_found``,
    ``pairs`` (with ``high``, ``medium``, ``low``), ``unmatched_images`` and
    ``unmatched_masks``.
    """
    project = Path(project_path).resolve()
    if not project.exists():
        return {"success": False, "message": f"project path does not exist: {project}"}
    if not project.is_dir():
        return {"success": False, "message": f"project path is not a directory: {project}"}
    images_dir = project / "images"
    masks_dir = project / "masks"

    if not images_dir.exists():
        return {"success": False, "message": f"images directory not found: {images_dir}"}
    if not masks_dir.exists():
        return {"success": False, "message": f"masks directory not found: {masks_dir}"}

    image_paths = _scan_nii_gz(images_dir)
    mask_paths = _scan_nii_gz(masks_dir)

    high_pairs: List[Dict[str, Any]] = []
    medium_pairs: List[Dict[str, Any]] = []
    low_pairs: List[Dict[str, Any]] = []
    unmatched_images: List[str] = []

    available_masks = {m: _stem(m) for m in mask_paths}
    remaining_images = list(image_paths)

    def _rel_to_project(path: Path) -> str:
        return str(path.relative_to(project).as_posix())

    # High confidence: identical relative path under images/ and masks/.
    for image_path in image_paths:
        image_rel = image_path.relative_to(images_dir)
        expected_mask = masks_dir / image_rel
        if expected_mask in available_masks:
            mask_path = expected_mask
            available_masks.pop(mask_path)
            remaining_images.remove(image_path)
            high_pairs.append({
                "patient_id": _patient_id(image_rel),
                "sequence": _sequence(image_path),
                "image_path": _rel_to_project(image_path),
                "mask_path": _rel_to_project(mask_path),
            })

    # Medium confidence: suffix stripping or unique token intersection.
    for image_path in remaining_images[:]:
        image_rel = image_path.relative_to(images_dir)
        image_base = _stem(image_path)

        suffix_candidates: List[Path] = []
        token_candidates: List[Path] = []

        for mask_path, mask_base in available_masks.items():
            if _suffix_match(image_base, mask_base):
                suffix_candidates.append(mask_path)
            elif _token_match(image_base, mask_base):
                token_candidates.append(mask_path)

        chosen: Optional[Path] = None
        if len(suffix_candidates) == 1:
            chosen = suffix_candidates[0]
        elif not suffix_candidates and len(token_candidates) == 1:
            chosen = token_candidates[0]

        if chosen is not None:
            available_masks.pop(chosen)
            remaining_images.remove(image_path)
            medium_pairs.append({
                "patient_id": _patient_id(image_rel),
                "sequence": _sequence(image_path),
                "image_path": _rel_to_project(image_path),
                "mask_path": _rel_to_project(chosen),
            })

    # Low confidence: remaining images get only their ambiguous plausible
    # candidates (masks that still look like a medium-confidence match),
    # not every leftover mask.
    for image_path in remaining_images[:]:
        image_rel = image_path.relative_to(images_dir)
        image_base = _stem(image_path)

        suffix_candidates = [
            mask_path for mask_path in available_masks
            if _suffix_match(image_base, available_masks[mask_path])
        ]
        token_candidates = [
            mask_path for mask_path in available_masks
            if mask_path not in suffix_candidates
            and _token_match(image_base, available_masks[mask_path])
        ]

        if suffix_candidates:
            candidates = suffix_candidates
        elif token_candidates:
            candidates = token_candidates
        else:
            candidates = []

        remaining_images.remove(image_path)
        if candidates:
            low_pairs.append({
                "patient_id": _patient_id(image_rel),
                "sequence": _sequence(image_path),
                "image_path": _rel_to_project(image_path),
                "candidates": [_rel_to_project(mask_path) for mask_path in candidates],
            })
        else:
            unmatched_images.append(_rel_to_project(image_path))

    return {
        "success": True,
        "images_found": len(image_paths),
        "masks_found": len(mask_paths),
        "pairs": {
            "high": high_pairs,
            "medium": medium_pairs,
            "low": low_pairs,
        },
        "unmatched_images": unmatched_images,
        "unmatched_masks": [_rel_to_project(mask_path) for mask_path in available_masks],
    }
