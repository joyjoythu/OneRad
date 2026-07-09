from pathlib import Path
from typing import Union, List, Dict, Any


class Sandbox:
    """Sandbox that restricts all paths to the project root directory."""

    def __init__(self, root: Union[str, Path]):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"Sandbox root must be an existing directory: {root}")

    def resolve(self, path: Union[str, Path], must_exist: bool = False) -> Path:
        """Resolve a path relative to the sandbox root and verify it stays inside."""
        p = Path(path)
        if p.is_absolute():
            target = p.resolve()
        else:
            target = (self.root / p).resolve()

        try:
            target.relative_to(self.root)
        except ValueError:
            raise ValueError(f"Path outside project sandbox: {path}")

        if must_exist and not target.exists():
            raise FileNotFoundError(f"Path does not exist: {path}")

        return target

    def is_within(self, path: Union[str, Path]) -> bool:
        """Return True if the path resolves inside the sandbox."""
        try:
            self.resolve(path)
            return True
        except ValueError:
            return False


ALLOWED_ACTIONS = {"move", "copy", "rename", "mkdir"}


def validate_plan(plan: List[Dict[str, Any]], sandbox: Sandbox) -> List[Dict[str, Any]]:
    """Validate an AI-generated file-operation plan."""
    if not isinstance(plan, list):
        raise ValueError("Plan must be a list")

    validated = []
    for idx, item in enumerate(plan):
        if not isinstance(item, dict):
            raise ValueError(f"Item {idx}: must be a dictionary")

        action = item.get("action")
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"Item {idx}: unsupported action '{action}'")

        source = item.get("source")
        target = item.get("target")

        if source is not None and not isinstance(source, (str, Path)):
            raise ValueError(f"Item {idx}: source/target must be a string or Path")
        if target is not None and not isinstance(target, (str, Path)):
            raise ValueError(f"Item {idx}: source/target must be a string or Path")

        overwrite = item.get("overwrite", False)
        if not isinstance(overwrite, bool):
            raise ValueError(f"Item {idx}: 'overwrite' must be a boolean")

        if action in {"move", "copy", "rename"}:
            if not source or not target:
                raise ValueError(f"Item {idx}: '{action}' requires source and target")
            sandbox.resolve(source)
            sandbox.resolve(target)
        elif action == "mkdir":
            if not target:
                raise ValueError(f"Item {idx}: 'mkdir' requires target")
            sandbox.resolve(target)

        validated.append({
            "action": action,
            "source": source,
            "target": target,
            "reason": item.get("reason", ""),
            "overwrite": overwrite,
        })
    return validated
