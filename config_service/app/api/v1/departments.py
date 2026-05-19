from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.rbac import require_permission
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.schemas.departments import (
    DepartmentCreate,
    DepartmentListResponse,
    DepartmentResponse,
    DepartmentUpdate,
)
from config_service.app.services.departments import DepartmentService


logger = get_file_logger(name="departments_api", prefix="departments_api")

router = APIRouter(prefix="/departments", tags=["departments"])


PERM_READ = "departments:read"
PERM_CREATE = "departments:create"
PERM_UPDATE = "departments:update"
PERM_DELETE = "departments:delete"


def _enforce_tenant_scope(current_user, company_id: UUID) -> None:
    """Raise 403 if a non-platform user tries to cross tenants."""
    if getattr(current_user, "is_platform_admin", False):
        return
    user_tenant = getattr(current_user, "tenant_id", None)
    if user_tenant != company_id:
        raise HTTPException(status_code=403, detail="Cross-tenant access forbidden")


@router.get("", response_model=APIResponse[DepartmentListResponse])
async def list_departments_by_company(
    company_id: UUID = Query(..., description="Tenant / company UUID"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    search: str | None = Query(default=None, description="Case-insensitive substring filter on the department name"),
    is_active: bool | None = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission(PERM_READ)),
):
    """List departments belonging to a company / tenant.

    Platform admins (Super Admin / Ayumonk Admin) can fetch any tenant.
    Per-tenant users are restricted to their own tenant.
    """
    logger.info(
        "REQUEST | list_departments_by_company | user_id=%s | company_id=%s "
        "| skip=%s | limit=%s | search=%s | is_active=%s",
        current_user.user_id,
        company_id,
        skip,
        limit,
        search,
        is_active,
    )

    try:
        _enforce_tenant_scope(current_user, company_id)
        db.info["user_id"] = current_user.user_id
        svc = DepartmentService(db)
        items, total = await svc.list(
            company_id,
            skip=skip,
            limit=limit,
            search=search,
            is_active=is_active,
        )
        payload = DepartmentListResponse(
            items=items, total=total, skip=skip, limit=limit
        )
        return success_response(data=payload, message="Departments fetched successfully")
    except HTTPException:
        raise
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | list_departments_by_company | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | list_departments_by_company | user_id=%s | company_id=%s",
            current_user.user_id,
            company_id,
        )
        return error_response(message="Failed to fetch departments", status_code=500)


@router.post("", response_model=APIResponse[DepartmentResponse])
async def create_department(
    payload: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission(PERM_CREATE)),
):
    logger.info(
        "REQUEST | create_department | user_id=%s | company_id=%s | name=%s",
        current_user.user_id,
        payload.company_id,
        payload.name,
    )

    try:
        _enforce_tenant_scope(current_user, payload.company_id)
        db.info["user_id"] = current_user.user_id
        svc = DepartmentService(db)
        result = await svc.create(payload)
        return success_response(data=result, message="Department created successfully")
    except HTTPException:
        raise
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_department | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_department | %s", e.errors())
        return error_response(
            message="Invalid department payload", status_code=422, errors=e.errors()
        )
    except Exception:
        logger.exception(
            "ERROR | create_department | user_id=%s | company_id=%s",
            current_user.user_id,
            payload.company_id,
        )
        return error_response(message="Failed to create department", status_code=500)


@router.get("/{department_id}", response_model=APIResponse[DepartmentResponse])
async def get_department(
    department_id: UUID,
    company_id: UUID = Query(..., description="Tenant / company UUID"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission(PERM_READ)),
):
    logger.info(
        "REQUEST | get_department | user_id=%s | company_id=%s | department_id=%s",
        current_user.user_id,
        company_id,
        department_id,
    )

    try:
        _enforce_tenant_scope(current_user, company_id)
        db.info["user_id"] = current_user.user_id
        svc = DepartmentService(db)
        result = await svc.get(department_id, company_id)
        return success_response(data=result, message="Department fetched successfully")
    except HTTPException:
        raise
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_department | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | get_department | user_id=%s | department_id=%s",
            current_user.user_id,
            department_id,
        )
        return error_response(message="Failed to fetch department", status_code=500)


@router.put("/{department_id}", response_model=APIResponse[DepartmentResponse])
async def update_department(
    department_id: UUID,
    payload: DepartmentUpdate,
    company_id: UUID = Query(..., description="Tenant / company UUID"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission(PERM_UPDATE)),
):
    logger.info(
        "REQUEST | update_department | user_id=%s | company_id=%s | department_id=%s",
        current_user.user_id,
        company_id,
        department_id,
    )

    try:
        _enforce_tenant_scope(current_user, company_id)
        db.info["user_id"] = current_user.user_id
        svc = DepartmentService(db)
        result = await svc.update(department_id, payload, company_id)
        return success_response(data=result, message="Department updated successfully")
    except HTTPException:
        raise
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_department | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_department | %s", e.errors())
        return error_response(
            message="Invalid department payload", status_code=422, errors=e.errors()
        )
    except Exception:
        logger.exception(
            "ERROR | update_department | user_id=%s | department_id=%s",
            current_user.user_id,
            department_id,
        )
        return error_response(message="Failed to update department", status_code=500)


@router.delete("/{department_id}", response_model=APIResponse[DepartmentResponse])
async def delete_department(
    department_id: UUID,
    company_id: UUID = Query(..., description="Tenant / company UUID"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission(PERM_DELETE)),
):
    logger.info(
        "REQUEST | delete_department | user_id=%s | company_id=%s | department_id=%s",
        current_user.user_id,
        company_id,
        department_id,
    )

    try:
        _enforce_tenant_scope(current_user, company_id)
        db.info["user_id"] = current_user.user_id
        svc = DepartmentService(db)
        result = await svc.delete(department_id, company_id)
        return success_response(data=result, message="Department deleted successfully")
    except HTTPException:
        raise
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_department | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | delete_department | user_id=%s | department_id=%s",
            current_user.user_id,
            department_id,
        )
        return error_response(message="Failed to delete department", status_code=500)
