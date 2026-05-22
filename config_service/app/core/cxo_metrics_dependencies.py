"""Auth dependencies specific to the CXO metric endpoints.

The base project uses three overlapping role identifiers:

* `is_platform_admin` JWT claim — Super Admin / Ayumonk Admin (cross-tenant).
* legacy `user.role` string — "ADMIN" / "USER" + the platform legacy variants
  ("SUPER ADMIN", "AYUMONK ADMIN", ...).
* RBAC role name resolved via `company_users.role_id` — "Company Admin",
  "CXO", "HR Manager", "Employee".

The CXO endpoints are spec'd in terms of the public role names
(`super_admin`, `ayumonk_admin`, `admin`, `hr`, `cxo`), so this module
translates between those and what's actually on the TokenUser.

Three dependencies are exposed:

* `require_cxo_metrics_read` — platform admins + company admins. Company
  admins are scoped to their own tenant (raises 403 if `company_id` query
  param mismatches their tenant).
* `require_cxo_metrics_write` — platform admins only.
* `require_cxo_dashboard_access` — platform admins + company admins + CXO +
  HR Manager. Non-platform callers are forced onto their own company_id (the
  endpoint overrides the query param, see the router).
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.rbac_constants import PLATFORM_LEGACY_ROLES
from authentication_service.app.repositories.role_repo import RoleRepository
from authentication_service.app.schemas.auth import TokenUser
from config_service.app.core.db import get_db
from config_service.app.repositories.company_users import UserRepository


# Public role identifiers as they appear in the spec.
ROLE_SUPER_ADMIN = "super_admin"
ROLE_AYUMONK_ADMIN = "ayumonk_admin"
ROLE_ADMIN = "admin"
ROLE_HR = "hr"
ROLE_CXO = "cxo"

CXO_READ_ROLES = {ROLE_SUPER_ADMIN, ROLE_AYUMONK_ADMIN, ROLE_ADMIN}
CXO_WRITE_ROLES = {ROLE_SUPER_ADMIN, ROLE_AYUMONK_ADMIN}
CXO_DASHBOARD_ROLES = {
    ROLE_SUPER_ADMIN,
    ROLE_AYUMONK_ADMIN,
    ROLE_ADMIN,
    ROLE_HR,
    ROLE_CXO,
}


class CxoAccessContext:
    """Resolved access context for CXO endpoints. Lightweight (not a Pydantic
    model) — never serialized over the wire."""

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


async def _resolve_role(db: AsyncSession, current_user: TokenUser) -> tuple[str, bool, Optional[UUID]]:
    """Map the caller to one of the public role identifiers above.

    Returns (resolved_role, is_platform_admin, tenant_id). For non-platform
    users tenant_id comes from company_users (since the legacy JWT doesn't
    always carry it).
    """
    if getattr(current_user, "is_platform_admin", False):
        legacy = (current_user.role or "").upper()
        if legacy == "AYUMONK ADMIN" or legacy == "AYUMONKADMIN":
            return ROLE_AYUMONK_ADMIN, True, None
        return ROLE_SUPER_ADMIN, True, None

    legacy = (current_user.role or "").upper()
    if legacy in PLATFORM_LEGACY_ROLES:
        # Token didn't carry the flag but the legacy role string is platform.
        return ROLE_SUPER_ADMIN, True, None

    requester = await UserRepository(db).get_by_email(current_user.email)
    tenant_id: Optional[UUID] = requester.company_id if requester else None

    # First-pass: legacy "ADMIN" maps to Company Admin per LEGACY_TO_RBAC_ROLE.
    if legacy == "ADMIN":
        return ROLE_ADMIN, False, tenant_id

    # Fall back to looking up the RBAC role name via role_id.
    role_id = requester.role_id if requester else None
    if role_id is not None and tenant_id is not None:
        role = await RoleRepository(db).get_by_id(role_id)
        if role is not None:
            name = (role.name or "").strip().lower()
            if name == "company admin":
                return ROLE_ADMIN, False, tenant_id
            if name == "cxo":
                return ROLE_CXO, False, tenant_id
            if name == "hr manager":
                return ROLE_HR, False, tenant_id

    # Unknown role — caller will be rejected by the role-set check downstream.
    return "", False, tenant_id


def _assert_role(resolved_role: str, allowed: set[str], *, action: str) -> None:
    if resolved_role not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{resolved_role or 'unknown'}' is not permitted to {action}",
        )


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


async def require_cxo_metrics_read(
    company_id: UUID = Query(..., description="Target company_id"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
) -> CxoAccessContext:
    """Read access for /cxo-metrics endpoints. The `company_id` query param is
    mandatory. Company admins are restricted to their own tenant."""
    resolved_role, is_platform, tenant_id = await _resolve_role(db, current_user)
    _assert_role(resolved_role, CXO_READ_ROLES, action="read CXO mappings")

    if not is_platform:
        if tenant_id is None or tenant_id != company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="company_id does not match your tenant",
            )

    return CxoAccessContext(
        current_user=current_user,
        is_platform_admin=is_platform,
        resolved_role=resolved_role,
        tenant_id=tenant_id,
    )


async def require_cxo_metrics_read_no_company(
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
) -> CxoAccessContext:
    """Variant for endpoints without a company_id (e.g. GET /cxo-metrics)."""
    resolved_role, is_platform, tenant_id = await _resolve_role(db, current_user)
    _assert_role(resolved_role, CXO_READ_ROLES, action="read CXO mappings")
    return CxoAccessContext(
        current_user=current_user,
        is_platform_admin=is_platform,
        resolved_role=resolved_role,
        tenant_id=tenant_id,
    )


async def require_cxo_metrics_write(
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
) -> CxoAccessContext:
    """Write access (PUT mapping / POST reset). Platform admins only."""
    resolved_role, is_platform, tenant_id = await _resolve_role(db, current_user)
    _assert_role(resolved_role, CXO_WRITE_ROLES, action="modify CXO mappings")
    return CxoAccessContext(
        current_user=current_user,
        is_platform_admin=is_platform,
        resolved_role=resolved_role,
        tenant_id=tenant_id,
    )


async def require_cxo_dashboard_access(
    db: AsyncSession = Depends(get_db),
    current_user: TokenUser = Depends(get_current_user),
) -> CxoAccessContext:
    """Read access for the dashboard endpoint. Open to platform admins,
    company admins, CXO, and HR."""
    resolved_role, is_platform, tenant_id = await _resolve_role(db, current_user)
    _assert_role(resolved_role, CXO_DASHBOARD_ROLES, action="read CXO dashboard")
    return CxoAccessContext(
        current_user=current_user,
        is_platform_admin=is_platform,
        resolved_role=resolved_role,
        tenant_id=tenant_id,
    )
