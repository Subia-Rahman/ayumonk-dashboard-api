from __future__ import annotations
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.rbac_dependencies import (
    CompanyUsersAccess,
    require_company_users_access,
)
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.repositories.company_users import UserRepository
from config_service.app.schemas.company_users import (
    CompanyUserCreateRequest,
    CompanyUserListResponse,
    CompanyUserResponse,
    CompanyUserUpdateRequest,
)
from config_service.app.services.company_users import UserService


logger = get_file_logger(name="users_api", prefix="users_api")

router = APIRouter(prefix="/users", tags=["users"])


# RBAC menu slug + permission codenames (matches the rbac_constants seed).
MENU_SLUG = "company-users"
PERM_READ = "company_users:read"
PERM_CREATE = "company_users:create"
PERM_UPDATE = "company_users:update"
PERM_DELETE = "company_users:delete"


def _log_access(action: str, access: CompanyUsersAccess, **extra) -> None:
    fields = {
        "user_id": access.current_user.user_id,
        "tenant_id": str(access.tenant_id) if access.tenant_id else None,
        "is_super_admin": access.is_super_admin,
        "policy": access.policy_name,
    }
    fields.update({k: str(v) if v is not None else None for k, v in extra.items()})
    logger.info(
        "REQUEST | %s | %s",
        action,
        " | ".join(f"{k}={v}" for k, v in fields.items()),
    )


@router.get("", response_model=APIResponse[CompanyUserListResponse])
async def list_company_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    company_id: UUID | None = None,
    department_id: UUID | None = Query(default=None, description="Filter by department UUID"),
    role_id: int | None = Query(default=None, description="Filter by RBAC role id"),
    search: str | None = None,
    is_active: bool | None = True,
    db: AsyncSession = Depends(get_db),
    access: CompanyUsersAccess = Depends(
        require_company_users_access(MENU_SLUG, "view", PERM_READ)
    ),
):
    _log_access(
        "list_company_users",
        access,
        skip=skip,
        limit=limit,
        company_id=company_id,
        department_id=department_id,
        role_id=role_id,
    )

    try:
        db.info["user_id"] = access.current_user.user_id

        resolved_company_id = access.effective_company_id(requested=company_id)
        # Non-super-admin: prevent crossing tenant boundary even if a query
        # param was supplied.
        if (
            company_id is not None
            and not access.is_super_admin
            and access.tenant_id is not None
            and company_id != access.tenant_id
        ):
            return error_response(
                message="Cross-tenant access forbidden",
                status_code=403,
            )

        # Department-scoped users can only narrow within their own department.
        eff_dept = access.effective_department_id()
        if eff_dept is not None and department_id is not None and department_id != eff_dept:
            return error_response(
                message="Cannot list users outside your department scope",
                status_code=403,
            )
        final_department_id = department_id if department_id is not None else eff_dept

        svc = UserService(db)
        result = await svc.list_users(
            skip=skip,
            limit=limit,
            company_id=resolved_company_id,
            department_id=final_department_id,
            restrict_to_id=access.restrict_to_self_id(),
            role_id=role_id,
            search=search,
            is_active=is_active,
        )
        return success_response(data=result, message="Company users fetched successfully")
    except HTTPException:
        raise
    except Exception:
        logger.exception("ERROR | list_company_users | user_id=%s", access.current_user.user_id)
        return error_response(message="Failed to fetch company users", status_code=500)


@router.get("/{user_id}", response_model=APIResponse[CompanyUserResponse])
async def get_company_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: CompanyUsersAccess = Depends(
        require_company_users_access(MENU_SLUG, "view", PERM_READ)
    ),
):
    _log_access("get_company_user", access, target=user_id)

    try:
        db.info["user_id"] = access.current_user.user_id

        record = await UserRepository(db).get_by_id(
            user_id,
            access.effective_company_id(),
        )
        if not record:
            return error_response(message="Company user not found", status_code=404)

        access.assert_record_in_scope(
            record_company_id=record.company_id,
            record_department_id=record.department_id,
            record_id=record.id,
        )

        return success_response(
            data=CompanyUserResponse.model_validate(record),
            message="Company user fetched successfully",
        )
    except HTTPException:
        raise
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_company_user | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_company_user | user_id=%s", access.current_user.user_id)
        return error_response(message="Failed to fetch company user", status_code=500)


