from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def agent_root():
    return {"detail": "not implemented"}
