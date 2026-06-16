from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.db import get_db
from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.rbac import require_permission
from authentication_service.app.core.rbac_constants import MenuAccessLevel
from authentication_service.app.models.role import Role
from authentication_service.app.models.permission import Permission
from authentication_service.app.models.user_permission import UserPermission
from authentication_service.app.models.policy import Policy
from authentication_service.app.models.menu import Menu
from authentication_service.app.models.user_menu import UserMenu
from authentication_service.app.schemas.access_control import (
    RoleCreate,
    RoleRead,
    RoleUpdate,
    PermissionCreate,
    PermissionRead,
    PermissionUpdate,
    RolePermissionAssign,
    UserPermissionOverride,
    PolicyCreate,
    PolicyRead,
    MenuCreate,
    MenuRead,
    MenuUpdate,
    RoleMenuAssign,
    UserMenuAssign,
    MenuTreeNode,
    RoleMenuRead,
    RolePermissionRead,
    AccessibleMenuRead,
    ResolvedPermissionRead,
    RolePolicyAssign,
    UserPolicyAssign,
    EffectivePolicyResponse,
)
from authentication_service.app.repositories.role_repo import RoleRepository
from authentication_service.app.repositories.permission_repo import PermissionRepository
from authentication_service.app.repositories.role_permission_repo import RolePermissionRepository
from authentication_service.app.repositories.user_permission_repo import UserPermissionRepository
from authentication_service.app.repositories.policy_repo import PolicyRepository
from authentication_service.app.repositories.menu_repo import MenuRepository
from authentication_service.app.repositories.role_menu_repo import RoleMenuRepository
from authentication_service.app.repositories.user_menu_repo import UserMenuRepository
from authentication_service.app.repositories.role_policy_repo import RolePolicyRepository
from authentication_service.app.repositories.user_policy_repo import UserPolicyRepository

from authentication_service.app.services.access_control_service import AccessControlService
from authentication_service.app.services.menu_service import MenuService
from authentication_service.app.services.audit_log_service import AuditLogService
from authentication_service.app.services.rbac_service import RBACService
from config_service.app.repositories.company_users import UserRepository


router = APIRouter(prefix="/api/v1/auth", tags=["AccessControl"])


def _build_menu_tree(menus: list[Menu]) -> list[MenuTreeNode]:
    nodes = {m.id: MenuTreeNode.model_validate(m) for m in menus}
    roots = []
    for node in nodes.values():
        if node.parent_id and node.parent_id in nodes:
            parent = nodes[node.parent_id]
            parent.children.append(node)
        else:
            roots.append(node)
    roots.sort(key=lambda n: n.order_no)
    return roots


def _require_platform_admin(current_user):
    if not getattr(current_user, "is_platform_admin", False):
        raise HTTPException(status_code=403, detail="Only platform admin allowed")


@router.post("/roles", response_model=RoleRead)
async def create_role(
    payload: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:create")),
):
    repo = RoleRepository(db)
    if await repo.get_by_name(payload.name, payload.tenant_id):
        raise HTTPException(status_code=409, detail="Role name already exists for this tenant")
    role = Role(name=payload.name, tenant_id=payload.tenant_id, is_active=payload.is_active)
    created = await repo.create(role)
    await AuditLogService(db).log(current_user.user_id, payload.tenant_id, "create", "role", None, payload.model_dump())
    return RoleRead.model_validate(created)


@router.post("/permissions", response_model=PermissionRead)
async def create_permission(
    payload: PermissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:create")),
):
    if not getattr(current_user, "is_platform_admin", False):
        raise HTTPException(status_code=403, detail="Only platform admin can create permissions")
    codename = payload.codename or f"{payload.resource or payload.module}:{payload.action}"
    perm = Permission(
        name=payload.name,
        module=payload.module,
        action=payload.action,
        resource=payload.resource or payload.module,
        codename=codename,
    )
    created = await PermissionRepository(db).create(perm)
    await AuditLogService(db).log(
        current_user.user_id,
        getattr(current_user, "tenant_id", None),
        "create",
        "permission",
        None,
        payload.model_dump(),
    )
    return PermissionRead.model_validate(created)