@router.post("", response_model=APIResponse[CompanyUserResponse])
async def create_company_user(
    payload: CompanyUserCreateRequest,
    db: AsyncSession = Depends(get_db),
    access: CompanyUsersAccess = Depends(
        require_company_users_access(MENU_SLUG, "full", PERM_CREATE)
    ),
):
    _log_access("create_company_user", access)

    try:
        db.info["user_id"] = access.current_user.user_id

        # Force company_id to the requester's tenant unless they're super admin.
        if not access.is_super_admin and access.tenant_id is not None:
            payload.company_id = access.tenant_id

        # Department-scoped roles can only create users in their own department.
        eff_dept_id = access.effective_department_id()
        if eff_dept_id is not None:
            if payload.department_id is not None and payload.department_id != eff_dept_id:
                return error_response(
                    message="Cannot create user outside your department scope",
                    status_code=403,
                )
            if payload.department_id is None:
                payload.department_id = eff_dept_id

        # Self-scoped users cannot create others.
        if access.restrict_to_self_id() is not None:
            return error_response(
                message="Self-scoped role cannot create company users",
                status_code=403,
            )

        svc = UserService(db)
        result, warning_message = await svc.create_user(payload)
        return success_response(
            data=result,
            message=warning_message or "Company user created successfully",
        )
    except HTTPException:
        raise
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_company_user | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_company_user | %s", e.errors())
        return error_response(message="Invalid company user payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | create_company_user | user_id=%s", access.current_user.user_id)
        return error_response(message="Failed to create company user", status_code=500)


@router.post("/upload", response_model=APIResponse[dict])
async def upload_users(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    access: CompanyUsersAccess = Depends(
        require_company_users_access(MENU_SLUG, "full", PERM_CREATE)
    ),
):
    _log_access("upload_users", access, filename=file.filename)

    try:
        db.info["user_id"] = access.current_user.user_id

        if access.restrict_to_self_id() is not None:
            return error_response(
                message="Self-scoped role cannot bulk upload users",
                status_code=403,
            )

        svc = UserService(db)
        result = await svc.upload_users_from_excel(file.file)
        logger.info(
            "RESPONSE | upload_users | user_id=%s | result=%s",
            access.current_user.user_id,
            result,
        )
        return success_response(data=result, message="Users uploaded successfully")
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "ERROR | upload_users | user_id=%s | filename=%s",
            access.current_user.user_id,
            file.filename,
        )
        return error_response(message="Failed to upload users", status_code=500)


@router.put("/{user_id}", response_model=APIResponse[CompanyUserResponse])
async def update_company_user(
    user_id: UUID,
    payload: CompanyUserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    access: CompanyUsersAccess = Depends(
        require_company_users_access(MENU_SLUG, "full", PERM_UPDATE)
    ),
):
    _log_access("update_company_user", access, target=user_id)

    try:
        db.info["user_id"] = access.current_user.user_id

        record = await UserRepository(db).get_by_id(
            user_id,
            access.effective_company_id(),
        )
        if not record:
            return error_response(message="Company user not found", status_code=404)

        access.assert_record_in_scope(
            record_company_id=record.company_id,
            record_department_id=record.department_id,
            record_id=record.id,
        )

        # Reject reassignment outside the requester's tenant.
        if (
            payload.company_id is not None
            and not access.is_super_admin
            and access.tenant_id is not None
            and payload.company_id != access.tenant_id
        ):
            return error_response(
                message="Cannot move user to a different tenant",
                status_code=403,
            )

        # Department-scoped role: cannot move users out of (or into) other depts.
        eff_dept_id = access.effective_department_id()
        if (
            eff_dept_id is not None
            and payload.department_id is not None
            and payload.department_id != eff_dept_id
        ):
            return error_response(
                message="Cannot reassign user outside your department scope",
                status_code=403,
            )

        svc = UserService(db)
        result = await svc.update_user(
            user_id,
            payload,
            company_id=access.effective_company_id(),
        )
        return success_response(data=result, message="Company user updated successfully")
    except HTTPException:
        raise
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_company_user | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_company_user | %s", e.errors())
        return error_response(message="Invalid company user payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | update_company_user | user_id=%s", access.current_user.user_id)
        return error_response(message="Failed to update company user", status_code=500)


@router.delete("/{user_id}", response_model=APIResponse[CompanyUserResponse])
async def delete_company_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: CompanyUsersAccess = Depends(
        require_company_users_access(MENU_SLUG, "full", PERM_DELETE)
    ),
):
    _log_access("delete_company_user", access, target=user_id)

    try:
        db.info["user_id"] = access.current_user.user_id

        record = await UserRepository(db).get_by_id(
            user_id,
            access.effective_company_id(),
        )
        if not record:
            return error_response(message="Company user not found", status_code=404)

        access.assert_record_in_scope(
            record_company_id=record.company_id,
            record_department_id=record.department_id,
            record_id=record.id,
        )

        # Self-scoped role cannot delete itself via this API by default.
        if access.restrict_to_self_id() is not None:
            return error_response(
                message="Self-scoped role cannot delete company users",
                status_code=403,
            )

        svc = UserService(db)
        result = await svc.delete_user(
            user_id,
            company_id=access.effective_company_id(),
        )
        return success_response(data=result, message="Company user deleted successfully")
    except HTTPException:
        raise
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_company_user | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_company_user | user_id=%s", access.current_user.user_id)
        return error_response(message="Failed to delete company user", status_code=500)
