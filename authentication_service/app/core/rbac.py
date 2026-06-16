from __future__ import annotations
"""Access-control dependencies for FastAPI endpoints.

Two patterns are supported:

* :func:`require_permission` — RECOMMENDED. Permission-codename gating only.
  Menus are pure UI navigation; API access is granted via per-role / per-user
  permission rows that are fully managed from the admin UI.

* :func:`require_access` — DEPRECATED. Combined menu_slug + permission gating
  retained for backwards-compatibility with existing call sites that still
  reference a menu slug. Forwards to the same building blocks.

Both dependencies return an :class:`AccessContext` with the resolved
``policy_scope`` so downstream queries can filter by tenant / department /
self where applicable.
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.db import get_db
from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.rbac_constants import (
    MenuAccessLevel,
    is_at_least,
)
from authentication_service.app.repositories.role_repo import RoleRepository
from authentication_service.app.schemas.access_control import AccessContext
from authentication_service.app.services.rbac_service import RBACService


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_tenant_id(current_user) -> Optional[UUID]:
    return getattr(current_user, "tenant_id", None)


def _resolve_role_name(current_user) -> Optional[str]:
    role = getattr(current_user, "role", None)
    if role is None:
        return None
    return str(role)


async def _resolve_role_id(
    db: AsyncSession,
    role_name: Optional[str],
    tenant_id: Optional[UUID],
) -> Optional[int]:
    if not role_name or tenant_id is None:
        return None
    role = await RoleRepository(db).get_by_name(role_name, tenant_id)
    return role.id if role else None


def _platform_admin_context(current_user, role_name: Optional[str]) -> AccessContext:
    """Build the AccessContext for a platform admin.

    Platform admins act across every tenant. We short-circuit RBAC entirely
    and signal "no filter" to downstream code via an empty policy_scope.
    """
    return AccessContext(
        user_id=current_user.user_id,
        role=role_name or "",
        email=getattr(current_user, "email", None),
        tenant_id=getattr(current_user, "tenant_id", None),
        menu_access_level=MenuAccessLevel.FULL.value,
        granted_permissions=[],
        policy_scope={},
        is_platform_admin=True,
    )


async def _resolve_runtime_context(
    db: AsyncSession,
    current_user,
    *,
    apply_policy: bool,
) -> tuple[set[str], dict, Optional[int], Optional[UUID], Optional[str]]:
    """Resolve everything a non-platform-admin endpoint needs.

    Returns a tuple of (granted_permissions, policy_scope, role_id,
    tenant_id, role_name). Values are computed once and reused so individual
    dependencies don't issue duplicate queries.
    """
    tenant_id = _resolve_tenant_id(current_user)
    role_name = _resolve_role_name(current_user)
    role_id = await _resolve_role_id(db, role_name, tenant_id)

    rbac = RBACService(db)

    granted: set[str] = set()
    if tenant_id is not None:
        granted = await rbac.resolve_granted_permission_codenames(
            user_id=current_user.user_id,
            role_id=role_id,
            tenant_id=tenant_id,
        )

    policy_scope: dict = {}
    if apply_policy and tenant_id is not None:
        user_context = {
            "user_id": current_user.user_id,
            "tenant_id": tenant_id,
            "department_id": getattr(current_user, "department_id", None),
        }
        effective = await rbac.resolve_effective_policy(
            user_id=current_user.user_id,
            role_id=role_id,
            tenant_id=tenant_id,
            user_context=user_context,
        )
        policy_scope = effective.get("conditions") or {}

    return granted, policy_scope, role_id, tenant_id, role_name


def _build_access_context(
    current_user,
    *,
    role_name: Optional[str],
    tenant_id: Optional[UUID],
    granted: set[str],
    policy_scope: dict,
    menu_access_level: str,
) -> AccessContext:
    return AccessContext(
        user_id=current_user.user_id,
        role=role_name or "",
        email=getattr(current_user, "email", None),
        tenant_id=tenant_id,
        menu_access_level=menu_access_level,
        granted_permissions=sorted(granted),
        policy_scope=policy_scope,
        is_platform_admin=bool(getattr(current_user, "is_platform_admin", False)),
    )


# ---------------------------------------------------------------------------
# Public dependencies
# ---------------------------------------------------------------------------


def require_permission(
    required_permission: str,
    *,
    apply_policy: bool = True,
):
    """Permission-codename access gate (RECOMMENDED).

    The endpoint passes if (in order):
      1. The caller is a platform admin (``is_platform_admin`` JWT claim).
      2. ``required_permission`` is in the caller's resolved permission set
         (role + user overrides, see :class:`RBACService`).

    Layer-1 menu access_level is intentionally NOT checked. Menus are pure
    UI navigation metadata; API authorization is permission-driven and
    fully manageable from the admin UI via
    ``POST /api/v1/auth/roles/{id}/permissions/add`` and the user-override
    endpoints.

    Layer-3 policy scope (tenant / department / self) is still resolved when
    ``apply_policy=True`` so downstream queries can apply correct filters
    via the returned :class:`AccessContext`.

    Args:
        required_permission: Permission codename, e.g. ``"kpis:read"``.
        apply_policy: When True (default), compute the effective policy
            and populate ``AccessContext.policy_scope``. Set False for
            endpoints that don't need scope filtering.

    Raises:
        HTTPException 403: When the caller doesn't hold ``required_permission``.
    """

    if not required_permission or not isinstance(required_permission, str):
        raise ValueError("required_permission must be a non-empty string")

    async def dependency(
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_user),
    ) -> AccessContext:
        if getattr(current_user, "is_platform_admin", False):
            return _platform_admin_context(
                current_user, _resolve_role_name(current_user)
            )

        granted, policy_scope, _role_id, tenant_id, role_name = (
            await _resolve_runtime_context(
                db, current_user, apply_policy=apply_policy
            )
        )

        if required_permission not in granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission '{required_permission}'",
            )

        return _build_access_context(
            current_user,
            role_name=role_name,
            tenant_id=tenant_id,
            granted=granted,
            policy_scope=policy_scope,
            # Layer-1 not enforced here; surface "full" so downstream code
            # treating menu_access_level as a hint isn't misled into thinking
            # the user has no menu access.
            menu_access_level=MenuAccessLevel.FULL.value,
        )

    return dependency


def require_access(
    menu_slug: str,
    required_level: str = "view",
    required_permission: Optional[str] = None,
    apply_policy: bool = True,
):
    """DEPRECATED. Combined menu_slug + permission gate.

    Retained for backwards compatibility. New code should use
    :func:`require_permission` and rely on UI-managed permission grants.

    The endpoint passes if (in order):
      1. The caller is a platform admin.
      2. The caller's resolved menu access_level on ``menu_slug`` is at
         least ``required_level``.
      3. ``required_permission`` (if supplied) is in the caller's granted set.
    """

    if required_level not in (
        MenuAccessLevel.VIEW.value,
        MenuAccessLevel.FULL.value,
    ):
        raise ValueError(
            f"required_level must be 'view' or 'full', got '{required_level}'"
        )

    async def dependency(
        db: AsyncSession = Depends(get_db),
        current_user=Depends(get_current_user),
    ) -> AccessContext:
        if getattr(current_user, "is_platform_admin", False):
            return _platform_admin_context(
                current_user, _resolve_role_name(current_user)
            )

        granted, policy_scope, role_id, tenant_id, role_name = (
            await _resolve_runtime_context(
                db, current_user, apply_policy=apply_policy
            )
        )

        rbac = RBACService(db)

        # Layer 1: menu access level
        if tenant_id is not None:
            menu_access_level = await rbac.resolve_menu_access_level(
                user_id=current_user.user_id,
                role_id=role_id,
                tenant_id=tenant_id,
                menu_slug=menu_slug,
            )
        else:
            menu_access_level = MenuAccessLevel.NONE.value

        if not is_at_least(menu_access_level, required_level):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Menu '{menu_slug}' requires access level "
                    f"'{required_level}', got '{menu_access_level}'"
                ),
            )

        # Layer 2: permission codename (optional)
        if required_permission and required_permission not in granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission '{required_permission}'",
            )

        return _build_access_context(
            current_user,
            role_name=role_name,
            tenant_id=tenant_id,
            granted=granted,
            policy_scope=policy_scope,
            menu_access_level=menu_access_level,
        )

    return dependency
