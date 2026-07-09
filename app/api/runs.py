from fastapi import APIRouter

router = APIRouter()


@router.get("/", status_code=501)
def list_runs():
    return {"detail": "not implemented"}
