from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SearchResult(Base):
    """Resultado persistido de uma consulta de precos para uma rota."""

    __tablename__ = "search_results"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    route_id: Mapped[int] = mapped_column(
        ForeignKey("monitored_routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    searched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # Disparo: scheduled (agendador) | manual (endpoint)
    triggered_by: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)

    lowest_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="BRL", nullable=False)

    # Resumo da melhor opcao encontrada
    airline: Mapped[str | None] = mapped_column(String(80), nullable=True)
    total_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stops: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Escalas e detalhes por trecho (estrutura livre, preenchida pela Etapa 2)
    layovers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    legs_detail: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Detector de classe mista
    has_mixed_class: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mixed_class_details: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Resposta bruta do provedor (SerpApi) para auditoria
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    route: Mapped["MonitoredRoute"] = relationship(back_populates="results")  # noqa: F821
