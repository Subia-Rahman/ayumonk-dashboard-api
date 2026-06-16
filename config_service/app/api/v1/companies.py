from __future__ import annotations
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from fastapi import APIRouter, Depends, File, Query, UploadFile
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.services.companies import CompanyService
from config_service.app.core.db import get_db
from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.rbac import require_permission
from config_service.app.repositories.company_users import UserRepository
from config_service.app.schemas.companies import (
    CompanyAdminCreateRequest,
    CompanyCreateWithAdminRequest,
    CompanyCreateWithAdminResponse,
    CompanyResponse,
    CompanyUpdateRequest,
)
from config_service.app.schemas.company_users import CompanyUserResponse
from config_service.app.core.business_exceptions import BusinessException
from pydantic import ValidationError

logger = get_file_logger(
    name="companies_api",
    prefix="companies_api"
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=APIResponse[list[CompanyResponse]])
async def list_companies(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_permission("company_master:read")),
):
    is_platform = getattr(current_user, "is_platform_admin", False)
    logger.info(
        "REQUEST | list_companies | user_id=%s | skip=%s | limit=%s | is_platform_admin=%s",
        current_user.user_id,
        skip,
        limit,
        is_platform,
    )

    try:
        db.info["user_id"] = current_user.user_id
        svc = CompanyService(db)

        if is_platform:
            result = await svc.list_companies(skip=skip, limit=limit)
        else:
            tenant_id = getattr(current_user, "tenant_id", None)
            if tenant_id is None:
                return error_response(
                    message="No tenant context for current user",
                    status_code=403,
                )
            try:
                company = await svc.get_company(tenant_id)
                result = [company]
            except BusinessException:
                result = []

        logger.info(
            "RESPONSE | list_companies | user_id=%s | count=%s",
            current_user.user_id,
            len(result),
        )

        return success_response(
            data=result,
            message="Companies fetched successfully"
        )

    except Exception as e:
        logger.exception(
            "ERROR | list_companies | user_id=%s",
            current_user.user_id
        )
        return error_response(
            message="Failed to fetch companies",
            status_code=500
        )


@router.get("/me", response_model=APIResponse[CompanyResponse])
async def get_my_company(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    logger.info(
        "REQUEST | get_my_company | user_id=%s",
        current_user.user_id,
    )
    db.info["user_id"] = current_user.user_id

    try:
        user_repo = UserRepository(db)
        company_user = await user_repo.get_by_email(current_user.email)
        if not company_user:
            return error_response(message="Company user not found", status_code=404)

        svc = CompanyService(db)
        result = await svc.get_company(company_user.company_id)
        return success_response(data=result, message="Company fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_my_company | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_my_company | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch company", status_code=500)


@router.post("/upload", response_model=APIResponse[dict])
async def upload_companies(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_permission("company_master:create")),
):
    logger.info(
        "REQUEST | upload_companies_excel | user_id=%s | filename=%s",
        current_user.user_id,
        file.filename
    )

    try:
        db.info["user_id"] = current_user.user_id

        svc = CompanyService(db)
        result = await svc.upload_companies_from_excel(file.file)

        logger.info(
            "RESPONSE | upload_companies_excel | user_id=%s | result=%s",
            current_user.user_id,
            result
        )

        return success_response(
            data=result,
            message="Companies uploaded successfully"
        )

    except Exception as e:
        logger.exception(
            "ERROR | upload_companies_excel | user_id=%s | filename=%s",
            current_user.user_id,
            file.filename
        )
        return error_response(
            message="Failed to upload companies",
            status_code=500
        )


@router.post("", response_model=APIResponse[CompanyCreateWithAdminResponse])
async def create_company_with_admin(
    payload: CompanyCreateWithAdminRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("company_master:create")),
):
    logger.info(
        "REQUEST | create_company_with_admin | user_id=%s | company=%s",
        current_user.user_id,
        payload.company.company_name,
    )
    db.info["user_id"] = current_user.user_id

    try:
        svc = CompanyService(db)
        result = await svc.create_company_with_admin(payload)
        return success_response(data=result, message="Company and admin created successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_company_with_admin | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_company_with_admin | %s", e.errors())
        return error_response(message="Invalid company payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | create_company_with_admin | user_id=%s", current_user.user_id)
        return error_response(message="Failed to create company", status_code=500)


@router.get("/{company_id}", response_model=APIResponse[CompanyResponse])
async def get_company(
    company_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("company_master:read")),
):
    logger.info(
        "REQUEST | get_company | user_id=%s | company_id=%s",
        current_user.user_id,
        company_id,
    )
    db.info["user_id"] = current_user.user_id

    try:
        svc = CompanyService(db)
        result = await svc.get_company(company_id)
        return success_response(data=result, message="Company fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_company | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_company | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch company", status_code=500)


@router.put("/{company_id}", response_model=APIResponse[CompanyResponse])
async def update_company(
    company_id: UUID,
    payload: CompanyUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("company_master:update")),
):
    logger.info(
        "REQUEST | update_company | user_id=%s | company_id=%s",
        current_user.user_id,
        company_id,
    )
    db.info["user_id"] = current_user.user_id

    try:
        svc = CompanyService(db)
        result = await svc.update_company(company_id, payload)
        return success_response(data=result, message="Company updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_company | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_company | %s", e.errors())
        return error_response(
            message="Invalid company payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        logger.exception("ERROR | update_company | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update company", status_code=500)


@router.delete("/{company_id}", response_model=APIResponse[CompanyResponse])
async def delete_company(
    company_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("company_master:delete")),
):
    logger.info(
        "REQUEST | delete_company | user_id=%s | company_id=%s",
        current_user.user_id,
        company_id,
    )
    db.info["user_id"] = current_user.user_id

    try:
        svc = CompanyService(db)
        result = await svc.delete_company(company_id)
        return success_response(data=result, message="Company deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_company | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_company | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete company", status_code=500)


@router.post("/{company_id}/admin", response_model=APIResponse[CompanyUserResponse])
async def assign_company_admin(
    company_id: UUID,
    payload: CompanyAdminCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("company_users:create")),
):
    logger.info(
        "REQUEST | assign_company_admin | user_id=%s | company_id=%s",
        current_user.user_id,
        str(company_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        svc = CompanyService(db)
        result = await svc.assign_company_admin(company_id, payload)
        return success_response(data=result, message="Company admin assigned successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | assign_company_admin | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | assign_company_admin | %s", e.errors())
        return error_response(message="Invalid admin payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | assign_company_admin | user_id=%s", current_user.user_id)
        return error_response(message="Failed to assign company admin", status_code=500)
