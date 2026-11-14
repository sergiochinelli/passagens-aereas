from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.config import settings
from app.core.security import hash_password
from app.models.family_account import FamilyAccount
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate

router = APIRouter()


@router.get("", response_model=list[UserRead])
def list_users(
    db: DbSession,
    family_account_id: int | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(settings.DEFAULT_PAGE_SIZE, ge=1, le=settings.MAX_PAGE_SIZE),
):
    stmt = select(User).offset(skip).limit(limit).order_by(User.id)
    if family_account_id is not None:
        stmt = stmt.where(User.family_account_id == family_account_id)
    return db.scalars(stmt).all()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, db: DbSession):
    if db.get(FamilyAccount, payload.family_account_id) is None:
        raise HTTPException(status_code=404, detail="Conta familiar nao encontrada")
    exists = db.scalar(select(User).where(User.email == payload.email))
    if exists is not None:
        raise HTTPException(status_code=409, detail="Email ja cadastrado")
    data = payload.model_dump(exclude={"password"})
    obj = User(**data, password_hash=hash_password(payload.password))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: int, db: DbSession):
    obj = db.get(User, user_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    return obj


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: int, payload: UserUpdate, db: DbSession):
    obj = db.get(User, user_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    data = payload.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    if password is not None:
        data["password_hash"] = hash_password(password)
    if "email" in data and data["email"] != obj.email:
        exists = db.scalar(select(User).where(User.email == data["email"]))
        if exists is not None:
            raise HTTPException(status_code=409, detail="Email ja cadastrado")
    for field, value in data.items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, db: DbSession):
    obj = db.get(User, user_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    db.delete(obj)
    db.commit()
