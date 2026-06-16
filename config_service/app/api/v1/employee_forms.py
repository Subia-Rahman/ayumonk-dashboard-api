from __future__ import annotations
from authentication_service.app.repositories.user_repo import AuthUserRepository
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.config import settings
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.repositories.employee_form import EmployeeFormRepository
from config_service.app.repositories.kpi_questions import KPIQuestionRepository
from config_service.app.repositories.kpi_scoring import KPIScoringRepository
from config_service.app.core.db import get_db
from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.rbac import require_permission

from config_service.app.services.employee_form import EmployeeFormService
from config_service.app.schemas.employee_forms import GoogleFormWebhookRequest
from pydantic import ValidationError


logger = get_file_logger(
    name="forms_api",
    prefix="forms_api"
)

router = APIRouter(prefix="/employee_forms", tags=["employee_forms"])


@router.post("/webhook", response_model=APIResponse[dict])
async def employee_forms_webhook(
    request: Request,
    x_webhook_secret: str | None = Header(default=None, alias="X-Webhook-Secret"),
    db: AsyncSession = Depends(get_db)
):
    logger.info("REQUEST | employee_forms_webhook")

    try:
        expected_secret = settings.EMPLOYEE_FORM_WEBHOOK_SECRET
        if expected_secret and x_webhook_secret != expected_secret:
            raise BusinessException(message="Invalid webhook secret", status_code=401)

        raw_payload = await request.json()
        payload = _normalize_webhook_payload(raw_payload)
        data = payload["form_data"]
        email = data.get("email")

        # Resolve user
        user_repo = AuthUserRepository(db)
        user = await user_repo.get_by_email(email)

        if user:
            db.info["user_id"] = user.id
        else:
            db.info["user_id"] = 0  # SYSTEM / anonymous

        svc = EmployeeFormService(
            EmployeeFormRepository(db),
            KPIQuestionRepository(db),
            KPIScoringRepository(db)
        )

        result = await svc.process_submission(payload)

        logger.info(
            "RESPONSE | employee_forms_webhook | response_id=%s",
            result
        )

        return success_response(
            data={"response_id": result},
            message="Form response processed successfully"
        )

    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | employee_forms_webhook | %s", e.message)
        return error_response(
            message=e.message,
            status_code=e.status_code,
            errors=e.errors,
        )
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | employee_forms_webhook | %s", e.errors())
        return error_response(
            message="Invalid webhook payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception as e:
        logger.exception("ERROR | employee_forms_webhook")
        return error_response(
            message="Failed to process form response",
            status_code=500
        )


@router.get("/score", response_model=APIResponse[list])
async def get_employee_score(
    employee_email: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_permission("kpis:read"))
):
    logger.info(
        "REQUEST | get_employee_score | user_id=%s | employee_email=%s",
        current_user.user_id,
        employee_email
    )

    try:
        db.info["user_id"] = current_user.user_id

        svc = EmployeeFormService(
            EmployeeFormRepository(db),
            None,
            None
        )

        result = await svc.get_scores(employee_email)
        logger.info(
            "RESPONSE | get_employee_score | user_id=%s | result_count=%s",
            current_user.user_id,
            len(result)
        )

        return success_response(
            data=result,
            message="Scores fetched successfully"
        )

    except Exception as e:
        logger.exception(
            "ERROR | get_employee_score | user_id=%s",
            current_user.user_id
        )
        return error_response(
            message="Failed to fetch scores",
            status_code=500
        )


def _normalize_webhook_payload(raw_payload: dict) -> dict:
    if "form_data" in raw_payload and "company_id" in raw_payload and "form_id" in raw_payload:
        return raw_payload

    parsed = GoogleFormWebhookRequest(**raw_payload)
    form_data = {
        "email": parsed.respondent_email,
        "response_id": parsed.response_id,
    }
    form_data.update(parsed.answers)

    return {
        "company_id": parsed.company_id,
        "form_id": parsed.form_id,
        "form_data": form_data,
    }

