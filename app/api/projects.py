from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.deps import get_project_store
from app.projects import ProjectStore

router = APIRouter()


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
    model: str = "deepseek-v4-pro"
    api_key: str = ""


@router.get("/", response_model=List[Dict[str, Any]])
def list_projects(store: ProjectStore = Depends(get_project_store)):
    """List all projects ordered by most recently updated."""
    return store.list_projects()


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=Dict[str, Any])
def create_project(payload: CreateProjectRequest, store: ProjectStore = Depends(get_project_store)):
    """Create a new project with the given name, path and description."""
    try:
        return store.create_project(payload.name, payload.path, payload.description)
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
    try:
        return store.save_project_config(project_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, store: ProjectStore = Depends(get_project_store)):
    """Delete a project and its associated runs."""
    store.delete_project(project_id)
    return None


@router.get("/{project_id}/runs", response_model=List[Dict[str, Any]])
def list_project_runs(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
):
    """List analysis runs associated with a project."""
    return store.list_runs(project_id)
