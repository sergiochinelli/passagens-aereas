from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=128)
    family_account_id: int | None = None


class AuthUserInfo(BaseModel):
    login: str
    name: str
    email: str = ""
    must_change: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_hours: int
    family_account_id: int
    user: AuthUserInfo


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class SessionInfo(BaseModel):
    login: str
    family_account_id: int
    created_at: datetime
    expires_at: datetime


class ResetRequest(BaseModel):
    family_account_id: int
    login: str = Field(min_length=1, max_length=80)
    voucher_login: str = Field(min_length=1, max_length=80)
    voucher_password: str = Field(min_length=1, max_length=128)


class ResetResponse(BaseModel):
    login: str
    name: str
    temporary_password: str


class SeedRequest(BaseModel):
    family_account_id: int


class SeedResponse(BaseModel):
    created: bool
