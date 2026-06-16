from __future__ import annotations
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: str
    is_active: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


class LogoutResponse(BaseModel):
    success: bool
    message: str


class TokenUser(BaseModel):
    user_id: int
    username: str
    email: str
    role: str
    tenant_id: Optional[UUID] = None
    department_id: Optional[str] = None
    role_id: Optional[int] = None
    is_platform_admin: Optional[bool] = False
    vendor_id: Optional[int] = None


class CreateAdminRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    email: str = Field(..., min_length=5, max_length=150)
    password: str = Field(..., min_length=6, max_length=255)
    is_active: bool = True
