from __future__ import annotations
"""Auth dependencies for the Wellness Dimension configuration endpoints.

Access rules (per the spec):
  * Platform admin (Super Admin / Ayumonk Admin) — full access.
  * Company admin / HR admin — full access. The dimensions catalog is a global
    configuration (no `company_id` column), so there is no per-row tenant
    scoping; `company_id` from the JWT is recorded only on `created_by` /
    `updated_by` audit fields.
  * Employee — HTTP 403 on all endpoints.

The legacy auth role string is the source of truth for the gate; the RBAC
role_id is consulted only as a fallback when the legacy role is "USER" (which
on its own is ambiguous between Employee, HR Manager, and CXO).
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.rbac_constants import PLATFORM_LEGACY_ROLES
from authentication_service.app.repositories.role_repo import RoleRepository
from authentication_service.app.schemas.auth import TokenUser
from config_service.app.core.db import get_db
from config_service.app.repositories.company_users import UserRepository


# Public role identifiers, same vocabulary as cxo_metrics_dependencies.
ROLE_SUPER_ADMIN = "super_admin"
ROLE_AYUMONK_ADMIN = "ayumonk_admin"
ROLE_ADMIN = "admin"
ROLE_HR = "hr"
ROLE_CXO = "cxo"
ROLE_EMPLOYEE = "employee"


DIMENSIONS_ALLOWED_ROLES = {
    ROLE_SUPER_ADMIN,
    ROLE_AYUMONK_ADMIN,
    ROLE_ADMIN,
    ROLE_HR,
}


class DimensionAccessContext:
    """Resolved access context for wellness-dimension endpoints. Lightweight,
    never serialized — `tenant_id` is captured so the endpoint can record the
    actor's company on audit fields if it ever needs to."""

    def __init__(
        self,
        *,
        current_user: TokenUser,
        is_platform_admin: bool,
        resolved_role: str,
        tenant_id: Optional[UUID],
    ):
        self.current_user = current_user
        self.is_platform_admin = is_platform_admin
        self.resolved_role = resolved_role
        self.tenant_id = tenant_id


async def _resolve_role(
    db: AsyncSession, current_user: TokenUser
) -> tuple[str, bool, Optional[UUID]]:
    """Map the caller onto one of the public role identifiers above. Returns
    (resolved_role, is_platform_admin, tenant_id)."""
    if getattr(current_user, "is_platform_admin", False):
        legacy = (current_user.role or "").upper()
        if legacy in ("AYUMONK ADMIN", "AYUMONKADMIN"):
            return ROLE_AYUMONK_ADMIN, True, None
        return ROLE_SUPER_ADMIN, True, None

    legacy = (current_user.role or "").upper()
    if legacy in PLATFORM_LEGACY_ROLES:
        return ROLE_SUPER_ADMIN, True, None

    requester = await UserRepository(db).get_by_email(current_user.email)
    tenant_id: Optional[UUID] = requester.company_id if requester else None

    if legacy == "ADMIN":
        return ROLE_ADMIN, False, tenant_id

    role_id = requester.role_id if requester else None
    if role_id is not None:
        role = await RoleRepository(db).get_by_id(role_id)
        if role is not None:
            name = (role.name or "").strip().lower()
            if name == "company admin":
                return ROLE_ADMIN, False, tenant_id
            if name == "hr manager":
                return ROLE_HR, False, tenant_id
            if name == "cxo":
                return ROLE_CXO, False, tenant_id
            if name == "employee":
                return ROLE_EMPLOYEE, False, tenant_id

    # Unknown role — fall through; the gate below will reject.
    return ROLE_EMPLOYEE if legacy == "USER" else "", False, tenant_id


async def require_dimensions_access(
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
) -> DimensionAccessContext:
    """Single dependency for all wellness-dimension endpoints. Allows platform
    admins, company admins, and HR; everyone else (including employees) gets
    403."""
    resolved_role, is_platform, tenant_id = await _resolve_role(db, current_user)
    if resolved_role not in DIMENSIONS_ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Role '{resolved_role or 'unknown'}' is not permitted to access "
                "wellness dimension configuration"
            ),
        )
    return DimensionAccessContext(
        current_user=current_user,
        is_platform_admin=is_platform,
        resolved_role=resolved_role,
        tenant_id=tenant_id,
    )
