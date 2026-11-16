from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuthSession(Base):
    """Sessao autenticada da API (token opaco; so o hash e persistido)."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    family_account_id: Mapped[int] = mapped_column(
        ForeignKey("family_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    login: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
