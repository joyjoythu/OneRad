"""Application-wide settings API."""

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_general_settings_store
from app.settings import GeneralSettingsStore


router = APIRouter()


class UpdateGeneralSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = ""


@router.get("", response_model=Dict[str, Any])
def get_settings(
    store: GeneralSettingsStore = Depends(get_general_settings_store),
) -> Dict[str, Any]:
    return store.public_settings()


@router.put("", response_model=Dict[str, Any])
def update_settings(
    payload: UpdateGeneralSettingsRequest,
    store: GeneralSettingsStore = Depends(get_general_settings_store),
) -> Dict[str, Any]:
    return store.save(payload.api_key)
