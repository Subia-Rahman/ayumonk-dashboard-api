from __future__ import annotations
from uuid import UUID

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.repositories.company_users import UserRepository
from config_service.app.repositories.kpi import KPIRepository
from config_service.app.repositories.kpi_questions import KPIQuestionRepository
from config_service.app.repositories.kpi_scoring import KPIScoringRepository
from config_service.app.repositories.theme import ThemeRepository
from config_service.app.schemas.kpi_hierarchy import ThemeHierarchyResponse
from config_service.app.core.db import get_db
from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.rbac import require_permission

from config_service.app.services.kpi_questions import KPIService

logger = get_file_logger(name="kpi_question_api", prefix="kpi_question_api")
router = APIRouter(prefix="/kpiquestions", tags=["kpiquestions"])


async def _resolve_company_id(current_user, db: AsyncSession, company_id_param: UUID | None = None):
    if getattr(current_user, "is_platform_admin", False):
        return company_id_param
    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id is None:
        raise BusinessException(message="Admin company not found", status_code=403)
    return tenant_id


@router.get("/hierarchy", response_model=APIResponse[list[ThemeHierarchyResponse]])
async def get_kpi_hierarchy(
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:read")),
):
    logger.info("REQUEST | get_kpi_hierarchy | user_id=%s", current_user.user_id)

    try:
        db.info["user_id"] = current_user.user_id
        resolved = await _resolve_company_id(current_user, db, company_id)

        service = KPIService(
            ThemeRepository(db),
            KPIRepository(db),
            KPIQuestionRepository(db),
            KPIScoringRepository(db),
        )
        result = await service.get_hierarchy(company_id=resolved)
        logger.info(
            "RESPONSE | get_kpi_hierarchy | user_id=%s | theme_count=%s",
            current_user.user_id, len(result),
        )
        return success_response(data=result, message="Configuration hierarchy fetched successfully")
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_kpi_hierarchy | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch configuration hierarchy", status_code=500)


@router.post("/upload", response_model=APIResponse[dict])
async def upload_kpi_excel(
    file: UploadFile = File(...),
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("kpis:create")),
):
    try:
        logger.info(
            "REQUEST | upload_kpi_excel | user_id=%s | filename=%s",
            current_user.user_id, file.filename,
        )
        db.info["user_id"] = current_user.user_id
        resolved = await _resolve_company_id(current_user, db, company_id)

        service = KPIService(
            ThemeRepository(db),
            KPIRepository(db),
            KPIQuestionRepository(db),
            KPIScoringRepository(db),
        )
        result = await service.upload_kpi_from_excel(file.file, company_id=resolved)
        logger.info(
            "RESPONSE | upload_kpi_excel | user_id=%s | created=%s | updated=%s | errors=%s",
            current_user.user_id,
            result.get("created"),
            result.get("updated"),
            len(result.get("errors", [])),
        )
        if result.get("errors"):
            logger.error(
                "ROW_ERRORS | upload_kpi_excel | user_id=%s | errors=%s",
                current_user.user_id, result["errors"],
            )
        return success_response(data=result, message="KPI Excel uploaded successfully")
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | upload_kpi_excel | user_id=%s | filename=%s",
            current_user.user_id, file.filename,
        )
        return error_response(message="Failed to upload KPI Excel", status_code=500)
