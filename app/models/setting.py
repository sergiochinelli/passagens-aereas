from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Setting(Base):
    """Configuracao chave-valor por conta familiar (area de parametrizacao)."""

    __tablename__ = "settings"
    __table_args__ = (
        UniqueConstraint("family_account_id", "key", name="uq_settings_family_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    family_account_id: Mapped[int] = mapped_column(
        ForeignKey("family_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSON, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    family_account: Mapped["FamilyAccount"] = relationship(back_populates="settings")  # noqa: F821
