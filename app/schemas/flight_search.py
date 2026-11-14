from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.route_leg import RouteLegCreate

TripType = Literal["round_trip", "one_way", "multi_city"]
TravelClass = Literal["economy", "premium_economy", "business", "first"]
TriggeredBy = Literal["scheduled", "manual"]


class SearchCriteria(BaseModel):
    """Criterios de busca (aceita tanto consulta avulsa quanto rota salva)."""

    trip_type: TripType
    origin: str | None = Field(default=None, min_length=3, max_length=10)
    destination: str | None = Field(default=None, min_length=3, max_length=10)
    departure_date: date | None = None
    return_date: date | None = None
    passengers: int = Field(default=1, ge=1, le=9)
    travel_class: TravelClass = "economy"
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    airlines_include: list[str] | None = None
    airlines_exclude: list[str] | None = None
    legs: list[RouteLegCreate] = []

    @model_validator(mode="after")
    def validate_trip_fields(self) -> "SearchCriteria":
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


class LegDetail(BaseModel):
    leg_index: int
    origin: str | None = None
    origin_name: str | None = None
    destination: str | None = None
    destination_name: str | None = None
    departure_time: str | None = None
    arrival_time: str | None = None
    airline: str | None = None
    flight_number: str | None = None
    travel_class: str | None = None
    duration_minutes: int | None = None
    overnight: bool = False


class LayoverDetail(BaseModel):
    airport_id: str | None = None
    name: str | None = None
    duration_minutes: int | None = None
    overnight: bool = False


class MixedClassDetail(BaseModel):
    leg_index: int
    expected_class: str
    found_class: str | None


class FlightOption(BaseModel):
    """Uma opcao de voo ja normalizada a partir da resposta do provedor."""

    price: Decimal | None = None
    currency: str = "BRL"
    airlines: list[str] = []
    total_duration_minutes: int | None = None
    stops: int = 0
    layovers: list[LayoverDetail] = []
    legs: list[LegDetail] = []
    has_mixed_class: bool = False
    mixed_class_details: list[MixedClassDetail] = []
    booking_token: str | None = None


class FlightSearchResponse(BaseModel):
    searched_at: datetime
    criteria: SearchCriteria
    options: list[FlightOption]
    option_count: int
    search_url: str | None = None  # link do Google Flights p/ esta busca


class PersistedSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    route_id: int
    searched_at: datetime
    triggered_by: str
    lowest_price: Decimal | None
    currency: str
    airline: str | None
    total_duration_minutes: int | None
    stops: int | None
    layovers: list | None
    legs_detail: list | None
    has_mixed_class: bool
    mixed_class_details: list | None
