import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.api.deps import get_project_store
from app.api.runner import RunConfig, get_bridge, start_pipeline_task
from app.projects import ProjectStore

router = APIRouter()


def _data_dir() -> Path:
    """数据目录：每次调用现读环境变量，保证测试的 monkeypatch 生效。"""
    return Path(
        os.environ.get("ONERAD_DATA_DIR", str(Path.home() / ".onerad"))
    ).resolve()


def _resolve_project_path(path: str) -> Path:
    """Resolve a user-supplied project path.

    Rejects paths that contain '..' as a path component. Relative paths are
    resolved relative to the data directory (ONERAD_DATA_DIR env var, read
    lazily at call time); absolute paths are accepted as-is, allowing
    projects to live outside the default data directory.
    """
    parsed = Path(path)
    if ".." in parsed.parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project path"
        )

    if parsed.is_absolute():
        resolved = parsed.resolve()
    else:
        resolved = (_data_dir() / parsed).resolve()

    return resolved


class CreateProjectRequest(BaseModel):
    """Request body for creating a new project."""

    name: str
    path: str
    description: str = ""


class UpdateConfigRequest(BaseModel):
    """Request body for updating a project's analysis configuration."""

    image_dir: str = ""
    clinical_path: str = ""
    output_dir: str = "./outputs"
    modality: str = "auto"
    covariates: str = ""
    model: str = "logistic"
    analysis_model: str = "logistic"
    api_key: str = ""


@router.get("", response_model=List[Dict[str, Any]])
def list_projects(store: ProjectStore = Depends(get_project_store)):
    """List all projects ordered by most recently updated."""
    return store.list_projects()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
def create_project(payload: CreateProjectRequest, store: ProjectStore = Depends(get_project_store)):
    """Create a new project with the given name, path and description."""
    project_path = _resolve_project_path(payload.path)
    try:
        return store.create_project(payload.name, str(project_path), payload.description)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{project_id}", response_model=Dict[str, Any])
def get_project(project_id: str, store: ProjectStore = Depends(get_project_store)):
    """Get full details for a single project, including its analysis config."""
    project = store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return project


@router.put("/{project_id}/config", response_model=Dict[str, Any])
def update_config(
    project_id: str,
    payload: UpdateConfigRequest,
    store: ProjectStore = Depends(get_project_store),
):
    """Update the analysis configuration for a project."""
    if store.load_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    try:
        return store.save_project_config(project_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, store: ProjectStore = Depends(get_project_store)):
    """Delete a project and its associated runs."""
    if store.load_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    store.delete_project(project_id)
    return None


@router.post("/{project_id}/runs", response_model=Dict[str, Any], status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    project_id: str,
    payload: RunConfig,
    request: Request,
    store: ProjectStore = Depends(get_project_store),
) -> Dict[str, Any]:
    """Trigger a new pipeline run for a project."""
    if store.load_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    if store.has_running_run(project_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="项目已有正在运行的流水线"
        )

    run_id = store.record_run_start(project_id, payload.model_dump())
    bridge = get_bridge(request)
    loop = asyncio.get_running_loop()

    start_pipeline_task(
        request.app,
        project_id,
        run_id,
        payload.model_dump(),
        bridge,
        store,
        loop,
    )

    return {"run_id": run_id}


@router.get("/{project_id}/runs", response_model=List[Dict[str, Any]])
def list_project_runs(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
):
    """List analysis runs associated with a project."""
    if store.load_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return store.list_runs(project_id)
