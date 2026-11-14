from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MonitoredRoute(Base):
    """Rota monitorada: parametros de busca e alerta definidos pelo painel."""

    __tablename__ = "monitored_routes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    family_account_id: Mapped[int] = mapped_column(
        ForeignKey("family_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Tipo de viagem: round_trip | one_way | multi_city
    trip_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Origem/destino usados em round_trip e one_way; em multi_city usam-se as legs
    origin: Mapped[str | None] = mapped_column(String(10), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(10), nullable=True)
    departure_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    return_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    passengers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Classe solicitada: economy | premium_economy | business | first
    travel_class: Mapped[str] = mapped_column(String(20), default="economy", nullable=False)

    # Parametros de alerta (configuraveis por rota via painel)
    max_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="BRL", nullable=False)
    monitor_interval_minutes: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False
    )
    alert_on_price_drop: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    alert_on_mixed_class: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Filtros de companhias (listas de codigos IATA)
    airlines_include: Mapped[list | None] = mapped_column(JSON, nullable=True)
    airlines_exclude: Mapped[list | None] = mapped_column(JSON, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    family_account: Mapped["FamilyAccount"] = relationship(back_populates="routes")  # noqa: F821
    created_by: Mapped["User | None"] = relationship(back_populates="created_routes")  # noqa: F821
    legs: Mapped[list["RouteLeg"]] = relationship(  # noqa: F821
        back_populates="route",
        cascade="all, delete-orphan",
        order_by="RouteLeg.leg_order",
    )
    results: Mapped[list["SearchResult"]] = relationship(  # noqa: F821
        back_populates="route", cascade="all, delete-orphan"
    )
