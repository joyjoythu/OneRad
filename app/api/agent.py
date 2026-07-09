from fastapi import APIRouter

router = APIRouter()


@router.get("/", status_code=501)
def agent_root():
    return {"detail": "not implemented"}
