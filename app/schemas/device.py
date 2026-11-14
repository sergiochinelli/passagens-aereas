from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DevicePlatform = Literal["android", "web"]


class DeviceBase(BaseModel):
    platform: DevicePlatform
    fcm_token: str = Field(min_length=10, max_length=512)
    label: str | None = Field(default=None, max_length=120)
    is_active: bool = True


class DeviceCreate(DeviceBase):
    family_account_id: int
    user_id: int | None = None


class DeviceUpdate(BaseModel):
    platform: DevicePlatform | None = None
    fcm_token: str | None = Field(default=None, min_length=10, max_length=512)
    label: str | None = Field(default=None, max_length=120)
    user_id: int | None = None
    is_active: bool | None = None


class DeviceRead(DeviceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    family_account_id: int
    user_id: int | None
    last_seen_at: datetime | None
    created_at: datetime
