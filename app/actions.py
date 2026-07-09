import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from app.agent.safety import Sandbox, validate_plan, ALLOWED_ACTIONS


def execute_plan(plan: List[Dict[str, Any]], project_path: str) -> List[Dict[str, Any]]:
    sandbox = Sandbox(project_path)
    try:
        validated = validate_plan(plan, sandbox)
    except ValueError as e:
        return [{"success": False, "error": str(e)}]

    backup_dir = _make_backup_dir(project_path)
    results = []
    for item in validated:
        results.append(_execute_one(item, sandbox, backup_dir, project_path))
    return results


def _make_backup_dir(project_path: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(project_path) / ".onerad_backup" / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _backup_file(target: Path, backup_dir: Path, project_path: str) -> None:
    rel = target.relative_to(Path(project_path))
    dest = backup_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if target.is_dir():
        shutil.copytree(target, dest, dirs_exist_ok=True)
    else:
        shutil.copy2(target, dest)


def _execute_one(item: Dict[str, Any], sandbox: Sandbox, backup_dir: Path, project_path: str) -> Dict[str, Any]:
    action = item.get("action")
    if action not in ALLOWED_ACTIONS:
        return {"success": False, "error": f"Unsupported action: {action}", "item": item}

    try:
        if action == "mkdir":
            target = sandbox.resolve(item["target"])
            target.mkdir(parents=True, exist_ok=True)
            return {"success": True, "action": action, "target": str(target.relative_to(sandbox.root))}

        source = sandbox.resolve(item["source"], must_exist=True)
        target = sandbox.resolve(item["target"])

        if target.exists() and not item.get("overwrite"):
            if not (action == "move" and target.is_dir()):
                rel_target = target.relative_to(sandbox.root)
                return {"success": False, "error": f"Target exists: {rel_target}", "item": item}

        if target.exists():
            if action == "move" and target.is_dir():
                shutil.move(str(source), str(target))
                return {
                    "success": True,
                    "action": action,
                    "source": str(source.relative_to(sandbox.root)),
                    "target": str(target.relative_to(sandbox.root)),
                }
            _backup_file(target, backup_dir, project_path)
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

        target.parent.mkdir(parents=True, exist_ok=True)

        if action == "move":
            shutil.move(str(source), str(target))
        elif action == "copy":
            if source.is_dir():
                shutil.copytree(str(source), str(target))
            else:
                shutil.copy2(str(source), str(target))
        elif action == "rename":
            source.rename(target)

        return {
            "success": True,
            "action": action,
            "source": str(source.relative_to(sandbox.root)),
            "target": str(target.relative_to(sandbox.root)),
        }
    except (ValueError, FileNotFoundError, OSError, KeyError) as e:
        return {"success": False, "error": str(e), "item": item}
