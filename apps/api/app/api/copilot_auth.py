from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import current_user, get_store
from app.schemas.auth import CopilotCheckRequest, CopilotStartRequest
from app.services.copilot_auth_service import CopilotAuthService
from app.store import InMemoryStore, UserRecord


router = APIRouter(prefix="/api/copilot/auth", tags=["copilot-auth"])


@router.post("/start")
def start(
    payload: CopilotStartRequest,
    user: UserRecord = Depends(current_user),
    store: InMemoryStore = Depends(get_store),
) -> dict[str, object]:
    record = CopilotAuthService(store).start(user=user, github_base_url=payload.github_base_url)
    return {
        "auth_id": record.auth_id,
        "device_code": record.device_code,
        "user_code": record.user_code,
        "verification_uri": record.verification_uri,
        "verification_uri_complete": record.verification_uri_complete,
        "expires_in": record.expires_in,
        "interval": record.interval,
    }


@router.post("/check")
def check(
    payload: CopilotCheckRequest,
    user: UserRecord = Depends(current_user),
    store: InMemoryStore = Depends(get_store),
) -> dict[str, object]:
    return CopilotAuthService(store).check(user=user, auth_id=payload.auth_id)
