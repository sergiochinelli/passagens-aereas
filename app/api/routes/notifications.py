from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import DbSession, Notifier
from app.services.notification import FCMError

router = APIRouter()


class TestPushRequest(BaseModel):
    device_id: int
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=500)


@router.post("/notifications/test", tags=["notifications"])
def send_test_push(payload: TestPushRequest, db: DbSession, notifier: Notifier):
    """Envia push de teste a um dispositivo cadastrado (validacao do painel)."""
    try:
        return notifier.send_test_push(
            db, payload.device_id, payload.title, payload.body
        )
    except FCMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
