"""Servico de autenticacao da API.

Usuarios de login vivem no setting `auth_users` da conta familiar
(mesmo formato consumido pelo frontend). Senhas podem estar no formato
legado `v1.` (AES-GCM, reversivel) ou PBKDF2 (`iterations$salt$hex`) —
`verify_any_password` aceita ambos; gravacoes novas sempre usam PBKDF2.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    encrypt_v1_password,
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_any_password,
)
from app.models.auth_session import AuthSession
from app.models.setting import Setting

DEFAULT_AUTH_USERS = [
    {"login": "sergio", "name": "Sergio", "email": "", "password": "1234"},
    {"login": "cris", "name": "Cris", "email": "", "password": "1234"},
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _users_of(setting: Setting) -> list[dict]:
    value = setting.value if isinstance(setting.value, dict) else {}
    return list(value.get("users") or [])


def get_auth_setting(db: Session, family_account_id: int) -> Setting | None:
    return db.scalar(
        select(Setting).where(
            Setting.family_account_id == family_account_id,
            Setting.key == settings.AUTH_USERS_SETTING_KEY,
        )
    )


def seed_auth_users(db: Session, family_account_id: int) -> Setting | None:
    """Cria o setting auth_users inicial (mesmos defaults do frontend).

    Senhas no formato legado v1 para manter compatibilidade com o app
    atual; ambos nascem com must_change=true.
    """
    existing = get_auth_setting(db, family_account_id)
    if existing is not None:
        return existing
    users = [
        {
            "login": u["login"],
            "name": u["name"],
            "email": u["email"],
            "pw": encrypt_v1_password(u["password"]),
            "must_change": True,
        }
        for u in DEFAULT_AUTH_USERS
    ]
    setting = Setting(
        family_account_id=family_account_id,
        key=settings.AUTH_USERS_SETTING_KEY,
        value={"users": users},
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


def find_login_users(
    db: Session, login: str, family_account_id: int | None = None
) -> list[tuple[Setting, dict]]:
    """Todas as ocorrencias do login nos settings auth_users."""
    stmt = select(Setting).where(Setting.key == settings.AUTH_USERS_SETTING_KEY)
    if family_account_id is not None:
        stmt = stmt.where(Setting.family_account_id == family_account_id)
    found = []
    for setting in db.scalars(stmt).all():
        user = next(
            (u for u in _users_of(setting) if u.get("login") == login.lower()),
            None,
        )
        if user is not None:
            found.append((setting, user))
    return found


def find_login_user(
    db: Session, login: str, family_account_id: int | None = None
) -> tuple[Setting, dict] | None:
    found = find_login_users(db, login, family_account_id)
    return found[0] if found else None


def list_login_users(db: Session, family_account_id: int) -> list[dict]:
    """Usuarios aptos a login, sem o campo de senha (uso pre-autenticacao)."""
    setting = get_auth_setting(db, family_account_id)
    if setting is None:
        return []
    return [
        {
            "login": u.get("login", ""),
            "name": u.get("name", u.get("login", "")),
            "must_change": bool(u.get("must_change", False)),
        }
        for u in _users_of(setting)
    ]


def create_session(db: Session, family_account_id: int, login: str) -> str:
    token = generate_session_token()
    session = AuthSession(
        family_account_id=family_account_id,
        login=login,
        token_hash=hash_session_token(token),
        expires_at=_utcnow() + timedelta(hours=settings.AUTH_TOKEN_TTL_HOURS),
    )
    db.add(session)
    db.commit()
    return token


def get_valid_session(db: Session, token: str | None) -> AuthSession | None:
    if not token:
        return None
    session = db.scalar(
        select(AuthSession).where(AuthSession.token_hash == hash_session_token(token))
    )
    if session is None or session.revoked_at is not None:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= _utcnow():
        return None
    return session


def authenticate(
    db: Session, login: str, password: str, family_account_id: int | None = None
) -> tuple[Setting, dict] | None:
    """Retorna (setting, user) se a senha confere; None caso contrario.

    Sem filtro de conta, testa todos os candidatos com o mesmo login —
    a combinacao login+senha resolve qual conta autenticar.
    """
    for setting, user in find_login_users(db, login, family_account_id):
        if verify_any_password(password, str(user.get("pw", ""))):
            return setting, user
    return None


def revoke_session(db: Session, session: AuthSession) -> None:
    session.revoked_at = _utcnow()
    db.commit()


def revoke_other_sessions(
    db: Session, family_account_id: int, login: str, keep: AuthSession | None = None
) -> None:
    stmt = select(AuthSession).where(
        AuthSession.family_account_id == family_account_id,
        AuthSession.login == login,
        AuthSession.revoked_at.is_(None),
    )
    for other in db.scalars(stmt).all():
        if keep is not None and other.id == keep.id:
            continue
        other.revoked_at = _utcnow()
    db.commit()


def set_user_password(
    db: Session,
    family_account_id: int,
    login: str,
    new_password: str,
    must_change: bool,
) -> dict:
    """Regrava a senha do usuario em PBKDF2. Retorna o usuario atualizado."""
    setting = get_auth_setting(db, family_account_id)
    if setting is None:
        raise ValueError("Usuarios de login nao configurados para esta conta")
    users = _users_of(setting)
    if not any(u.get("login") == login for u in users):
        raise ValueError("Usuario nao encontrado")
    users = [
        {**u, "pw": hash_password(new_password), "must_change": must_change}
        if u.get("login") == login
        else u
        for u in users
    ]
    setting.value = {**(setting.value or {}), "users": users}
    db.commit()
    return next(u for u in users if u.get("login") == login)


def change_password(
    db: Session,
    family_account_id: int,
    login: str,
    new_password: str,
    must_change: bool = False,
) -> None:
    set_user_password(db, family_account_id, login, new_password, must_change)


def reset_user_password(
    db: Session, family_account_id: int, login: str
) -> tuple[dict, str]:
    """Reset "esqueci a senha": gera temporaria PBKDF2 + must_change.

    Retorna (usuario, senha_temporaria). A temporaria volta na resposta para
    o frontend autenticar a sessao e trocar a senha sem exibi-la.
    """
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    temp = "".join(secrets.choice(alphabet) for _ in range(10))
    user = set_user_password(
        db, family_account_id, login, temp, must_change=True
    )
    revoke_other_sessions(db, family_account_id, login)
    return user, temp
    """Regrava a senha do usuario em PBKDF2 (formato nao reversivel)."""
    setting = get_auth_setting(db, family_account_id)
    if setting is None:
        raise ValueError("Usuarios de login nao configurados para esta conta")
    users = _users_of(setting)
    if not any(u.get("login") == login for u in users):
        raise ValueError("Usuario nao encontrado")
    users = [
        {
            **u,
            "pw": hash_password(new_password),
            "must_change": must_change,
        }
        if u.get("login") == login
        else u
        for u in users
    ]
    setting.value = {**(setting.value or {}), "users": users}
    db.commit()
