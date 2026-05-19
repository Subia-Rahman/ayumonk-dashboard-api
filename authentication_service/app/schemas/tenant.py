from pydantic import BaseModel, Field, ConfigDict
from typing import Optional


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    code: str = Field(min_length=1, max_length=50)
    domain: Optional[str] = None
    is_active: bool = True


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    domain: Optional[str] = None
    is_active: Optional[bool] = None


class TenantRead(BaseModel):
    id: int
    name: str
    code: str
    domain: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class TenantIdRead(BaseModel):
    tenant_id: int
    name: str | None = None
    code: str | None = None
