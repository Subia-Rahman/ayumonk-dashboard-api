"""Bridge dependencies that combine legacy auth (User by email) with the
3-layer RBAC architecture defined in authentication_service.

The legacy JWT carries `role` (ADMIN / SUPER ADMIN / USER) and `email`, but
not `tenant_id` / `department_id`. To run the RBAC checks we look up the
requester in `CompanyUser` by email to recover their `company_id` (tenant),
`department_id`, and assigned `role_id`, then evaluate menu / permission /
policy on that context.

Use `require_company_users_access(menu_slug, required_level, required_permission)`
from a FastAPI route to:
  * Layer 1 – assert menu access >= required_level
  * Layer 2 – assert required_permission is granted
  * Layer 3 – materialize the active policy scope into a `CompanyUsersAccess`
              object that endpoints can use to filter records.
"""

from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.rbac_constants import (
    MenuAccessLevel,
    PLATFORM_LEGACY_ROLES,
    is_at_least,
)
from authentication_service.app.repositories.role_repo import RoleRepository
from authentication_service.app.schemas.auth import TokenUser
from authentication_service.app.services.rbac_service import RBACService

from config_service.app.core.db import get_db
from config_service.app.models.company_users import CompanyUser
from config_service.app.repositories.company_users import UserRepository


SUPER_ADMIN_LEGACY_ROLES = PLATFORM_LEGACY_ROLES


# Fallback mapping for users whose CompanyUser record has no role_id assigned
# yet (e.g. legacy data created before role_id was added to the schema).
LEGACY_TO_RBAC_ROLE = {
    "ADMIN": "Company Admin",
    "USER": "Employee",
}


@dataclass
class CompanyUsersAccess:
    """Resolved RBAC context for company_users endpoints."""

    current_user: TokenUser
    tenant_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    requester_company_user_id: Optional[UUID] = None
    role_id: Optional[int] = None
    menu_access_level: str = MenuAccessLevel.NONE.value
    granted_permissions: list[str] = field(default_factory=list)
    policy_scope: dict = field(default_factory=dict)
    policy_name: Optional[str] = None
    is_super_admin: bool = False

    def effective_company_id(self, requested: Optional[UUID] = None) -> Optional[UUID]:
        """Return the company_id that records must be scoped to.

        - Super admins / global scope: return the requested override (or None
          for "see everything").
        - Tenant / department / self: forced to the requester's tenant.
        """
        if self.is_super_admin:
            return requested
        scope_tenant = self.policy_scope.get("tenant_id")
        if scope_tenant is None:
            return requested
        return scope_tenant

    def effective_department_id(self) -> Optional[UUID]:
        return self.policy_scope.get("department_id")

    def restrict_to_self_id(self) -> Optional[UUID]:
        """When the policy scope is self-only, return the CompanyUser id of
        the requester so the caller can scope queries down to that single row.
        """
        if self.policy_scope.get("user_id") is None:
            return None
        return self.requester_company_user_id

    def assert_record_in_scope(
        self,
        *,
        record_company_id: UUID,
        record_department_id: Optional[UUID],
        record_id: UUID,
    ) -> None:
        """Raise 403 if a fetched CompanyUser row doesn't satisfy the active
        policy scope."""
        if self.is_super_admin:
            return
        eff_company = self.policy_scope.get("tenant_id")
        if eff_company is not None and record_company_id != eff_company:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Record outside your tenant scope",
            )
        eff_dept = self.policy_scope.get("department_id")
        if eff_dept is not None and record_department_id != eff_dept:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Record outside your department scope",
            )
        self_id = self.restrict_to_self_id()
        if self_id is not None and record_id != self_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Record outside your self scope",
            )


async def _resolve_requester(
    db: AsyncSession,
    current_user: TokenUser,
) -> tuple[Optional[CompanyUser], bool]:
    legacy_role = (current_user.role or "").upper()
    is_super = legacy_role in SUPER_ADMIN_LEGACY_ROLES or bool(
        getattr(current_user, "is_platform_admin", False)
    )
    if is_super:
        return None, True
    record = await UserRepository(db).get_by_email(current_user.email)
    return record, False


async def _resolve_role_id_for_requester(
    db: AsyncSession,
    requester: CompanyUser,
    legacy_role: str,
    tenant_id: UUID,
) -> Optional[int]:
    """Prefer the role_id stored on CompanyUser; fall back to mapping the
    legacy auth role to a seeded RBAC role name."""
    if getattr(requester, "role_id", None) is not None:
        return requester.role_id
    rbac_role_name = LEGACY_TO_RBAC_ROLE.get(legacy_role.upper(), legacy_role)
    role_row = await RoleRepository(db).get_by_name(rbac_role_name, tenant_id)
    return role_row.id if role_row else None


def require_company_users_access(
    menu_slug: str = "company-users",
    required_level: str = "view",
    required_permission: Optional[str] = None,
):
    """Dependency factory enforcing menu + permission + policy for the
    company_users domain. Returns a `CompanyUsersAccess` with the resolved
    scope filters ready to be applied by the endpoint.
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
        current_user: TokenUser = Depends(get_current_user),
    ) -> CompanyUsersAccess:
        requester_record, is_super = await _resolve_requester(db, current_user)

        # Super admins (platform) bypass menu/permission/policy gating —
        # they get global scope.
        if is_super:
            return CompanyUsersAccess(
                current_user=current_user,
                tenant_id=None,
                department_id=None,
                requester_company_user_id=None,
                role_id=None,
                menu_access_level=MenuAccessLevel.FULL.value,
                granted_permissions=[],
                policy_scope={},
                policy_name="Global Access",
                is_super_admin=True,
            )

        if requester_record is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No company record for current user",
            )

        tenant_id: UUID = requester_record.company_id
        if tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Current user has no tenant assignment",
            )

        role_id = await _resolve_role_id_for_requester(
            db, requester_record, current_user.role or "", tenant_id
        )

        rbac = RBACService(db)

        # Layer 1: menu access
        menu_level = await rbac.resolve_menu_access_level(
            user_id=current_user.user_id,
            role_id=role_id,
            tenant_id=tenant_id,
            menu_slug=menu_slug,
        )
        if not is_at_least(menu_level, required_level):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Menu '{menu_slug}' requires access level "
                    f"'{required_level}', got '{menu_level}'"
                ),
            )

        # Layer 2: permission
        granted = await rbac.resolve_granted_permission_codenames(
            user_id=current_user.user_id,
            role_id=role_id,
            tenant_id=tenant_id,
        )
        if required_permission and required_permission not in granted:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission '{required_permission}'",
            )

        # Layer 3: effective policy scope
        user_context = {
            "user_id": current_user.user_id,
            "tenant_id": tenant_id,
            "department_id": requester_record.department_id,
        }
        effective = await rbac.resolve_effective_policy(
            user_id=current_user.user_id,
            role_id=role_id,
            tenant_id=tenant_id,
            user_context=user_context,
        )

        return CompanyUsersAccess(
            current_user=current_user,
            tenant_id=tenant_id,
            department_id=requester_record.department_id,
            requester_company_user_id=requester_record.id,
            role_id=role_id,
            menu_access_level=menu_level,
            granted_permissions=sorted(granted),
            policy_scope=effective.get("conditions") or {},
            policy_name=effective.get("name"),
            is_super_admin=False,
        )

    return dependency
