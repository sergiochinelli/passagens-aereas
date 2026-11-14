from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FamilyAccountBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_active: bool = True


class FamilyAccountCreate(FamilyAccountBase):
    pass


class FamilyAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None


class FamilyAccountRead(FamilyAccountBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
