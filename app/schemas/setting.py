from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SettingBase(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    value: Any = None


class SettingCreate(SettingBase):
    family_account_id: int


class SettingUpdate(BaseModel):
    value: Any = None


class SettingRead(SettingBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    family_account_id: int
    updated_at: datetime
