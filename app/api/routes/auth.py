from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentSession, DbSession
from app.core.config import settings as app_settings
from app.core.security import verify_any_password
from app.models.family_account import FamilyAccount
from app.schemas.auth import (
    AuthUserInfo,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    ResetRequest,
    ResetResponse,
    SeedRequest,
    SeedResponse,
    SessionInfo,
)
from app.services import auth_service

router = APIRouter()


@router.get("/users", response_model=list[AuthUserInfo])
def list_login_users(
    db: DbSession,
    family_account_id: int = Query(...),
):
    """Usuarios da conta para a tela de login (sem campo de senha)."""
    if db.get(FamilyAccount, family_account_id) is None:
        raise HTTPException(status_code=404, detail="Conta familiar nao encontrada")
    return auth_service.list_login_users(db, family_account_id)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: DbSession):
    result = auth_service.authenticate(
        db, payload.login, payload.password, payload.family_account_id
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login ou senha invalidos",
        )
    setting, user = result
    token = auth_service.create_session(
        db, setting.family_account_id, user["login"]
    )
    return LoginResponse(
        access_token=token,
        expires_in_hours=app_settings.AUTH_TOKEN_TTL_HOURS,
        family_account_id=setting.family_account_id,
        user=AuthUserInfo(
            login=user.get("login", payload.login.lower()),
            name=user.get("name", payload.login),
            email=user.get("email", ""),
            must_change=bool(user.get("must_change", False)),
        ),
    )


@router.get("/me", response_model=SessionInfo)
def me(session: CurrentSession):
    return SessionInfo(
        login=session.login,
        family_account_id=session.family_account_id,
        created_at=session.created_at,
        expires_at=session.expires_at,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(session: CurrentSession, db: DbSession):
    auth_service.revoke_session(db, session)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordRequest, session: CurrentSession, db: DbSession
):
    found = auth_service.find_login_user(db, session.login, session.family_account_id)
    if found is None or not verify_any_password(
        payload.current_password, str(found[1].get("pw", ""))
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha atual incorreta",
        )
    auth_service.change_password(
        db, session.family_account_id, session.login, payload.new_password
    )
    auth_service.revoke_other_sessions(
        db, session.family_account_id, session.login, keep=session
    )


@router.post("/reset", response_model=ResetResponse)
def reset_password(payload: ResetRequest, db: DbSession):
    """Fluxo "esqueci a senha": outro usuario da MESMA conta avaliza com a
    propria senha; a vitoria gera temporaria e exige troca no proximo login."""
    if payload.login.lower() == payload.voucher_login.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O avalista precisa ser outro usuario da conta",
        )
    voucher = auth_service.authenticate(
        db,
        payload.voucher_login,
        payload.voucher_password,
        payload.family_account_id,
    )
    if voucher is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Senha do avalista incorreta",
        )
    try:
        user, temp = auth_service.reset_user_password(
            db, payload.family_account_id, payload.login.lower()
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    return ResetResponse(
        login=user["login"],
        name=user.get("name", user["login"]),
        temporary_password=temp,
    )


@router.post("/seed", response_model=SeedResponse)
def seed(payload: SeedRequest, db: DbSession):
    """Bootstrap: semeia auth_users se a conta ainda nao tiver (idempotente)."""
    if db.get(FamilyAccount, payload.family_account_id) is None:
        raise HTTPException(status_code=404, detail="Conta familiar nao encontrada")
    existed = auth_service.get_auth_setting(db, payload.family_account_id)
    auth_service.seed_auth_users(db, payload.family_account_id)
    return SeedResponse(created=existed is None)
