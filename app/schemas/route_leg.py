from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class RouteLegBase(BaseModel):
    leg_order: int = Field(ge=1)
    origin: str = Field(min_length=3, max_length=10)
    destination: str = Field(min_length=3, max_length=10)
    departure_date: date


class RouteLegCreate(RouteLegBase):
    pass


class RouteLegRead(RouteLegBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    route_id: int
