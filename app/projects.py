import concurrent.futures
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.constants import DEEPSEEK_MODEL


DEFAULT_DB_DIR = Path.home() / ".onerad"
DEFAULT_DB_PATH = DEFAULT_DB_DIR / "projects.db"
DEFAULT_PARAMS_TEMPLATE = (
    Path(__file__).resolve().parent.parent / "config" / "Params_labels.yaml"
)

# 带超时读取项目配置专用的小线程池。线程若因不可达路径（如断开的网络盘）
# 阻塞会滞留到系统调用返回，但最多占满 worker 数，不会再耗尽 API 线程池。
# 滞留的 worker 是非守护线程，进程退出时需等待其系统调用返回，会额外拖慢退出。
_CONFIG_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)
_CONFIG_READ_TIMEOUT = 2.0  # 秒


class ProjectStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = self._connect()
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT,
                    llm_model TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_threads_project_updated "
                "ON threads(project_id, updated_at DESC)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    fact TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memories_project "
                "ON memories(project_id, created_at DESC)"
            )
        finally:
            conn.close()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def create_project(self, name: str, path: str, description: str = "") -> Dict[str, Any]:
        project_path = Path(path).resolve()
        if not project_path.exists():
            project_path.mkdir(parents=True, exist_ok=True)
        if not project_path.is_dir():
            raise ValueError(f"项目路径必须是目录: {path}")

        project_id = str(uuid.uuid4())
        now = self._now()
        conn = self._connect()
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
                "model": "logistic",
                "analysis_model": "logistic",
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
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            # 按最新对话活动排序：有对话的项目按 MAX(threads.updated_at)，
            # 无对话的回退到 projects.updated_at。
            rows = conn.execute(
                """
                SELECT p.id, p.name, p.path, p.description, p.created_at, p.updated_at
                FROM projects p
                LEFT JOIN threads t ON t.project_id = p.id
                GROUP BY p.id
                ORDER BY COALESCE(MAX(t.updated_at), p.updated_at) DESC
                """
            ).fetchall()
            return [self.load_project(row["id"]) for row in rows]
        finally:
            conn.close()

    def load_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
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
        project["analysis"] = self._load_analysis(Path(project["path"]))
        return project

    def _load_analysis(self, project_path: Path) -> Dict[str, Any]:
        """带超时读取项目配置；路径不可达或读取失败时降级为默认配置。

        网络盘等不可达路径的文件访问会阻塞数十秒，逐个项目串行读取会拖垮
        整个列表接口（API 线程池被占满）。超时后返回默认配置保证接口有界。
        网络盘只是首次访问缓慢（超过超时时间）时同样会返回默认配置——
        配置会在驱动器恢复后的下次读取自动生效。
        """
        future = _CONFIG_EXECUTOR.submit(self._read_analysis_file, project_path)
        try:
            return future.result(timeout=_CONFIG_READ_TIMEOUT)
        except (concurrent.futures.TimeoutError, OSError):
            future.cancel()  # 丢弃尚未开始的任务，防止队列在无响应路径上无限堆积
            return self._default_analysis()

    def _read_analysis_file(self, project_path: Path) -> Dict[str, Any]:
        yaml_path = project_path / "project.yaml"
        if yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as f:
                try:
                    data = yaml.safe_load(f) or {}
                except yaml.YAMLError:
                    data = {}
            return data.get("analysis", self._default_analysis())
        return self._default_analysis()

    def _default_analysis(self) -> Dict[str, Any]:
        return {
            "image_dir": "",
            "clinical_path": "",
            "output_dir": "./outputs",
            "modality": "auto",
            "covariates": "",
            "model": "logistic",
            "analysis_model": "logistic",
        }

    def delete_project(self, project_id: str) -> None:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT id FROM threads WHERE project_id = ?", (project_id,)
            ).fetchall()
            for (thread_id,) in rows:
                conn.execute(
                    "DELETE FROM sse_events WHERE scope = ? AND scope_id = ?",
                    ("agent", thread_id),
                )
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
        finally:
            conn.close()

    def record_thread(
        self,
        project_id: str,
        thread_id: str,
        title: Optional[str],
        _legacy_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = self._now()
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO threads (id, project_id, title, llm_model, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (thread_id, project_id, title or "", DEEPSEEK_MODEL, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_thread_meta(thread_id)

    def list_threads(self, project_id: str) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, project_id, title, llm_model, created_at, updated_at
                FROM threads WHERE project_id = ? ORDER BY updated_at DESC
                """,
                (project_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_thread_meta(self, thread_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, project_id, title, llm_model, created_at, updated_at
                FROM threads WHERE id = ?
                """,
                (thread_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def update_thread_title(self, thread_id: str, title: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE threads SET title = ?, updated_at = ? WHERE id = ?",
                (title, self._now(), thread_id),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get_thread_meta(thread_id)

    def update_project_name(self, project_id: str, name: str) -> Dict[str, Any]:
        now = self._now()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
                (name, now, project_id),
            )
            conn.commit()
        except sqlite3.IntegrityError as e:
            raise ValueError(f"项目名已存在: {e}")
        finally:
            conn.close()
        project = self.load_project(project_id)
        if project is None:
            raise ValueError(f"项目不存在: {project_id}")
        return project

    def update_thread_timestamp(self, thread_id: str) -> None:
        now = self._now()
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id)
            )
            conn.commit()
        finally:
            conn.close()

    # ── memories ────────────────────────────────────────────────────────

    def add_memories(self, project_id: str, memories: List[Dict[str, str]]) -> int:
        """Persist extracted facts; returns count of newly inserted rows.

        Each dict must contain ``category`` and ``fact``.  Duplicate facts
        (same project + category + fact text) are silently skipped.
        """
        if not memories:
            return 0
        now = self._now()
        conn = self._connect()
        inserted = 0
        try:
            for m in memories:
                fact = (m.get("fact") or "").strip()
                category = (m.get("category") or "general").strip()
                if not fact:
                    continue
                existing = conn.execute(
                    "SELECT 1 FROM memories WHERE project_id=? AND category=? AND fact=?",
                    (project_id, category, fact),
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    "INSERT INTO memories (id, project_id, category, fact, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), project_id, category, fact, now),
                )
                inserted += 1
            conn.commit()
            return inserted
        finally:
            conn.close()

    def get_memories(
        self, project_id: str, limit: int = 20
    ) -> List[Dict[str, str]]:
        """Return the most recent memories for *project_id*, newest first."""
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, category, fact, created_at FROM memories "
                "WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    # ── threads (continued) ────────────────────────────────────────────

    def delete_thread(self, thread_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
            conn.execute(
                "DELETE FROM sse_events WHERE scope = ? AND scope_id = ?",
                ("agent", thread_id),
            )
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

        analysis_model = analysis_config.get("analysis_model") or analysis_config.get("model", "logistic")
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
                "model": analysis_model,
                "analysis_model": analysis_model,
            },
        }
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(project_data, f, allow_unicode=True, sort_keys=False)

        conn = self._connect()
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
        conn = self._connect()
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
                    analysis_config.get("analysis_model")
                    or analysis_config.get("model", "logistic"),
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
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE runs SET status = ?, log_summary = ?, report_path = ?, finished_at = ? WHERE id = ?",
                (status, log_summary, report_path, now, run_id),
            )
            conn.commit()
        finally:
            conn.close()

    def list_runs(self, project_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM runs WHERE project_id = ? ORDER BY started_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def record_sse_event(self, scope: str, scope_id: str, event_id: int, data: str) -> None:
        conn = self._connect()
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
        conn = self._connect()
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

    def get_latest_sse_event_containing(
        self, scope: str, scope_id: str, needle: str
    ) -> Optional[Dict[str, Any]]:
        """返回 data 中包含指定键名的最近一条事件（倒序取一），无则 None。"""
        conn = self._connect()
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT scope, scope_id, event_id, data, created_at
                FROM sse_events
                WHERE scope = ? AND scope_id = ? AND data LIKE ?
                ORDER BY event_id DESC
                LIMIT 1
                """,
                (scope, scope_id, f'%"{needle}"%'),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_max_event_id(self, scope: str, scope_id: str) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT COALESCE(MAX(event_id), 0)
                FROM sse_events
                WHERE scope = ? AND scope_id = ?
                """,
                (scope, scope_id),
            ).fetchone()
            return int(row[0])
        finally:
            conn.close()

    def delete_sse_events(self, scope: str, scope_id: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "DELETE FROM sse_events WHERE scope = ? AND scope_id = ?",
                (scope, scope_id),
            )
            conn.commit()
        finally:
            conn.close()

    def has_running_run(self, project_id: str) -> bool:
        conn = self._connect()
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
