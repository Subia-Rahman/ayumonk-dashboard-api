from __future__ import annotations
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.rbac_constants import (
    MENU_SLUG_TO_RESOURCE,
    MenuAccessLevel,
    POLICY_SCOPE_RANK,
    PolicyScope,
    access_level_to_permissions,
)
from authentication_service.app.repositories.menu_repo import MenuRepository
from authentication_service.app.repositories.permission_repo import PermissionRepository
from authentication_service.app.repositories.policy_repo import PolicyRepository
from authentication_service.app.repositories.role_menu_repo import RoleMenuRepository
from authentication_service.app.repositories.role_permission_repo import RolePermissionRepository
from authentication_service.app.repositories.role_policy_repo import RolePolicyRepository
from authentication_service.app.repositories.role_repo import RoleRepository
from authentication_service.app.repositories.user_menu_repo import UserMenuRepository
from authentication_service.app.repositories.user_permission_repo import UserPermissionRepository
from authentication_service.app.repositories.user_policy_repo import UserPolicyRepository


class RBACService:
    """3-layer RBAC resolution: menus, permissions, policies.

    Resolution is computed at runtime from the database; never cached, so
    role/user overrides take effect immediately.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.role_repo = RoleRepository(db)
        self.menu_repo = MenuRepository(db)
        self.role_menu_repo = RoleMenuRepository(db)
        self.user_menu_repo = UserMenuRepository(db)
        self.permission_repo = PermissionRepository(db)
        self.role_perm_repo = RolePermissionRepository(db)
        self.user_perm_repo = UserPermissionRepository(db)
        self.policy_repo = PolicyRepository(db)
        self.role_policy_repo = RolePolicyRepository(db)
        self.user_policy_repo = UserPolicyRepository(db)

    # ------------------------------------------------------------------
    # Layer 1: Menu access resolution
    # ------------------------------------------------------------------
    async def resolve_accessible_menus(
        self,
        user_id: int,
        role_id: Optional[int],
        tenant_id: UUID,
    ) -> list[dict]:
        menus = await self.menu_repo.list()
        menu_map = {m.id: m for m in menus}

        role_levels: dict[int, str] = {}
        if role_id is not None:
            for rm in await self.role_menu_repo.list_by_role(role_id, tenant_id):
                role_levels[rm.menu_id] = rm.access_level

        user_levels: dict[int, tuple[str, bool]] = {}
        for um in await self.user_menu_repo.list_by_user(user_id, tenant_id):
            user_levels[um.menu_id] = (um.access_level, um.is_active)

        merged: list[dict] = []
        for menu_id, menu in menu_map.items():
            source = "role"
            level = role_levels.get(menu_id, MenuAccessLevel.NONE.value)
            if menu_id in user_levels:
                u_level, u_active = user_levels[menu_id]
                if not u_active:
                    level = MenuAccessLevel.NONE.value
                else:
                    level = u_level
                source = "user_override"
            if level == MenuAccessLevel.NONE.value:
                continue
            merged.append(
                {
                    "menu_id": menu.id,
                    "menu_name": menu.name,
                    "slug": menu.slug,
                    "order_no": menu.order_no or 0,
                    "access_level": level,
                    "source": source,
                }
            )
        merged.sort(key=lambda x: (x["order_no"], x["menu_name"] or ""))
        return merged

    async def resolve_menu_access_level(
        self,
        user_id: int,
        role_id: Optional[int],
        tenant_id: UUID,
        menu_slug: str,
    ) -> str:
        menu = await self.menu_repo.get_by_slug(menu_slug)
        if menu is None:
            return MenuAccessLevel.NONE.value

        role_level = MenuAccessLevel.NONE.value
        if role_id is not None:
            for rm in await self.role_menu_repo.list_by_role(role_id, tenant_id):
                if rm.menu_id == menu.id:
                    role_level = rm.access_level
                    break

        for um in await self.user_menu_repo.list_by_user(user_id, tenant_id):
            if um.menu_id == menu.id:
                if not um.is_active:
                    return MenuAccessLevel.NONE.value
                return um.access_level
        return role_level

    # ------------------------------------------------------------------
    # Layer 2: Permission resolution
    # ------------------------------------------------------------------
    async def resolve_permissions(
        self,
        user_id: int,
        role_id: Optional[int],
        tenant_id: UUID,
    ) -> list[dict]:
        """Return resolved permissions with provenance.

        Priority (highest first):
          1. UserPermission   (source: user_override)
          2. RolePermission with is_override=True   (source: role_override)
          3. RolePermission with is_override=False  (source: role_override) - explicit role grant
          4. RoleMenu access_level expansion         (source: role_menu)
        """
        permissions = await self.permission_repo.list()
        codename_index: dict[str, "Permission"] = {}
        id_index: dict[int, "Permission"] = {}
        for p in permissions:
            id_index[p.id] = p
            cn = p.codename or self._codename_from_permission(p)
            codename_index[cn] = p

        resolved: dict[str, dict] = {}

        # Layer 4: auto-resolve from RoleMenu access_level
        if role_id is not None:
            menu_map = {m.id: m for m in await self.menu_repo.list()}
            for rm in await self.role_menu_repo.list_by_role(role_id, tenant_id):
                menu = menu_map.get(rm.menu_id)
                if not menu:
                    continue
                resource = MENU_SLUG_TO_RESOURCE.get(menu.slug or "")
                if not resource:
                    continue
                for cn in access_level_to_permissions(resource, rm.access_level):
                    resolved[cn] = {
                        "codename": cn,
                        "source": "role_menu",
                        "is_granted": True,
                    }

        # Layer 3: explicit RolePermission grants
        if role_id is not None:
            for rp in await self.role_perm_repo.list_by_role(role_id, tenant_id):
                perm = id_index.get(rp.permission_id)
                if not perm:
                    continue
                cn = perm.codename or self._codename_from_permission(perm)
                resolved[cn] = {
                    "codename": cn,
                    "source": "role_override",
                    "is_granted": bool(rp.is_granted),
                }

        # Layer 1: UserPermission overrides (highest priority)
        for up in await self.user_perm_repo.list_by_user(user_id, tenant_id):
            perm = id_index.get(up.permission_id)
            if not perm:
                continue
            cn = perm.codename or self._codename_from_permission(perm)
            granted = bool(getattr(up, "is_granted", up.is_allowed))
            resolved[cn] = {
                "codename": cn,
                "source": "user_override",
                "is_granted": granted,
            }

        return sorted(resolved.values(), key=lambda x: x["codename"])

    async def resolve_granted_permission_codenames(
        self,
        user_id: int,
        role_id: Optional[int],
        tenant_id: UUID,
    ) -> set[str]:
        items = await self.resolve_permissions(user_id, role_id, tenant_id)
        return {item["codename"] for item in items if item["is_granted"]}

    @staticmethod
    def _codename_from_permission(perm) -> str:
        resource = perm.resource or perm.module
        return f"{resource}:{perm.action}"

    # ------------------------------------------------------------------
    # Layer 3: Policy resolution
    # ------------------------------------------------------------------
    async def resolve_effective_policy(
        self,
        user_id: int,
        role_id: Optional[int],
        tenant_id: UUID,
        user_context: Optional[dict] = None,
    ) -> dict:
        """Returns the resolved effective policy for the user.

        - User-level policy overrides role-level.
        - When multiple policies are applicable, the most restrictive scope wins.
        - Conditions are materialized using the user_context (e.g. department_id).
        """
        user_context = user_context or {}

        user_policy_rows = await self.user_policy_repo.list_by_user(user_id, tenant_id)
        if user_policy_rows:
            policies = await self.policy_repo.list_by_ids(
                [row.policy_id for row in user_policy_rows]
            )
            chosen = self._most_restrictive(policies)
            if chosen:
                return self._materialize_policy(chosen, user_context, source="user")

        if role_id is not None:
            role_policy_rows = await self.role_policy_repo.list_by_role(role_id, tenant_id)
            if role_policy_rows:
                policies = await self.policy_repo.list_by_ids(
                    [row.policy_id for row in role_policy_rows]
                )
                chosen = self._most_restrictive(policies)
                if chosen:
                    return self._materialize_policy(chosen, user_context, source="role")

        return {
            "policy_id": None,
            "name": None,
            "scope": PolicyScope.SELF.value,
            "conditions": {"user_id": user_context.get("user_id")},
            "source": "default",
        }

    @staticmethod
    def _most_restrictive(policies: list) -> Optional[object]:
        scoped = [p for p in policies if getattr(p, "scope", None) and p.is_active]
        if not scoped:
            return next((p for p in policies if p.is_active), None)
        return max(scoped, key=lambda p: POLICY_SCOPE_RANK.get(p.scope, -1))

    @staticmethod
    def _materialize_policy(policy, user_context: dict, source: str) -> dict:
        raw_conditions = policy.conditions or {}
        materialized = {}
        for k, v in raw_conditions.items():
            if isinstance(v, str) and v.startswith("user."):
                ctx_key = v.split(".", 1)[1]
                materialized[k] = user_context.get(ctx_key)
            else:
                materialized[k] = v
        return {
            "policy_id": policy.id,
            "name": policy.name,
            "scope": policy.scope,
            "conditions": materialized,
            "source": source,
        }
