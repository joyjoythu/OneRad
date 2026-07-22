"""Application-wide settings persisted outside individual projects."""

from __future__ import annotations

import os
import stat
import threading
from pathlib import Path
from typing import Any, Dict, Iterable

import yaml


def _default_settings_path() -> Path:
    data_dir = Path(os.environ.get("ONERAD_DATA_DIR", Path.home() / ".onerad"))
    return data_dir / "settings.yaml"


class GeneralSettingsStore:
    """Store general OneRad settings in a small UTF-8 YAML file."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else _default_settings_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _raw_data(self) -> Dict[str, Any]:
        """Read the full YAML document; returns {} on any failure."""
        with self._lock:
            if not self.path.exists():
                return {}
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    return yaml.safe_load(handle) or {}
            except (OSError, yaml.YAMLError):
                return {}

    def load(self) -> Dict[str, str]:
        data = self._raw_data()
        deepseek = data.get("deepseek", {})
        if not isinstance(deepseek, dict):
            deepseek = {}
        api_key = deepseek.get("api_key", "")
        features = data.get("features", {})
        if not isinstance(features, dict):
            features = {}
        memory_enabled = features.get("memory_enabled", True)
        return {
            "api_key": api_key if isinstance(api_key, str) else "",
            "memory_enabled": bool(memory_enabled),
        }

    def save(self, api_key: str, memory_enabled: bool | None = None) -> Dict[str, Any]:
        data = self._raw_data()
        data.setdefault("deepseek", {})["api_key"] = api_key.strip()
        if memory_enabled is not None:
            data.setdefault("features", {})["memory_enabled"] = memory_enabled
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with self._lock:
            with temp_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
            temp_path.replace(self.path)
            try:
                self.path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
        return self.public_settings()

    def resolve_api_key(self) -> str:
        saved = self.load()["api_key"].strip()
        return saved or os.getenv("DEEPSEEK_API_KEY", "").strip()

    def is_memory_enabled(self) -> bool:
        """读取记忆功能开关（缺省为 True）。"""
        return self.load().get("memory_enabled", True)

    def public_settings(self) -> Dict[str, Any]:
        settings = self.load()
        saved = settings["api_key"]
        environment_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        source = "settings" if saved.strip() else "environment" if environment_key else "none"
        return {
            "api_key": saved,
            "api_key_configured": bool(saved.strip() or environment_key),
            "api_key_source": source,
            "memory_enabled": settings["memory_enabled"],
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
