from __future__ import annotations
from datetime import datetime
from typing import Optional, List, Literal
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


AccessLevelLiteral = Literal["none", "view", "full"]
PolicyScopeLiteral = Literal["global", "tenant", "department", "self"]


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    tenant_id: UUID
    is_active: bool = True


class RoleRead(BaseModel):
    id: int
    name: str
    tenant_id: Optional[UUID] = None
    tenant_name: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    tenant_id: Optional[UUID] = None
    is_active: Optional[bool] = None


class PermissionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    module: str = Field(min_length=1, max_length=50)
    action: str = Field(min_length=1, max_length=50)
    codename: Optional[str] = Field(default=None, max_length=150)
    resource: Optional[str] = Field(default=None, max_length=50)


class PermissionRead(BaseModel):
    id: int
    name: str
    module: str
    action: str
    codename: Optional[str] = None
    resource: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PermissionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    module: Optional[str] = Field(default=None, min_length=1, max_length=50)
    action: Optional[str] = Field(default=None, min_length=1, max_length=50)
    codename: Optional[str] = Field(default=None, max_length=150)
    resource: Optional[str] = Field(default=None, max_length=50)


class RolePermissionAssign(BaseModel):
    permission_ids: List[int]
    tenant_id: UUID
    is_override: bool = False


class UserPermissionOverride(BaseModel):
    permission_id: int
    is_allowed: bool = True
    is_granted: bool = True
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    tenant_id: UUID


class PolicyCreate(BaseModel):
    name: str
    module: str = "global"
    scope: Optional[PolicyScopeLiteral] = None
    description: Optional[str] = None
    conditions: Optional[dict] = None
    condition_json: Optional[dict] = None
    effect: str = "allow"
    tenant_id: UUID
    is_active: bool = True


class PolicyRead(BaseModel):
    id: int
    name: str
    module: str
    scope: Optional[PolicyScopeLiteral] = None
    description: Optional[str] = None
    conditions: Optional[dict] = None
    condition_json: dict
    effect: str
    tenant_id: UUID
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class MenuCreate(BaseModel):
    name: str
    slug: Optional[str] = Field(default=None, max_length=100)
    path: Optional[str] = None
    parent_id: Optional[int] = None
    icon: Optional[str] = None
    order_no: int = 0
    is_active: bool = True


class MenuRead(BaseModel):
    id: int
    name: str
    slug: Optional[str] = None
    path: Optional[str] = None
    parent_id: Optional[int] = None
    icon: Optional[str] = None
    order_no: int
    tenant_id: Optional[UUID] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class MenuUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    slug: Optional[str] = Field(default=None, max_length=100)
    path: Optional[str] = None
    parent_id: Optional[int] = None
    icon: Optional[str] = None
    order_no: Optional[int] = None
    is_active: Optional[bool] = None


class RoleMenuItem(BaseModel):
    menu_id: int
    access_level: AccessLevelLiteral = "view"


class RoleMenuAssign(BaseModel):
    menu_ids: Optional[List[int]] = None
    items: Optional[List[RoleMenuItem]] = None
    access_level: AccessLevelLiteral = "view"
    tenant_id: UUID

    def resolved_items(self) -> list[RoleMenuItem]:
        if self.items:
            return list(self.items)
        if self.menu_ids:
            return [
                RoleMenuItem(menu_id=mid, access_level=self.access_level)
                for mid in self.menu_ids
            ]
        return []


class UserMenuItem(BaseModel):
    menu_id: int
    access_level: AccessLevelLiteral = "view"
    is_active: bool = True


class UserMenuAssign(BaseModel):
    menu_id: Optional[int] = None
    items: Optional[List[UserMenuItem]] = None
    access_level: AccessLevelLiteral = "view"
    is_active: bool = True
    tenant_id: UUID

    def resolved_items(self) -> list[UserMenuItem]:
        if self.items:
            return list(self.items)
        if self.menu_id is not None:
            return [
                UserMenuItem(
                    menu_id=self.menu_id,
                    access_level=self.access_level,
                    is_active=self.is_active,
                )
            ]
        return []


class RoleMenuRead(BaseModel):
    role_id: int
    menu_id: int
    menu_name: Optional[str] = None
    menu_slug: Optional[str] = None
    tenant_id: Optional[UUID] = None
    access_level: AccessLevelLiteral = "view"

    model_config = ConfigDict(from_attributes=True)


class RolePermissionRead(BaseModel):
    role_id: int
    permission_id: int
    permission_name: Optional[str] = None
    permission_codename: Optional[str] = None
    tenant_id: Optional[UUID] = None
    is_override: bool = False
    is_granted: bool = True

    model_config = ConfigDict(from_attributes=True)


class AccessibleMenuRead(BaseModel):
    menu_id: int
    menu_name: str
    slug: Optional[str] = None
    order_no: int = 0
    access_level: AccessLevelLiteral
    source: Literal["role", "user_override"]


class ResolvedPermissionRead(BaseModel):
    codename: str
    source: Literal["role_menu", "role_override", "user_override"]
    is_granted: bool


class RolePolicyAssign(BaseModel):
    policy_ids: List[int]
    tenant_id: UUID


class UserPolicyAssign(BaseModel):
    policy_ids: List[int]
    tenant_id: UUID


class EffectivePolicyResponse(BaseModel):
    policy_id: Optional[int] = None
    name: Optional[str] = None
    scope: PolicyScopeLiteral
    conditions: dict
    source: Literal["user", "role", "default"] = "role"


class AuditLogRead(BaseModel):
    id: int
    user_id: int
    action: str
    entity: str
    old_value: Optional[dict] = None
    new_value: Optional[dict] = None
    timestamp: datetime
    tenant_id: UUID

    model_config = ConfigDict(from_attributes=True)


class MenuTreeNode(MenuRead):
    children: list["MenuTreeNode"] = []


MenuTreeNode.model_rebuild()


class AccessContext(BaseModel):
    user_id: int
    role: str
    email: Optional[str] = None
    tenant_id: Optional[UUID] = None
    menu_access_level: AccessLevelLiteral
    granted_permissions: list[str] = []
    policy_scope: dict = {}
    is_platform_admin: bool = False
