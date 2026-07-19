"""Application-wide settings persisted outside individual projects."""

from __future__ import annotations

import os
import stat
import threading
from pathlib import Path
from typing import Any, Dict, Iterable

import yaml


class GeneralSettingsStore:
    """Store general OneRad settings in a small UTF-8 YAML file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def load(self) -> Dict[str, str]:
        with self._lock:
            if not self.path.exists():
                return {"api_key": ""}
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    data = yaml.safe_load(handle) or {}
            except (OSError, yaml.YAMLError):
                return {"api_key": ""}

        deepseek = data.get("deepseek", {})
        if not isinstance(deepseek, dict):
            deepseek = {}
        api_key = deepseek.get("api_key", "")
        return {"api_key": api_key if isinstance(api_key, str) else ""}

    def save(self, api_key: str) -> Dict[str, Any]:
        payload = {"deepseek": {"api_key": api_key.strip()}}
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with self._lock:
            with temp_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
            temp_path.replace(self.path)
            try:
                self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                # Windows ACLs and some mounted filesystems may ignore POSIX modes.
                pass
        return self.public_settings()

    def resolve_api_key(self) -> str:
        saved = self.load()["api_key"].strip()
        return saved or os.getenv("DEEPSEEK_API_KEY", "").strip()

    def public_settings(self) -> Dict[str, Any]:
        saved = self.load()["api_key"]
        environment_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        source = "settings" if saved.strip() else "environment" if environment_key else "none"
        return {
            "api_key": saved,
            "api_key_configured": bool(saved.strip() or environment_key),
            "api_key_source": source,
        }

    def migrate_legacy_project_key(self, projects: Iterable[Dict[str, Any]]) -> bool:
        """Copy the first legacy project key when no general key exists yet."""
        if self.resolve_api_key():
            return False
        for project in projects:
            analysis = project.get("analysis", {})
            if not isinstance(analysis, dict):
                continue
            api_key = analysis.get("api_key", "")
            if isinstance(api_key, str) and api_key.strip():
                self.save(api_key)
                return True
        return False
