from fastapi import APIRouter, Depends

from app.api.deps import get_project_store
from app.projects import ProjectStore

router = APIRouter()


@router.get("/", status_code=501)
def list_projects(_store: ProjectStore = Depends(get_project_store)):
    return {"detail": "not implemented"}
