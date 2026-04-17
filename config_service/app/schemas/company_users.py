from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, EmailStr, field_validator

ALLOWED_AGE_BANDS = {"20-25", "26-30", "31-35", "36-40", "41-50", "50+"}


class CompanyUserCreateRequest(BaseModel):
    emp_id: str | None = None
    full_name: str | None = None
    department: str | None = None
    location: str | None = None
    gender: str | None = None
    phone: str | None = None
    email: EmailStr
    company_id: UUID
    age_band: str | None = None

    @field_validator("age_band")
    @classmethod
    def validate_age_band(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                return None
        if value not in ALLOWED_AGE_BANDS:
            raise ValueError(f"age_band must be one of {sorted(ALLOWED_AGE_BANDS)}")
        return value


class CompanyUserUpdateRequest(BaseModel):
    emp_id: str | None = None
    full_name: str | None = None
    department: str | None = None
    location: str | None = None
    gender: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    company_id: UUID | None = None
    is_active: bool | None = None
    age_band: str | None = None

    @field_validator("age_band")
    @classmethod
    def validate_age_band(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                return None
        if value not in ALLOWED_AGE_BANDS:
            raise ValueError(f"age_band must be one of {sorted(ALLOWED_AGE_BANDS)}")
        return value


class CompanyUserResponse(BaseModel):
    id: UUID
    emp_id: str | None = None
    full_name: str | None = None
    department: str | None = None
    location: str | None = None
    gender: str | None = None
    phone: str | None = None
    email: EmailStr
    company_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
    username: str | None = None
    password: str | None = None
    age_band: str | None = None

    model_config = {"from_attributes": True}


class CompanyUserListResponse(BaseModel):
    items: list[CompanyUserResponse]
    total: int
    skip: int
    limit: int
