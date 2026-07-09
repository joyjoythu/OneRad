from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_runs():
    return {"detail": "not implemented"}
