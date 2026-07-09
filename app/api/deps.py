from functools import lru_cache
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.projects import ProjectStore


@lru_cache()
def get_project_store() -> ProjectStore:
    db_dir = Path.home() / ".onerad"
    db_dir.mkdir(parents=True, exist_ok=True)
    return ProjectStore(db_path=str(db_dir / "projects.db"))


@lru_cache()
def get_checkpointer() -> AsyncSqliteSaver:
    db_dir = Path.home() / ".onerad"
    db_dir.mkdir(parents=True, exist_ok=True)
    return AsyncSqliteSaver.from_conn_string(str(db_dir / "checkpoints.db"))
