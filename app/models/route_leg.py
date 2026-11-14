from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RouteLeg(Base):
    """Trecho de uma rota multi_city (ordem, origem, destino e data)."""

    __tablename__ = "route_legs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    route_id: Mapped[int] = mapped_column(
        ForeignKey("monitored_routes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    leg_order: Mapped[int] = mapped_column(Integer, nullable=False)
    origin: Mapped[str] = mapped_column(String(10), nullable=False)
    destination: Mapped[str] = mapped_column(String(10), nullable=False)
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)

    route: Mapped["MonitoredRoute"] = relationship(back_populates="legs")  # noqa: F821
