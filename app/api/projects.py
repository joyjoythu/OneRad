import asyncio
import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

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

    model_config = ConfigDict(extra="forbid")

    image_dir: str = ""
    clinical_path: str = ""
    output_dir: str = "./outputs"
    modality: str = "auto"
    covariates: str = ""
    model: str = "logistic"
    analysis_model: str = "logistic"


def _public_project(project: Dict[str, Any]) -> Dict[str, Any]:
    """Remove legacy project-scoped secrets from API responses."""
    result = dict(project)
    analysis = dict(result.get("analysis") or {})
    analysis.pop("api_key", None)
    result["analysis"] = analysis
    return result


class UpdateProjectRequest(BaseModel):
    """Request body for renaming a project."""

    name: str


@router.get("", response_model=List[Dict[str, Any]])
def list_projects(store: ProjectStore = Depends(get_project_store)):
    """List all projects ordered by most recently updated."""
    return [_public_project(project) for project in store.list_projects()]


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
    return _public_project(project)


@router.patch("/{project_id}", response_model=Dict[str, Any])
def update_project(
    project_id: str,
    payload: UpdateProjectRequest,
    store: ProjectStore = Depends(get_project_store),
):
    """Rename a project."""
    if store.load_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="项目名不能为空"
        )
    try:
        return _public_project(store.update_project_name(project_id, name))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


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
        return _public_project(store.save_project_config(project_id, payload.model_dump()))
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

    run_config = payload.model_dump()
    run_id = store.record_run_start(project_id, run_config)
    runtime_config = {
        **run_config,
        "api_key": request.app.state.settings_store.resolve_api_key(),
    }
    bridge = get_bridge(request)
    loop = asyncio.get_running_loop()

    start_pipeline_task(
        request.app,
        project_id,
        run_id,
        runtime_config,
        bridge,
        store,
        loop,
    )

    return {"run_id": run_id}


# @mention 文件索引时排除的目录名：版本控制、依赖与缓存目录
# 文件多且对用户无引用价值，遍历时直接跳过整棵子树。
_FILE_INDEX_EXCLUDED_DIRS = frozenset(
    {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".pytest_cache"}
)


@router.get("/{project_id}/files", response_model=Dict[str, Any])
def list_project_files(
    project_id: str,
    q: str = "",
    limit: int = 200,
    store: ProjectStore = Depends(get_project_store),
):
    """List files and directories under the project root for @mention completion.

    Returns a single sorted ``entries`` list of relative paths (POSIX
    separators); directory entries carry a trailing ``/`` so the chat input can
    insert them as ``@data/`` and the agent can resolve them with
    ``list_directory``. Noise directories are neither listed nor descended.
    ``q`` filters by case-insensitive substring; ``limit`` caps the result
    (clamped to [1, 500]). Unreadable subtrees are skipped so a permission
    error never fails the whole request.
    """
    project = store.load_project(project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")

    root = Path(project["path"])
    limit = max(1, min(limit, 500))
    entries: List[str] = []
    if root.is_dir():
        query = q.strip().lower()
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _FILE_INDEX_EXCLUDED_DIRS]
            for dirname in dirnames:
                rel = (Path(dirpath) / dirname).relative_to(root).as_posix()
                if not query or query in rel.lower():
                    entries.append(rel + "/")
            for name in filenames:
                rel = (Path(dirpath) / name).relative_to(root).as_posix()
                if not query or query in rel.lower():
                    entries.append(rel)
        entries.sort()
    return {"entries": entries[:limit]}


@router.get("/{project_id}/runs", response_model=List[Dict[str, Any]])
def list_project_runs(
    project_id: str,
    store: ProjectStore = Depends(get_project_store),
):
    """List analysis runs associated with a project."""
    if store.load_project(project_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
    return store.list_runs(project_id)
