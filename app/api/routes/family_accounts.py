from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.config import settings
from app.models.family_account import FamilyAccount
from app.schemas.family_account import (
    FamilyAccountCreate,
    FamilyAccountRead,
    FamilyAccountUpdate,
)

router = APIRouter()


@router.get("", response_model=list[FamilyAccountRead])
def list_family_accounts(
    db: DbSession,
    skip: int = Query(0, ge=0),
    limit: int = Query(settings.DEFAULT_PAGE_SIZE, ge=1, le=settings.MAX_PAGE_SIZE),
):
    stmt = select(FamilyAccount).offset(skip).limit(limit).order_by(FamilyAccount.id)
    return db.scalars(stmt).all()


@router.post(
    "", response_model=FamilyAccountRead, status_code=status.HTTP_201_CREATED
)
def create_family_account(payload: FamilyAccountCreate, db: DbSession):
    obj = FamilyAccount(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{account_id}", response_model=FamilyAccountRead)
def get_family_account(account_id: int, db: DbSession):
    obj = db.get(FamilyAccount, account_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Conta familiar nao encontrada")
    return obj


@router.patch("/{account_id}", response_model=FamilyAccountRead)
def update_family_account(
    account_id: int, payload: FamilyAccountUpdate, db: DbSession
):
    obj = db.get(FamilyAccount, account_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Conta familiar nao encontrada")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_family_account(account_id: int, db: DbSession):
    obj = db.get(FamilyAccount, account_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Conta familiar nao encontrada")
    db.delete(obj)
    db.commit()
