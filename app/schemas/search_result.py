from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TriggeredBy = Literal["scheduled", "manual"]


class SearchResultBase(BaseModel):
    triggered_by: TriggeredBy = "manual"
    lowest_price: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="BRL", min_length=3, max_length=3)
    airline: str | None = Field(default=None, max_length=80)
    total_duration_minutes: int | None = Field(default=None, ge=0)
    stops: int | None = Field(default=None, ge=0)
    layovers: list | None = None
    legs_detail: list | None = None
    has_mixed_class: bool = False
    mixed_class_details: list | None = None
    raw_payload: dict | None = None


class SearchResultCreate(SearchResultBase):
    route_id: int


class SearchResultRead(SearchResultBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    route_id: int
    searched_at: datetime
