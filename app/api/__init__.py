from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.api import agent, projects, runs


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="OneRad API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
    app.include_router(agent.router, prefix="/api/agent", tags=["agent"])

    dist_dir = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if dist_dir.exists():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            index = dist_dir / "index.html"
            if index.exists():
                return FileResponse(index)
            return {"detail": "frontend not built"}
    return app
