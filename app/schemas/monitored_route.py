from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.route_leg import RouteLegCreate, RouteLegRead

TripType = Literal["round_trip", "one_way", "multi_city"]
TravelClass = Literal["economy", "premium_economy", "business", "first"]


class MonitoredRouteBase(BaseModel):
    trip_type: TripType
    origin: str | None = Field(default=None, min_length=3, max_length=10)
    destination: str | None = Field(default=None, min_length=3, max_length=10)
    departure_date: date | None = None
    return_date: date | None = None
    passengers: int = Field(default=1, ge=1, le=9)
    travel_class: TravelClass = "economy"
    max_price: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    monitor_interval_minutes: int = Field(default=60, ge=5)
    alert_on_price_drop: bool = True
    alert_on_mixed_class: bool = True
    airlines_include: list[str] | None = None
    airlines_exclude: list[str] | None = None
    is_active: bool = True


class MonitoredRouteCreate(MonitoredRouteBase):
    family_account_id: int
    created_by_user_id: int | None = None
    legs: list[RouteLegCreate] = []

    @model_validator(mode="after")
    def validate_trip_fields(self) -> "MonitoredRouteCreate":
        if self.trip_type == "multi_city":
            if len(self.legs) < 2:
                raise ValueError(
                    "multi_city exige ao menos 2 trechos (legs) definidos"
                )
        else:
            if not self.origin or not self.destination:
                raise ValueError("origin e destination sao obrigatorios")
            if self.departure_date is None:
                raise ValueError("departure_date e obrigatorio")
            if self.trip_type == "round_trip" and self.return_date is None:
                raise ValueError("round_trip exige return_date")
        return self


class MonitoredRouteUpdate(BaseModel):
    trip_type: TripType | None = None
    origin: str | None = Field(default=None, min_length=3, max_length=10)
    destination: str | None = Field(default=None, min_length=3, max_length=10)
    departure_date: date | None = None
    return_date: date | None = None
    passengers: int | None = Field(default=None, ge=1, le=9)
    travel_class: TravelClass | None = None
    max_price: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    monitor_interval_minutes: int | None = Field(default=None, ge=5)
    alert_on_price_drop: bool | None = None
    alert_on_mixed_class: bool | None = None
    airlines_include: list[str] | None = None
    airlines_exclude: list[str] | None = None
    is_active: bool | None = None
    legs: list[RouteLegCreate] | None = None


class MonitoredRouteRead(MonitoredRouteBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    family_account_id: int
    created_by_user_id: int | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    legs: list[RouteLegRead] = []
