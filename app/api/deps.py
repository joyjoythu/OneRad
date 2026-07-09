import os
from pathlib import Path

from fastapi import Request
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.projects import ProjectStore


def _data_dir() -> Path:
    path = Path(os.environ.get("ONERAD_DATA_DIR", Path.home() / ".onerad"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_project_store(request: Request) -> ProjectStore:
    return request.app.state.project_store


def get_checkpointer(request: Request) -> AsyncSqliteSaver:
    return request.app.state.checkpointer
