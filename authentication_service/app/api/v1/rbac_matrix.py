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
from authentication_service.app.models.menu import Menu
from authentication_service.app.models.role import Role
from authentication_service.app.models.role_menu import RoleMenu
from config_service.app.models.company import Company


logger = get_file_logger(name="rbac_matrix_api", prefix="rbac_matrix_api")
router = APIRouter(prefix="/api/v1/auth", tags=["RBACMatrix"])


# Role-string match for Company Admin authz check. JWT/user.role values vary in
# casing/spacing across the codebase, so normalize before comparing.
_COMPANY_ADMIN_ALIASES = {"companyadmin"}


def _is_company_admin(role: str | None) -> bool:
    if not role:
        return False
    cleaned = str(role).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    return cleaned in _COMPANY_ADMIN_ALIASES


class RbacMatrixSection(BaseModel):
    name: str
    permissions: dict[str, str]


class RbacMatrixData(BaseModel):
    company_id: str | None = None
    company_name: str | None = None
    roles: list[str]
    sections: list[RbacMatrixSection]


@router.get("/rbac-matrix", response_model=APIResponse[RbacMatrixData])
async def get_rbac_matrix(
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Return the role × section RBAC capability matrix for one tenant.

    AuthZ:
      * Platform admin (JWT is_platform_admin=true) — may pass any company_id;
        omitting it returns an empty matrix (no tenant context).
      * Company admin — the query param is ignored; the user's JWT tenant_id
        is used.
      * Any other role — 403.

    Data shape: roles are the rows in `roles` scoped to this tenant
    (`roles.tenant_id = :company_id`) — every role defined for the company,
    whether or not any user is assigned to it. Sections are the menus that
    have at least one row in `role_menus` for those roles. Each cell is the
    `access_level` from `role_menus` (or "none" if no row exists).
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

    # Platform admin without a selected company → empty matrix (no tenant).
    if resolved_company_id is None:
        data = RbacMatrixData(
            company_id=None,
            company_name=None,
            roles=[],
            sections=[],
        )
        return success_response(data=data, message="RBAC matrix fetched successfully")

    # ------------------------------------------------------------------
    # 1. Roles dynamic per company — every active row in `roles` scoped to
    #    this tenant. Independent of whether any user is currently assigned.
    # ------------------------------------------------------------------
    role_result = await db.execute(
        select(Role.id, Role.name)
        .where(Role.tenant_id == resolved_company_id)
        .where(Role.is_active.is_(True))
        .order_by(Role.id)
    )
    role_rows = role_result.all()
    role_ids = [r.id for r in role_rows]
    role_names_by_id = {r.id: r.name for r in role_rows}
    role_names = [r.name for r in role_rows]

    if not role_ids:
        data = RbacMatrixData(
            company_id=str(resolved_company_id),
            company_name=company_name,
            roles=[],
            sections=[],
        )
        return success_response(data=data, message="RBAC matrix fetched successfully")

    # ------------------------------------------------------------------
    # 2. Sections dynamic — menus that have at least one role_menus row
    #    for any of the roles found above. Ordered by Menu.order_no.
    # ------------------------------------------------------------------
    menu_result = await db.execute(
        select(Menu.id, Menu.name, Menu.order_no)
        .join(RoleMenu, RoleMenu.menu_id == Menu.id)
        .where(RoleMenu.role_id.in_(role_ids))
        .where(Menu.is_active.is_(True))
        .distinct()
        .order_by(Menu.order_no, Menu.id)
    )
    menu_rows = menu_result.all()

    # ------------------------------------------------------------------
    # 3. Cell values — one row per (role_id, menu_id) we care about.
    # ------------------------------------------------------------------
    perm_result = await db.execute(
        select(RoleMenu.role_id, RoleMenu.menu_id, RoleMenu.access_level)
        .where(RoleMenu.role_id.in_(role_ids))
    )
    access_by_cell: dict[tuple[int, int], str] = {
        (row.role_id, row.menu_id): row.access_level for row in perm_result.all()
    }

    sections: list[RbacMatrixSection] = []
    for menu in menu_rows:
        permissions = {
            role_names_by_id[rid]: access_by_cell.get((rid, menu.id), "none")
            for rid in role_ids
        }
        sections.append(RbacMatrixSection(name=menu.name, permissions=permissions))

    data = RbacMatrixData(
        company_id=str(resolved_company_id),
        company_name=company_name,
        roles=role_names,
        sections=sections,
    )

    logger.info(
        "RESPONSE | get_rbac_matrix | user_id=%s | resolved_company_id=%s | "
        "roles=%d | sections=%d",
        getattr(current_user, "user_id", None),
        resolved_company_id,
        len(role_names),
        len(sections),
    )
    return success_response(data=data, message="RBAC matrix fetched successfully")
