from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.logging import get_logger
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.core.db import get_db
from authentication_service.app.core.dependencies import require_roles
from datetime import datetime
from config_service.app.services.company_users import UserService
from config_service.app.repositories.company_users import UserRepository
from config_service.app.schemas.company_users import (
    CompanyUserCreateRequest,
    CompanyUserListResponse,
    CompanyUserResponse,
    CompanyUserUpdateRequest,
)
from config_service.app.core.business_exceptions import BusinessException
from pydantic import ValidationError
from uuid import UUID

logger = get_file_logger(
    name="users_api",
    prefix="users_api"
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=APIResponse[CompanyUserListResponse])
async def list_company_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    company_id: UUID | None = None,
    search: str | None = None,
    is_active: bool | None = True,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_roles("ADMIN")),
):
    logger.info(
        "REQUEST | list_company_users | user_id=%s | skip=%s | limit=%s | company_id=%s",
        current_user.user_id,
        skip,
        limit,
        str(company_id) if company_id else None,
    )

    try:
        db.info["user_id"] = current_user.user_id
        # Force company scope to the logged-in admin's company
        repo = UserRepository(db)
        admin_record = await repo.get_by_email(current_user.email)
        if not admin_record:
            return error_response(message="Admin company not found", status_code=403)
        company_id = admin_record.company_id
        svc = UserService(db)
        result = await svc.list_users(
            skip=skip,
            limit=limit,
            company_id=company_id,
            search=search,
            is_active=is_active,
        )
        return success_response(data=result, message="Company users fetched successfully")
    except HTTPException:
        raise
    except Exception:
        logger.exception("ERROR | list_company_users | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch company users", status_code=500)


@router.get("/{user_id}", response_model=APIResponse[CompanyUserResponse])
async def get_company_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_roles("ADMIN")),
):
    logger.info(
        "REQUEST | get_company_user | user_id=%s | company_user_id=%s",
        current_user.user_id,
        str(user_id),
    )

    try:
        db.info["user_id"] = current_user.user_id
        svc = UserService(db)
        result = await svc.get_user(user_id)
        return success_response(data=result, message="Company user fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_company_user | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_company_user | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch company user", status_code=500)


@router.post("", response_model=APIResponse[CompanyUserResponse])
async def create_company_user(
    payload: CompanyUserCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_roles("ADMIN")),
):
    logger.info(
        "REQUEST | create_company_user | user_id=%s",
        current_user.user_id,
    )

    try:
        db.info["user_id"] = current_user.user_id
        svc = UserService(db)
        result, warning_message = await svc.create_user(payload)
        return success_response(
            data=result,
            message=warning_message or "Company user created successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_company_user | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_company_user | %s", e.errors())
        return error_response(message="Invalid company user payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | create_company_user | user_id=%s", current_user.user_id)
        return error_response(message="Failed to create company user", status_code=500)

@router.post("/upload", response_model=APIResponse[dict])
async def upload_users(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_roles("ADMIN")),
):
    logger.info(
        "REQUEST | upload_users_excel | user_id=%s | filename=%s",
        current_user.user_id,
        file.filename
    )

    try:
        db.info["user_id"] = current_user.user_id

        svc = UserService(db)
        result = await svc.upload_users_from_excel(file.file)

        logger.info(
            "RESPONSE | upload_users_excel | user_id=%s | result=%s",
            current_user.user_id,
            result
        )

        return success_response(
            data=result,
            message="Users uploaded successfully"
        )

    except Exception as e:
        logger.exception(
            "ERROR | upload_users_excel | user_id=%s | filename=%s",
            current_user.user_id,
            file.filename
        )
        return error_response(
            message="Failed to upload users",
            status_code=500
        )


@router.put("/{user_id}", response_model=APIResponse[CompanyUserResponse])
async def update_company_user(
    user_id: UUID,
    payload: CompanyUserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_roles("ADMIN")),
):
    logger.info(
        "REQUEST | update_company_user | user_id=%s | company_user_id=%s",
        current_user.user_id,
        str(user_id),
    )

    try:
        db.info["user_id"] = current_user.user_id
        svc = UserService(db)
        result = await svc.update_user(user_id, payload)
        return success_response(data=result, message="Company user updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_company_user | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_company_user | %s", e.errors())
        return error_response(message="Invalid company user payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | update_company_user | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update company user", status_code=500)


@router.delete("/{user_id}", response_model=APIResponse[CompanyUserResponse])
async def delete_company_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_roles("ADMIN")),
):
    logger.info(
        "REQUEST | delete_company_user | user_id=%s | company_user_id=%s",
        current_user.user_id,
        str(user_id),
    )

    try:
        db.info["user_id"] = current_user.user_id
        svc = UserService(db)
        result = await svc.delete_user(user_id)
        return success_response(data=result, message="Company user deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_company_user | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_company_user | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete company user", status_code=500)
