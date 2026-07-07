from typing import List, Optional, Tuple


def parse_covariates(covs: str) -> List[str]:
    """Parse a comma-separated covariates string into a cleaned list."""
    return [c.strip() for c in (covs or "").split(",") if c.strip()]


def parse_float_tuple(value: str, expected_length: int = 3) -> Optional[Tuple[float, ...]]:
    """Parse a comma-separated float string into a tuple.

    Returns ``None`` for empty/whitespace input. Raises ``ValueError`` when
    the string cannot be parsed or does not contain exactly ``expected_length``
    values.
    """
    if not value or not value.strip():
        return None
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != expected_length:
        raise ValueError(f"需要 {expected_length} 个数值, 得到 {len(parts)}: {value}")
    return tuple(float(p) for p in parts)
