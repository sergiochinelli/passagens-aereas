from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.config import settings as app_settings
from app.models.family_account import FamilyAccount
from app.models.setting import Setting
from app.schemas.setting import SettingCreate, SettingRead, SettingUpdate

router = APIRouter()


@router.get("", response_model=list[SettingRead])
def list_settings(
    db: DbSession,
    family_account_id: int | None = Query(None),
    key: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(
        app_settings.DEFAULT_PAGE_SIZE, ge=1, le=app_settings.MAX_PAGE_SIZE
    ),
):
    stmt = select(Setting).offset(skip).limit(limit).order_by(Setting.id)
    if family_account_id is not None:
        stmt = stmt.where(Setting.family_account_id == family_account_id)
    if key is not None:
        stmt = stmt.where(Setting.key == key)
    return db.scalars(stmt).all()


@router.post("", response_model=SettingRead, status_code=status.HTTP_201_CREATED)
def create_setting(payload: SettingCreate, db: DbSession):
    if db.get(FamilyAccount, payload.family_account_id) is None:
        raise HTTPException(status_code=404, detail="Conta familiar nao encontrada")
    exists = db.scalar(
        select(Setting).where(
            Setting.family_account_id == payload.family_account_id,
            Setting.key == payload.key,
        )
    )
    if exists is not None:
        raise HTTPException(
            status_code=409,
            detail="Chave ja configurada para esta conta (use PATCH)",
        )
    obj = Setting(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{setting_id}", response_model=SettingRead)
def get_setting(setting_id: int, db: DbSession):
    obj = db.get(Setting, setting_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Configuracao nao encontrada")
    return obj


@router.patch("/{setting_id}", response_model=SettingRead)
def update_setting(setting_id: int, payload: SettingUpdate, db: DbSession):
    obj = db.get(Setting, setting_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Configuracao nao encontrada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{setting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_setting(setting_id: int, db: DbSession):
    obj = db.get(Setting, setting_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Configuracao nao encontrada")
    db.delete(obj)
    db.commit()
