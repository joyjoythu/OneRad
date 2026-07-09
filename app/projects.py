import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


DEFAULT_DB_DIR = Path.home() / ".onerad"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "projects.db"
DEFAULT_PARAMS_TEMPLATE = (
    Path(__file__).resolve().parent.parent / "config" / "Params_labels.yaml"
)


class ProjectStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    path TEXT NOT NULL UNIQUE,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    image_dir TEXT,
                    clinical_path TEXT,
                    output_dir TEXT,
                    modality TEXT,
                    covariates TEXT,
                    model TEXT,
                    status TEXT NOT NULL,
                    log_summary TEXT,
                    report_path TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                )
                """
            )
            conn.commit()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sse_events (
                    scope TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    event_id INTEGER NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (scope, scope_id, event_id)
                )
                """
            )
        finally:
            conn.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_project(self, name: str, path: str, description: str = "") -> Dict[str, Any]:
        project_path = Path(path).resolve()
        if not project_path.exists():
            project_path.mkdir(parents=True, exist_ok=True)
        if not project_path.is_dir():
            raise ValueError(f"项目路径必须是目录: {path}")

        project_id = str(uuid.uuid4())
        now = self._now()
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "INSERT INTO projects (id, name, path, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, name, str(project_path), description, now, now),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"项目名或路径已存在: {e}")
        finally:
            conn.close()

        project_yaml_path = project_path / "project.yaml"
        params_yaml_path = project_path / "Params_labels.yaml"

        project_data = {
            "name": name,
            "description": description,
            "path": str(project_path),
            "created_at": now,
            "updated_at": now,
            "analysis": {
                "image_dir": "",
                "clinical_path": "",
                "output_dir": "./outputs",
                "modality": "auto",
                "covariates": "",
                "model": "deepseek-v4-pro",
                "api_key": "",
            },
        }
        with open(project_yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(project_data, f, allow_unicode=True, sort_keys=False)

        if DEFAULT_PARAMS_TEMPLATE.exists():
            shutil.copy(DEFAULT_PARAMS_TEMPLATE, params_yaml_path)
        else:
            with open(params_yaml_path, "w", encoding="utf-8") as f:
                yaml.safe_dump({}, f)

        return {
            "id": project_id,
            "name": name,
            "path": str(project_path),
            "description": description,
            "created_at": now,
            "updated_at": now,
        }

    def list_projects(self) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, path, description, created_at, updated_at FROM projects ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def load_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, name, path, description, created_at, updated_at FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        project = dict(row)
        project_path = Path(project["path"])
        yaml_path = project_path / "project.yaml"
        if yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as f:
                try:
                    data = yaml.safe_load(f) or {}
                except yaml.YAMLError:
                    data = {}
            project["analysis"] = data.get("analysis", self._default_analysis())
        else:
            project["analysis"] = self._default_analysis()
        return project

    def _default_analysis(self) -> Dict[str, Any]:
        return {
            "image_dir": "",
            "clinical_path": "",
            "output_dir": "./outputs",
            "modality": "auto",
            "covariates": "",
            "model": "deepseek-v4-pro",
            "api_key": "",
        }

    def delete_project(self, project_id: str) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
        finally:
            conn.close()

    def save_project_config(self, project_id: str, analysis_config: Dict[str, Any]) -> Dict[str, Any]:
        project = self.load_project(project_id)
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")

        now = self._now()
        project_path = Path(project["path"])
        yaml_path = project_path / "project.yaml"

        project_data = {
            "name": project["name"],
            "description": project.get("description", ""),
            "path": str(project_path),
            "created_at": project["created_at"],
            "updated_at": now,
            "analysis": {
                "image_dir": analysis_config.get("image_dir", ""),
                "clinical_path": analysis_config.get("clinical_path", ""),
                "output_dir": analysis_config.get("output_dir", "./outputs"),
                "modality": analysis_config.get("modality", "auto"),
                "covariates": analysis_config.get("covariates", ""),
                "model": analysis_config.get("model", "deepseek-v4-pro"),
                "api_key": analysis_config.get("api_key", ""),
            },
        }
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(project_data, f, allow_unicode=True, sort_keys=False)

        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?",
                (now, project_id),
            )
            conn.commit()
        finally:
            conn.close()

        return self.load_project(project_id)

    def record_run_start(self, project_id: str, analysis_config: Dict[str, Any]) -> str:
        run_id = str(uuid.uuid4())
        now = self._now()
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """
                INSERT INTO runs (id, project_id, image_dir, clinical_path, output_dir,
                                  modality, covariates, model, status, log_summary,
                                  report_path, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    project_id,
                    analysis_config.get("image_dir", ""),
                    analysis_config.get("clinical_path", ""),
                    analysis_config.get("output_dir", ""),
                    analysis_config.get("modality", "auto"),
                    analysis_config.get("covariates", ""),
                    analysis_config.get("model", "deepseek-v4-pro"),
                    "running",
                    "",
                    "",
                    now,
                    None,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        return run_id

    def record_run_end(
        self,
        run_id: str,
        status: str,
        log_summary: str = "",
        report_path: str = "",
    ) -> None:
        now = self._now()
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "UPDATE runs SET status = ?, log_summary = ?, report_path = ?, finished_at = ? WHERE id = ?",
                (status, log_summary, report_path, now, run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def list_runs(self, project_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM runs WHERE project_id = ? ORDER BY started_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def record_sse_event(self, scope: str, scope_id: str, event_id: int, data: str) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO sse_events (scope, scope_id, event_id, data, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (scope, scope_id, event_id, data, self._now()),
            )
            conn.commit()
        finally:
            conn.close()

    def list_sse_events(
        self, scope: str, scope_id: str, after_event_id: int = 0, limit: int = 200
    ) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT scope, scope_id, event_id, data, created_at
                FROM sse_events
                WHERE scope = ? AND scope_id = ? AND event_id > ?
                ORDER BY event_id ASC
                LIMIT ?
                """,
                (scope, scope_id, after_event_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def delete_sse_events(self, scope: str, scope_id: str) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                "DELETE FROM sse_events WHERE scope = ? AND scope_id = ?",
                (scope, scope_id),
            )
            conn.commit()
        finally:
            conn.close()

    def has_running_run(self, project_id: str) -> bool:
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, started_at FROM runs WHERE project_id = ? AND status = ?",
                (project_id, "running"),
            ).fetchall()
            now = datetime.now(timezone.utc)
            stale_run_ids = []
            active = False
            for row in rows:
                started_at = datetime.fromisoformat(row["started_at"])
                if now - started_at > timedelta(hours=24):
                    stale_run_ids.append(row["id"])
                else:
                    active = True
            if stale_run_ids:
                placeholders = ",".join("?" * len(stale_run_ids))
                conn.execute(
                    f"UPDATE runs SET status = 'failed' WHERE id IN ({placeholders})",
                    stale_run_ids,
                )
                conn.commit()
            return active
        finally:
            conn.close()
