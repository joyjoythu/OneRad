import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from starlette.responses import FileResponse

from app.api import agent, filesystem, fs, projects, runs, settings
from app.api.sse import EventBridge
from app.projects import ProjectStore
from app.settings import GeneralSettingsStore
from app.agent import create_agent_graph


def _data_dir() -> Path:
    path = Path(os.environ.get("ONERAD_DATA_DIR", Path.home() / ".onerad"))
    path.mkdir(parents=True, exist_ok=True)
    return path


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_dir = _data_dir()
    app.state.project_store = ProjectStore(db_path=str(data_dir / "projects.db"))
    app.state.settings_store = GeneralSettingsStore(data_dir / "settings.yaml")
    app.state.settings_store.migrate_legacy_project_key(
        app.state.project_store.list_projects()
    )
    app.state.event_bridge = EventBridge(str(app.state.project_store.db_path))
    app.state.pipeline_tasks = set()
    app.state.pipeline_task_map = {}
    app.state.active_agent_streams = set()
    app.state.agent_stream_tasks = {}
    app.state.agent_api_keys = {}
    app.state.agent_auto_approve = {}
    app.state.agent_title_tasks = set()
    async with AsyncSqliteSaver.from_conn_string(
        str(data_dir / "checkpoints.db")
    ) as saver:
        app.state.checkpointer = saver
        app.state.agent_graph = create_agent_graph(checkpointer=saver)
        yield

    remaining = list(app.state.pipeline_tasks)
    for task in remaining:
        task.cancel()
    if remaining:
        await asyncio.gather(*remaining, return_exceptions=True)


def create_app() -> FastAPI:
    app = FastAPI(title="OneRad API", lifespan=lifespan, redirect_slashes=False)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:4173",
            "http://localhost:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
    app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
    app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
    app.include_router(
        filesystem.router, prefix="/api/filesystem", tags=["filesystem"]
    )
    app.include_router(fs.router, prefix="/api/fs", tags=["fs"])

    dist_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist_dir.exists():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            index = dist_dir / "index.html"
            if index.exists():
                return FileResponse(index)
            raise HTTPException(status_code=404, detail="frontend not built")
    return app