@router.get("/roles/{role_id}/permissions", response_model=list[RolePermissionRead])
async def list_role_permissions(
    role_id: int,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = await RoleRepository(db).get_by_id(role_id)
    if not role or role.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Role not found for tenant")
    rows = await RolePermissionRepository(db).list_by_role(role_id, tenant_id)

    perm_ids = {r.permission_id for r in rows}
    perm_map: dict[int, Permission] = {}
    if perm_ids:
        from sqlalchemy import select as _select
        result = await db.execute(_select(Permission).where(Permission.id.in_(perm_ids)))
        perm_map = {p.id: p for p in result.scalars().all()}

    return [
        RolePermissionRead(
            role_id=r.role_id,
            permission_id=r.permission_id,
            permission_name=(perm_map[r.permission_id].name if r.permission_id in perm_map else None),
            permission_codename=(perm_map[r.permission_id].codename if r.permission_id in perm_map else None),
            tenant_id=r.tenant_id,
            is_override=r.is_override,
            is_granted=r.is_granted,
        )
        for r in rows
    ]


@router.post("/roles/{role_id}/permissions/add")
async def add_role_permissions(
    role_id: int,
    payload: RolePermissionAssign,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    role = await RoleRepository(db).get_by_id(role_id)
    if not role or role.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=404, detail="Role not found for tenant")
    await RolePermissionRepository(db).add_many(
        role_id,
        payload.permission_ids,
        payload.tenant_id,
        is_override=payload.is_override,
        is_granted=True,
    )
    AccessControlService(db).invalidate_permissions(payload.tenant_id)
    await AuditLogService(db).log(
        current_user.user_id,
        payload.tenant_id,
        "add",
        "role_permissions",
        None,
        payload.model_dump(),
    )
    return {"success": True}


@router.post("/roles/{role_id}/permissions/remove")
async def remove_role_permissions(
    role_id: int,
    payload: RolePermissionAssign,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    role = await RoleRepository(db).get_by_id(role_id)
    if not role or role.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=404, detail="Role not found for tenant")
    await RolePermissionRepository(db).remove_many(role_id, payload.permission_ids, payload.tenant_id)
    AccessControlService(db).invalidate_permissions(payload.tenant_id)
    await AuditLogService(db).log(
        current_user.user_id,
        payload.tenant_id,
        "remove",
        "role_permissions",
        None,
        payload.model_dump(),
    )
    return {"success": True}


@router.post("/users/{user_id}/permissions")
async def override_user_permissions(
    user_id: int,
    payload: UserPermissionOverride,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    await UserPermissionRepository(db).upsert(
        user_id=user_id,
        permission_id=payload.permission_id,
        tenant_id=payload.tenant_id,
        is_granted=payload.is_granted,
        is_allowed=payload.is_allowed,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    AccessControlService(db).invalidate_permissions(payload.tenant_id, user_id)
    await AuditLogService(db).log(
        current_user.user_id,
        payload.tenant_id,
        "override",
        "user_permissions",
        None,
        payload.model_dump(),
    )
    return {"success": True}


@router.get("/users/me/permissions", response_model=list[ResolvedPermissionRead])
async def get_my_permissions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id is None:
        # Platform-level user without a CompanyUser record (e.g. SUPER ADMIN).
        return []
    role_id = getattr(current_user, "role_id", None)
    if role_id is None:
        # Fall back to looking up by legacy role string.
        role = await RoleRepository(db).get_by_name(current_user.role, tenant_id)
        role_id = role.id if role else None
    items = await RBACService(db).resolve_permissions(
        user_id=current_user.user_id,
        role_id=role_id,
        tenant_id=tenant_id,
    )
    return [ResolvedPermissionRead(**item) for item in items]


@router.post("/policies", response_model=PolicyRead)
async def create_policy(
    payload: PolicyCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:create")),
):
    condition_json = payload.condition_json or payload.conditions or {}
    policy = Policy(
        name=payload.name,
        description=payload.description,
        module=payload.module,
        scope=payload.scope,
        conditions=payload.conditions,
        condition_json=condition_json,
        effect=payload.effect,
        tenant_id=payload.tenant_id,
        is_active=payload.is_active,
    )
    created = await PolicyRepository(db).create(policy)
    AccessControlService(db).invalidate_policies(payload.tenant_id)
    await AuditLogService(db).log(current_user.user_id, payload.tenant_id, "create", "policy", None, payload.model_dump())
    return PolicyRead.model_validate(created)


@router.get("/policies", response_model=list[PolicyRead])
async def list_policies(
    tenant_id: UUID = Query(...),
    module: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    policies = await PolicyRepository(db).list(tenant_id, module)
    return [PolicyRead.model_validate(p) for p in policies]


@router.post("/roles/{role_id}/policies/add")
async def add_role_policies(
    role_id: int,
    payload: RolePolicyAssign,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    role = await RoleRepository(db).get_by_id(role_id)
    if not role or role.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=404, detail="Role not found for tenant")
    await RolePolicyRepository(db).add_many(role_id, payload.policy_ids, payload.tenant_id)
    AccessControlService(db).invalidate_policies(payload.tenant_id)
    await AuditLogService(db).log(
        current_user.user_id,
        payload.tenant_id,
        "add",
        "role_policies",
        None,
        payload.model_dump(),
    )
    return {"success": True}


@router.post("/roles/{role_id}/policies/remove")
async def remove_role_policies(
    role_id: int,
    payload: RolePolicyAssign,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    role = await RoleRepository(db).get_by_id(role_id)
    if not role or role.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=404, detail="Role not found for tenant")
    await RolePolicyRepository(db).remove_many(role_id, payload.policy_ids, payload.tenant_id)
    AccessControlService(db).invalidate_policies(payload.tenant_id)
    await AuditLogService(db).log(
        current_user.user_id,
        payload.tenant_id,
        "remove",
        "role_policies",
        None,
        payload.model_dump(),
    )
    return {"success": True}


@router.post("/users/{user_id}/policies/add")
async def add_user_policies(
    user_id: int,
    payload: UserPolicyAssign,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    await UserPolicyRepository(db).add_many(user_id, payload.policy_ids, payload.tenant_id)
    AccessControlService(db).invalidate_policies(payload.tenant_id)
    await AuditLogService(db).log(
        current_user.user_id,
        payload.tenant_id,
        "add",
        "user_policies",
        None,
        payload.model_dump(),
    )
    return {"success": True}


@router.get("/users/me/effective-policy", response_model=EffectivePolicyResponse)
async def get_my_effective_policy(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id is None:
        # Platform-level user (no CompanyUser): default to global scope.
        return EffectivePolicyResponse(
            policy_id=None,
            name="Global Access",
            scope="global",
            conditions={},
            source="default",
        )
    role_id = getattr(current_user, "role_id", None)
    if role_id is None:
        role = await RoleRepository(db).get_by_name(current_user.role, tenant_id)
        role_id = role.id if role else None
    user_context = {
        "user_id": current_user.user_id,
        "tenant_id": tenant_id,
        "department_id": getattr(current_user, "department_id", None),
    }
    effective = await RBACService(db).resolve_effective_policy(
        user_id=current_user.user_id,
        role_id=role_id,
        tenant_id=tenant_id,
        user_context=user_context,
    )
    return EffectivePolicyResponse(**effective)


@router.get("/roles", response_model=list[RoleRead])
async def list_roles(
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    from sqlalchemy import select as _select
    from config_service.app.models.company import Company

    roles = await RoleRepository(db).list(tenant_id)
    filtered_roles = [r for r in roles if r.name != "SUPER ADMIN"]

    company_row = (
        await db.execute(_select(Company.company_name).where(Company.id == tenant_id))
    ).first()
    tenant_name = company_row[0] if company_row else None

    return [
        RoleRead(
            id=r.id,
            name=r.name,
            tenant_id=r.tenant_id,
            tenant_name=tenant_name,
            is_active=r.is_active,
        )
        for r in filtered_roles
    ]


@router.get("/roles/{role_id}", response_model=RoleRead)
async def get_role_by_id(
    role_id: int,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = await RoleRepository(db).get_by_id(role_id)
    if not role or role.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Role not found for tenant")
    return RoleRead.model_validate(role)


@router.put("/roles/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: int,
    payload: RoleUpdate,
    tenant_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    # tenant_id can be supplied via query string OR body. Body wins when
    # both are present so the API mirrors POST /roles.
    effective_tenant_id = payload.tenant_id or tenant_id
    if effective_tenant_id is None:
        raise HTTPException(
            status_code=422,
            detail="tenant_id is required (in body or query string)",
        )
    tenant_id = effective_tenant_id

    repo = RoleRepository(db)
    role = await repo.get_by_id(role_id)
    if not role or role.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Role not found for tenant")

    if payload.name and payload.name != role.name:
        existing = await repo.get_by_name(payload.name, tenant_id)
        if existing:
            raise HTTPException(status_code=409, detail="Role name already exists")
        role.name = payload.name
    if payload.is_active is not None:
        role.is_active = payload.is_active

    updated = await repo.update(role)
    await AuditLogService(db).log(
        current_user.user_id,
        tenant_id,
        "update",
        "role",
        None,
        payload.model_dump(exclude_unset=True),
    )
    return RoleRead.model_validate(updated)


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: int,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:delete")),
):
    repo = RoleRepository(db)
    role = await repo.get_by_id(role_id)
    if not role or role.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Role not found for tenant")
    protected_roles = {"ADMIN", "APPROVER", "VENDOR", "SUPER ADMIN"}
    if role.name in protected_roles:
        raise HTTPException(status_code=400, detail="Default roles cannot be deleted")
    user_repo = UserRepository(db)
    if hasattr(user_repo, "count_active_by_role"):
        active_users = await user_repo.count_active_by_role(role.name, tenant_id)
        if active_users > 0:
            raise HTTPException(status_code=400, detail="Role has active users and cannot be deleted")
    await repo.delete(role)
    await AuditLogService(db).log(
        current_user.user_id,
        tenant_id,
        "delete",
        "role",
        {"id": role_id},
        None,
    )
    return {"success": True}


@router.get("/permissions", response_model=list[PermissionRead])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not getattr(current_user, "is_platform_admin", False):
        raise HTTPException(status_code=403, detail="Only platform admin can view permissions")
    perms = await PermissionRepository(db).list()
    return [PermissionRead.model_validate(p) for p in perms]


@router.get("/permissions/{permission_id}", response_model=PermissionRead)
async def get_permission_by_id(
    permission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if not getattr(current_user, "is_platform_admin", False):
        raise HTTPException(status_code=403, detail="Only platform admin can view permissions")
    perm = await PermissionRepository(db).get_by_id(permission_id)
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    return PermissionRead.model_validate(perm)


@router.put("/permissions/{permission_id}", response_model=PermissionRead)
async def update_permission(
    permission_id: int,
    payload: PermissionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    if not getattr(current_user, "is_platform_admin", False):
        raise HTTPException(status_code=403, detail="Only platform admin can edit permissions")
    repo = PermissionRepository(db)
    perm = await repo.get_by_id(permission_id)
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")

    if payload.name is not None:
        perm.name = payload.name
    if payload.module is not None:
        perm.module = payload.module
    if payload.action is not None:
        perm.action = payload.action
    if payload.codename is not None:
        perm.codename = payload.codename
    if payload.resource is not None:
        perm.resource = payload.resource

    updated = await repo.update(perm)
    await AuditLogService(db).log(
        current_user.user_id,
        getattr(current_user, "tenant_id", None),
        "update",
        "permission",
        None,
        payload.model_dump(exclude_unset=True),
    )
    return PermissionRead.model_validate(updated)


@router.delete("/permissions/{permission_id}")
async def delete_permission(
    permission_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:delete")),
):
    if not getattr(current_user, "is_platform_admin", False):
        raise HTTPException(status_code=403, detail="Only platform admin can delete permissions")
    repo = PermissionRepository(db)
    perm = await repo.get_by_id(permission_id)
    if not perm:
        raise HTTPException(status_code=404, detail="Permission not found")
    role_perm_repo = RolePermissionRepository(db)
    in_use = await role_perm_repo.count_by_permission(permission_id)
    if in_use > 0:
        raise HTTPException(
            status_code=409,
            detail="Permission is assigned to one or more roles and cannot be deleted",
        )
    await repo.delete(perm)
    await AuditLogService(db).log(
        current_user.user_id,
        getattr(current_user, "tenant_id", None),
        "delete",
        "permission",
        {"id": permission_id},
        None,
    )
    return {"success": True}


@router.post("/menus", response_model=MenuRead)
async def create_menu(
    payload: MenuCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:create")),
):
    repo = MenuRepository(db)
    if payload.slug and await repo.get_by_slug(payload.slug):
        raise HTTPException(status_code=409, detail="Menu slug already exists")
    menu = Menu(**payload.model_dump(), tenant_id=None)
    created = await repo.create(menu)
    MenuService(db).invalidate_all()
    await AuditLogService(db).log(
        current_user.user_id, None, "create", "menu", None, payload.model_dump()
    )
    return MenuRead.model_validate(created)


@router.get("/menus", response_model=list[MenuTreeNode])
async def get_menus(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the menu tree visible to the current user.

    Platform admins see every active menu in the global catalog; per-tenant
    users see only the menus their role/user grants resolve to.
    """
    if getattr(current_user, "is_platform_admin", False):
        menus = await MenuRepository(db).list()
        return _build_menu_tree(menus)
    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=400, detail="No tenant context for user")
    role = await RoleRepository(db).get_by_name(current_user.role, tenant_id)
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    menus = await MenuService(db).resolve_menus(current_user, role.id, tenant_id)
    return _build_menu_tree(menus)


@router.get("/menus/all", response_model=list[MenuRead])
async def list_all_menus(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:read")),
):
    """Return the complete platform-wide menu catalog (active + inactive).
    Restricted to users with platform:read on the roles menu."""
    menus = await MenuRepository(db).list_all()
    return [MenuRead.model_validate(m) for m in menus]


@router.get("/menus/{menu_id}", response_model=MenuRead)
async def get_menu_by_id(
    menu_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    menu = await MenuRepository(db).get_by_id(menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")
    return MenuRead.model_validate(menu)


@router.put("/menus/{menu_id}", response_model=MenuRead)
async def update_menu(
    menu_id: int,
    payload: MenuUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    repo = MenuRepository(db)
    menu = await repo.get_by_id(menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")

    if payload.slug is not None and payload.slug != menu.slug:
        existing = await repo.get_by_slug(payload.slug)
        if existing and existing.id != menu_id:
            raise HTTPException(status_code=409, detail="Menu slug already exists")

    if payload.name is not None:
        menu.name = payload.name
    if payload.slug is not None:
        menu.slug = payload.slug
    if payload.path is not None:
        menu.path = payload.path
    if payload.parent_id is not None:
        menu.parent_id = payload.parent_id
    if payload.icon is not None:
        menu.icon = payload.icon
    if payload.order_no is not None:
        menu.order_no = payload.order_no
    if payload.is_active is not None:
        menu.is_active = payload.is_active

    updated = await repo.update(menu)
    MenuService(db).invalidate_all()
    await AuditLogService(db).log(
        current_user.user_id,
        None,
        "update",
        "menu",
        None,
        payload.model_dump(exclude_unset=True),
    )
    return MenuRead.model_validate(updated)


@router.delete("/menus/{menu_id}")
async def delete_menu(
    menu_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:delete")),
):
    repo = MenuRepository(db)
    menu = await repo.get_by_id(menu_id)
    if not menu:
        raise HTTPException(status_code=404, detail="Menu not found")
    role_menu_repo = RoleMenuRepository(db)
    in_use = await role_menu_repo.count_by_menu(menu_id)
    if in_use > 0:
        raise HTTPException(
            status_code=409,
            detail="Menu is assigned to one or more roles and cannot be deleted",
        )
    await repo.delete(menu)
    MenuService(db).invalidate_all()
    await AuditLogService(db).log(
        current_user.user_id,
        None,
        "delete",
        "menu",
        {"id": menu_id},
        None,
    )
    return {"success": True}


@router.get("/roles/{role_id}/menus", response_model=list[RoleMenuRead])
async def list_role_menus(
    role_id: int,
    tenant_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    role = await RoleRepository(db).get_by_id(role_id)
    if not role or role.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Role not found for tenant")
    rows = await RoleMenuRepository(db).list_by_role(role_id, tenant_id)

    menu_ids = {r.menu_id for r in rows}
    menu_map: dict[int, Menu] = {}
    if menu_ids:
        from sqlalchemy import select as _select
        result = await db.execute(_select(Menu).where(Menu.id.in_(menu_ids)))
        menu_map = {m.id: m for m in result.scalars().all()}

    return [
        RoleMenuRead(
            role_id=r.role_id,
            menu_id=r.menu_id,
            menu_name=(menu_map[r.menu_id].name if r.menu_id in menu_map else None),
            menu_slug=(menu_map[r.menu_id].slug if r.menu_id in menu_map else None),
            tenant_id=r.tenant_id,
            access_level=r.access_level,
        )
        for r in rows
    ]


@router.post("/roles/{role_id}/menus/add")
async def add_role_menus(
    role_id: int,
    payload: RoleMenuAssign,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    role = await RoleRepository(db).get_by_id(role_id)
    if not role or role.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=404, detail="Role not found for tenant")
    items = payload.resolved_items()
    if not items:
        raise HTTPException(status_code=400, detail="No menus provided")
    await RoleMenuRepository(db).upsert_items(
        role_id,
        [(it.menu_id, it.access_level) for it in items],
        payload.tenant_id,
    )
    MenuService(db).invalidate(payload.tenant_id)
    await AuditLogService(db).log(
        current_user.user_id,
        payload.tenant_id,
        "add",
        "role_menus",
        None,
        payload.model_dump(),
    )
    return {"success": True}


@router.post("/roles/{role_id}/menus/remove")
async def remove_role_menus(
    role_id: int,
    payload: RoleMenuAssign,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    role = await RoleRepository(db).get_by_id(role_id)
    if not role or role.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=404, detail="Role not found for tenant")
    items = payload.resolved_items()
    menu_ids = [it.menu_id for it in items] if items else (payload.menu_ids or [])
    if not menu_ids:
        raise HTTPException(status_code=400, detail="No menus provided")
    await RoleMenuRepository(db).remove_many(role_id, menu_ids, payload.tenant_id)
    MenuService(db).invalidate(payload.tenant_id)
    await AuditLogService(db).log(
        current_user.user_id,
        payload.tenant_id,
        "remove",
        "role_menus",
        None,
        payload.model_dump(),
    )
    return {"success": True}


@router.post("/users/{user_id}/menus")
async def assign_user_menu(
    user_id: int,
    payload: UserMenuAssign,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("platform:update")),
):
    items = payload.resolved_items()
    if not items:
        raise HTTPException(status_code=400, detail="No menus provided")
    await UserMenuRepository(db).upsert_items(
        user_id,
        [(it.menu_id, it.access_level, it.is_active) for it in items],
        payload.tenant_id,
    )
    MenuService(db).invalidate(payload.tenant_id, user_id)
    await AuditLogService(db).log(
        current_user.user_id,
        payload.tenant_id,
        "assign",
        "user_menus",
        None,
        payload.model_dump(),
    )
    return {"success": True}


@router.get("/users/me/accessible-menus", response_model=list[AccessibleMenuRead])
async def get_my_accessible_menus(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id is None:
        # Platform-level user (no CompanyUser record).
        return []
    role_id = getattr(current_user, "role_id", None)
    if role_id is None:
        role = await RoleRepository(db).get_by_name(current_user.role, tenant_id)
        role_id = role.id if role else None
    items = await RBACService(db).resolve_accessible_menus(
        user_id=current_user.user_id,
        role_id=role_id,
        tenant_id=tenant_id,
    )
    return [AccessibleMenuRead(**item) for item in items]
