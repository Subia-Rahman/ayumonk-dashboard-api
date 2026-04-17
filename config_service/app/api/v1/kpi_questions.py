
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.repositories.kpi import KPIRepository
from config_service.app.repositories.kpi_questions import KPIQuestionRepository
from config_service.app.repositories.kpi_scoring import KPIScoringRepository
from config_service.app.repositories.theme import ThemeRepository
from config_service.app.schemas.kpi_hierarchy import ThemeHierarchyResponse
from config_service.app.core.db import get_db
from authentication_service.app.core.dependencies import require_roles

from config_service.app.services.kpi_questions import KPIService

logger = get_file_logger(
    name="kpi_question_api",
    prefix="kpi_question_api"
)

router = APIRouter(prefix="/kpiquestions", tags=["kpiquestions"])


@router.get("/hierarchy", response_model=APIResponse[list[ThemeHierarchyResponse]])
async def get_kpi_hierarchy(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_roles("ADMIN")),
):
    logger.info("REQUEST | get_kpi_hierarchy | user_id=%s", current_user.user_id)

    try:
        db.info["user_id"] = current_user.user_id
        theme_repo = ThemeRepository(db)
        kpi_repo = KPIRepository(db)
        question_repo = KPIQuestionRepository(db)
        scoring_repo = KPIScoringRepository(db)

        service = KPIService(
            theme_repo,
            kpi_repo,
            question_repo,
            scoring_repo
        )

        result = await service.get_hierarchy()
        logger.info(
            "RESPONSE | get_kpi_hierarchy | user_id=%s | theme_count=%s",
            current_user.user_id,
            len(result),
        )

        return success_response(
            data=result,
            message="Configuration hierarchy fetched successfully"
        )
    except Exception:
        logger.exception("ERROR | get_kpi_hierarchy | user_id=%s", current_user.user_id)
        return error_response(
            message="Failed to fetch configuration hierarchy",
            status_code=500
        )


@router.post("/upload", response_model=APIResponse[dict])
async def upload_kpi_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_roles("ADMIN"))
):
    try:
        logger.info(
        "REQUEST | upload_kpi_excel | user_id=%s | filename=%s",
        current_user.user_id,
        file.filename
        )
        db.info["user_id"] = current_user.user_id
        theme_repo = ThemeRepository(db)
        kpi_repo = KPIRepository(db)
        question_repo = KPIQuestionRepository(db)
        scoring_repo = KPIScoringRepository(db)

        service = KPIService(
            theme_repo,
            kpi_repo,
            question_repo,
            scoring_repo
        )

        result = await service.upload_kpi_from_excel(
            file.file
        )

        logger.info(
            "RESPONSE | upload_kpi_excel | user_id=%s | created=%s | updated=%s | errors=%s",
            current_user.user_id,
            result.get("created"),
            result.get("updated"),
            len(result.get("errors", []))
        )

        return success_response(
            data=result,
            message="KPI Excel uploaded successfully"
        )
    except Exception as e:
        logger.exception(
            "ERROR | upload_kpi_excel | user_id=%s | filename=%s",
            current_user.user_id,
            file.filename
        )
        return error_response(
            message="Failed to upload KPI Excel",
            status_code=500
        )
