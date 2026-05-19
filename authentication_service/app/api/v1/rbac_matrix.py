from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.custom_loggers import get_file_logger
from authentication_service.app.core.db import get_db
from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.response import APIResponse
from authentication_service.app.core.response_utils import error_response, success_response
from config_service.app.models.company import Company


logger = get_file_logger(name="rbac_matrix_api", prefix="rbac_matrix_api")
router = APIRouter(prefix="/api/v1/auth", tags=["RBACMatrix"])


# -----------------------------------------------------------------------------
# Static matrix — mirrors the displayed dashboard sections. Role assignments
# are platform-wide; per-company overrides are not modelled here.
# -----------------------------------------------------------------------------
RBAC_MATRIX_ROLES: list[dict] = [
    {"key": "employee", "label": "Employee"},
    {"key": "hr", "label": "HR Manager"},
    {"key": "cxo", "label": "CXO"},
    {"key": "admin", "label": "Company Admin"},
    {"key": "ayumonk_admin", "label": "Ayumonk Admin"},
    {"key": "super_admin", "label": "Super Admin"},
]

# permissions value ∈ {"none", "view", "full"}
RBAC_MATRIX_SECTIONS: list[dict] = [
    {
        "key": "company_master",
        "label": "Company Master",
        "permissions": {
            "employee": "none", "hr": "none", "cxo": "none",
            "admin": "view", "ayumonk_admin": "full", "super_admin": "full",
        },
    },
    {
        "key": "company_users",
        "label": "Company Users",
        "permissions": {
            "employee": "none", "hr": "view", "cxo": "none",
            "admin": "full", "ayumonk_admin": "full", "super_admin": "full",
        },
    },
    {
        "key": "themes",
        "label": "Themes",
        "permissions": {
            "employee": "none", "hr": "none", "cxo": "none",
            "admin": "view", "ayumonk_admin": "full", "super_admin": "full",
        },
    },
    {
        "key": "kpis_questions",
        "label": "KPIs & Questions",
        "permissions": {
            "employee": "none", "hr": "none", "cxo": "none",
            "admin": "none", "ayumonk_admin": "full", "super_admin": "full",
        },
    },
    {
        "key": "challenges",
        "label": "Challenges",
        "permissions": {
            "employee": "none", "hr": "view", "cxo": "none",
            "admin": "view", "ayumonk_admin": "full", "super_admin": "full",
        },
    },
    {
        "key": "suggestion_master",
        "label": "Suggestion Master",
        "permissions": {
            "employee": "none", "hr": "none", "cxo": "none",
            "admin": "none", "ayumonk_admin": "full", "super_admin": "full",
        },
    },
    {
        "key": "sessions",
        "label": "Sessions / Windows",
        "permissions": {
            "employee": "none", "hr": "full", "cxo": "view",
            "admin": "full", "ayumonk_admin": "full", "super_admin": "full",
        },
    },
    {
        "key": "hr_analytics",
        "label": "HR Analytics",
        "permissions": {
            "employee": "none", "hr": "full", "cxo": "full",
            "admin": "none", "ayumonk_admin": "view", "super_admin": "full",
        },
    },
    {
        "key": "ayufinity",
        "label": "Ayufinity / Products",
        "permissions": {
            "employee": "none", "hr": "none", "cxo": "none",
            "admin": "none", "ayumonk_admin": "full", "super_admin": "full",
        },
    },
    {
        "key": "platform_settings",
        "label": "Platform Settings",
        "permissions": {
            "employee": "none", "hr": "none", "cxo": "none",
            "admin": "none", "ayumonk_admin": "none", "super_admin": "full",
        },
    },
]


# Role-string match for Company Admin authz check. JWT/user.role values vary in
# casing/spacing across the codebase, so normalize before comparing.
_COMPANY_ADMIN_ALIASES = {"companyadmin"}


def _is_company_admin(role: str | None) -> bool:
    if not role:
        return False
    cleaned = str(role).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    return cleaned in _COMPANY_ADMIN_ALIASES


class RbacMatrixRole(BaseModel):
    key: str
    label: str


class RbacMatrixSection(BaseModel):
    key: str
    label: str
    permissions: dict[str, str]


class RbacMatrixData(BaseModel):
    company_id: str | None = None
    company_name: str | None = None
    roles: list[RbacMatrixRole]
    sections: list[RbacMatrixSection]


@router.get("/rbac-matrix", response_model=APIResponse[RbacMatrixData])
async def get_rbac_matrix(
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Return the role × section RBAC capability matrix used by the super-admin
    dashboard. AuthZ rules:

      * Platform admin (JWT is_platform_admin=true) — may pass any company_id;
        omitting it returns the platform default (company_id null).
      * Company admin (role normalises to "admin") — the query param is
        ignored; the user's JWT tenant_id is used.
      * Any other role — 403.

    The matrix itself is currently a static snapshot of role capabilities; the
    company_id only scopes the company_name field, not the cell values.
    """
    logger.info(
        "REQUEST | get_rbac_matrix | user_id=%s | role=%s | company_id=%s | is_platform_admin=%s",
        getattr(current_user, "user_id", None),
        getattr(current_user, "role", None),
        company_id,
        getattr(current_user, "is_platform_admin", False),
    )

    is_platform = bool(getattr(current_user, "is_platform_admin", False))
    role = getattr(current_user, "role", None)

    if is_platform:
        resolved_company_id = company_id
    elif _is_company_admin(role):
        tenant_id = getattr(current_user, "tenant_id", None)
        if tenant_id is None:
            return error_response(
                message="Admin company not found",
                status_code=403,
            )
        try:
            resolved_company_id = UUID(str(tenant_id))
        except (TypeError, ValueError):
            return error_response(
                message="Invalid tenant identifier on token",
                status_code=403,
            )
    else:
        return error_response(
            message="Forbidden",
            status_code=403,
        )

    company_name: str | None = None
    if resolved_company_id is not None:
        result = await db.execute(
            select(Company.company_name).where(Company.id == resolved_company_id)
        )
        company_name = result.scalar_one_or_none()
        if company_name is None and not is_platform:
            # A company admin pointing at a tenant that no longer exists is
            # treated as forbidden rather than silently leaking a null body.
            return error_response(
                message="Company not found for current user",
                status_code=403,
            )

    data = RbacMatrixData(
        company_id=str(resolved_company_id) if resolved_company_id else None,
        company_name=company_name,
        roles=[RbacMatrixRole(**r) for r in RBAC_MATRIX_ROLES],
        sections=[RbacMatrixSection(**s) for s in RBAC_MATRIX_SECTIONS],
    )

    logger.info(
        "RESPONSE | get_rbac_matrix | user_id=%s | resolved_company_id=%s | company_name=%s",
        getattr(current_user, "user_id", None),
        resolved_company_id,
        company_name,
    )
    return success_response(data=data, message="RBAC matrix fetched successfully")
