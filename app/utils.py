from typing import List


def parse_covariates(covs: str) -> List[str]:
    """Parse a comma-separated covariates string into a cleaned list."""
    return [c.strip() for c in (covs or "").split(",") if c.strip()]
