from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.config import settings
from app.models.device import Device
from app.models.family_account import FamilyAccount
from app.schemas.device import DeviceCreate, DeviceRead, DeviceUpdate

router = APIRouter()


@router.get("", response_model=list[DeviceRead])
def list_devices(
    db: DbSession,
    family_account_id: int | None = Query(None),
    is_active: bool | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(settings.DEFAULT_PAGE_SIZE, ge=1, le=settings.MAX_PAGE_SIZE),
):
    stmt = select(Device).offset(skip).limit(limit).order_by(Device.id)
    if family_account_id is not None:
        stmt = stmt.where(Device.family_account_id == family_account_id)
    if is_active is not None:
        stmt = stmt.where(Device.is_active == is_active)
    return db.scalars(stmt).all()


@router.post("", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
def create_device(payload: DeviceCreate, db: DbSession):
    if db.get(FamilyAccount, payload.family_account_id) is None:
        raise HTTPException(status_code=404, detail="Conta familiar nao encontrada")
    exists = db.scalar(select(Device).where(Device.fcm_token == payload.fcm_token))
    if exists is not None:
        raise HTTPException(status_code=409, detail="Token FCM ja cadastrado")
    obj = Device(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{device_id}", response_model=DeviceRead)
def get_device(device_id: int, db: DbSession):
    obj = db.get(Device, device_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Dispositivo nao encontrado")
    return obj


@router.patch("/{device_id}", response_model=DeviceRead)
def update_device(device_id: int, payload: DeviceUpdate, db: DbSession):
    obj = db.get(Device, device_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Dispositivo nao encontrado")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_device(device_id: int, db: DbSession):
    obj = db.get(Device, device_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Dispositivo nao encontrado")
    db.delete(obj)
    db.commit()
