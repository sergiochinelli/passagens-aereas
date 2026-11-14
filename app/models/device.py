from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Device(Base):
    """Dispositivo cadastrado para receber notificacoes push (FCM)."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    family_account_id: Mapped[int] = mapped_column(
        ForeignKey("family_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Plataforma: android | web
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    fcm_token: Mapped[str] = mapped_column(String(512), unique=True, nullable=False, index=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    family_account: Mapped["FamilyAccount"] = relationship(back_populates="devices")  # noqa: F821
    user: Mapped["User | None"] = relationship(back_populates="devices")  # noqa: F821
