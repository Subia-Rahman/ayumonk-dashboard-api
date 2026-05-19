from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, EmailStr, field_validator, model_validator
from config_service.app.schemas.company_users import CompanyUserResponse, ALLOWED_AGE_BANDS


class CompanyCreateRequest(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    industry: str | None = None
    size_bucket: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    location: str | None = None
    no_of_employees: int | None = None


class CompanyAdminCreateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=255)
    emp_id: str = Field(..., min_length=1, max_length=100)
    full_name: str | None = None
    department: str | None = None
    department_id: UUID | None = None
    role_id: int | None = Field(default=None, description="FK to roles.id stored on company_users")
    role_name: str | None = Field(
        default=None,
        max_length=50,
        description="Legacy role string stored on users.role (e.g. 'Company Admin')",
    )
    gender: str | None = None
    phone: str | None = None
    age_band: str | None = None
    is_active: bool = True

    @field_validator("username", "password", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value):
        if value is None:
            return value
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

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

    @model_validator(mode="after")
    def require_core_fields(self):
        if self.username is None and self.email is None and self.password is None:
            raise ValueError("admin is empty")
        return self


class CompanyCreateWithAdminRequest(BaseModel):
    company: CompanyCreateRequest
    admin: CompanyAdminCreateRequest | None = None

    @model_validator(mode="before")
    @classmethod
    def drop_empty_admin(cls, values):
        if not isinstance(values, dict):
            return values
        admin = values.get("admin")
        if admin is None:
            return values
        if isinstance(admin, dict):
            empty_values = True
            for key, value in admin.items():
                if key == "is_active":
                    continue
                if value not in (None, "", [], {}):
                    empty_values = False
                    break
            if empty_values:
                values["admin"] = None
        return values


class CompanyCreateWithAdminResponse(BaseModel):
    company: "CompanyResponse"
    admin: CompanyUserResponse | None = None


class CompanyAdminUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=100)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=6, max_length=255)
    emp_id: str | None = None
    full_name: str | None = None
    department: str | None = None
    department_id: UUID | None = None
    role_id: int | None = None
    role_name: str | None = Field(default=None, max_length=50)
    gender: str | None = None
    phone: str | None = None
    age_band: str | None = None
    is_active: bool | None = None

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


class CompanyUpdateRequest(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=255)
    industry: str | None = None
    size_bucket: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    no_of_employees: int | None = None
    is_active: bool | None = None
    admin: CompanyAdminUpdateRequest | None = None


class CompanyResponse(BaseModel):
    id: UUID
    company_name: str
    industry: str | None = None
    size_bucket: str | None = None
    email: str | None = None
    phone: str | None = None
    location_id: UUID | None = None
    location: str | None = None
    no_of_employees: int | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    admin: CompanyUserResponse | None = None

    model_config = {"from_attributes": True}
