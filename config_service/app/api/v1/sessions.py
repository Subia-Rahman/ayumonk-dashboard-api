from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.rbac import require_permission
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.repositories.company_users import UserRepository
from config_service.app.repositories.sessions import SessionRepository
from config_service.app.schemas.sessions import (
    SessionCreateRequest,
    SessionDetailsResponse,
    SessionFormConfigResponse,
    SessionFormSubmissionRequest,
    SessionFormSubmissionResponse,
    SessionGenerateFormRequest,
    SessionGoogleFormResponse,
    SessionQuestionAddRequest,
    SessionQuestionRemoveRequest,
    SessionQuestionSetRequest,
    SessionQuestionOrderUpdateRequest,
    SessionQuestionResponse,
    SessionPublishedLinkListResponse,
    SessionSuggestionListResponse,
    SessionStatusUpdateRequest,
    SessionSummaryResponse,
    SessionUpdateRequest,
)
from config_service.app.services.sessions import SessionService
from config_service.app.core.business_exceptions import BusinessException
from pydantic import ValidationError

logger = get_file_logger(name="sessions_api", prefix="sessions_api")
router = APIRouter(prefix="/sessions", tags=["sessions"])


async def _resolve_company_id(current_user, db: AsyncSession, company_id_param: UUID | None = None):
    if getattr(current_user, "is_platform_admin", False):
        return company_id_param
    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id is None:
        raise BusinessException(message="Admin company not found", status_code=403)
    return tenant_id


@router.get("", response_model=APIResponse[list[SessionSummaryResponse]])
async def list_sessions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:read")),
):
    logger.info(
        "REQUEST | list_sessions | user_id=%s | skip=%s | limit=%s",
        current_user.user_id, skip, limit,
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        service = SessionService(SessionRepository(db))
        result = await service.list_sessions(skip=skip, limit=limit, company_id=resolved)
        logger.info("RESPONSE | list_sessions | user_id=%s | count=%s", current_user.user_id, len(result))
        return success_response(data=result, message="Sessions fetched successfully")
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | list_sessions | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch sessions", status_code=500)


@router.post("", response_model=APIResponse[SessionSummaryResponse])
async def create_session(
    payload: SessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:create")),
):
    logger.info("REQUEST | create_session | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    service = SessionService(SessionRepository(db))
    result = await service.create_session(payload)
    return success_response(data=result, message="Session created successfully")


@router.post("/{session_id}/questions", response_model=APIResponse[list[SessionQuestionResponse]])
async def add_questions_to_session(
    session_id: UUID,
    payload: SessionQuestionAddRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:update")),
):
    logger.info(
        "REQUEST | add_questions_to_session | user_id=%s | session_id=%s",
        current_user.user_id,
        str(session_id),
    )
    db.info["user_id"] = current_user.user_id

    service = SessionService(SessionRepository(db))
    result = await service.add_questions(session_id=session_id, payload=payload)
    return success_response(data=result, message="Questions added to session successfully")


@router.get("/{session_id}/questions", response_model=APIResponse[list[SessionQuestionResponse]])
async def list_session_questions(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:read")),
):
    logger.info(
        "REQUEST | list_session_questions | user_id=%s | session_id=%s",
        current_user.user_id,
        str(session_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SessionService(SessionRepository(db))
        result = await service._build_ordered_questions(session_id)
        return success_response(data=result, message="Session questions fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | list_session_questions | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | list_session_questions | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch session questions", status_code=500)


@router.put("/{session_id}/questions", response_model=APIResponse[list[SessionQuestionResponse]])
async def set_session_questions(
    session_id: UUID,
    payload: SessionQuestionSetRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:update")),
):
    logger.info(
        "REQUEST | set_session_questions | user_id=%s | session_id=%s",
        current_user.user_id,
        str(session_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SessionService(SessionRepository(db))
        result = await service.set_questions(session_id=session_id, payload=payload)
        return success_response(data=result, message="Session questions updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | set_session_questions | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | set_session_questions | %s", e.errors())
        return error_response(
            message="Invalid session questions payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        logger.exception("ERROR | set_session_questions | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update session questions", status_code=500)


@router.delete("/{session_id}/questions", response_model=APIResponse[list[SessionQuestionResponse]])
async def remove_session_questions(
    session_id: UUID,
    payload: SessionQuestionRemoveRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:delete")),
):
    logger.info(
        "REQUEST | remove_session_questions | user_id=%s | session_id=%s",
        current_user.user_id,
        str(session_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SessionService(SessionRepository(db))
        result = await service.remove_questions(session_id=session_id, payload=payload)
        return success_response(data=result, message="Session questions removed successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | remove_session_questions | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | remove_session_questions | %s", e.errors())
        return error_response(
            message="Invalid remove questions payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        logger.exception("ERROR | remove_session_questions | user_id=%s", current_user.user_id)
        return error_response(message="Failed to remove session questions", status_code=500)


@router.delete("/{session_id}/questions/{question_id}", response_model=APIResponse[list[SessionQuestionResponse]])
async def remove_single_session_question(
    session_id: UUID,
    question_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:delete")),
):
    logger.info(
        "REQUEST | remove_single_session_question | user_id=%s | session_id=%s | question_id=%s",
        current_user.user_id,
        str(session_id),
        str(question_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SessionService(SessionRepository(db))
        result = await service.remove_questions(
            session_id=session_id,
            payload=SessionQuestionRemoveRequest(question_ids=[question_id]),
        )
        return success_response(data=result, message="Session question removed successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | remove_single_session_question | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | remove_single_session_question | user_id=%s",
            current_user.user_id,
        )
        return error_response(message="Failed to remove session question", status_code=500)


@router.put("/{session_id}/questions/order", response_model=APIResponse[list[SessionQuestionResponse]])
async def update_session_question_order(
    session_id: UUID,
    payload: SessionQuestionOrderUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:update")),
):
    logger.info(
        "REQUEST | update_session_question_order | user_id=%s | session_id=%s",
        current_user.user_id,
        str(session_id),
    )
    db.info["user_id"] = current_user.user_id

    service = SessionService(SessionRepository(db))
    result = await service.update_question_order(session_id=session_id, payload=payload)
    return success_response(data=result, message="Session question order updated successfully")


@router.patch("/{session_id}/status", response_model=APIResponse[SessionSummaryResponse])
async def activate_or_deactivate_session(
    session_id: UUID,
    payload: SessionStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:update")),
):
    logger.info(
        "REQUEST | activate_or_deactivate_session | user_id=%s | session_id=%s | is_active=%s",
        current_user.user_id, str(session_id), payload.is_active,
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db)
        service = SessionService(SessionRepository(db))
        result = await service.update_session_status(session_id=session_id, is_active=payload.is_active, company_id=resolved)
        message = "Session activated successfully" if payload.is_active else "Session deactivated successfully"
        return success_response(data=result, message=message)
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)


@router.patch("/{session_id}", response_model=APIResponse[SessionSummaryResponse])
async def update_session(
    session_id: UUID,
    payload: SessionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:update")),
):
    logger.info(
        "REQUEST | update_session | user_id=%s | session_id=%s",
        current_user.user_id, str(session_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db)
        service = SessionService(SessionRepository(db))
        result = await service.update_session_details(session_id=session_id, payload=payload, company_id=resolved)
        return success_response(data=result, message="Session updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_session | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_session | %s", e.errors())
        return error_response(message="Invalid session payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | update_session | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update session", status_code=500)


@router.delete("/{session_id}", response_model=APIResponse[SessionSummaryResponse])
async def delete_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:delete")),
):
    logger.info(
        "REQUEST | delete_session | user_id=%s | session_id=%s",
        current_user.user_id, str(session_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db)
        service = SessionService(SessionRepository(db))
        result = await service.delete_session(session_id=session_id, company_id=resolved)
        return success_response(data=result, message="Session deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_session | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_session | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete session", status_code=500)


@router.get("/my-submissions", response_model=APIResponse[list])
async def get_my_submissions(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:read")),
):
    logger.info(
        "REQUEST | get_my_submissions | user_id=%s | email=%s",
        current_user.user_id,
        current_user.email,
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SessionService(SessionRepository(db))
        result = await service.get_user_submitted_sessions(current_user.email)
        return success_response(data=result, message="Submitted sessions fetched successfully")
    except Exception:
        logger.exception("ERROR | get_my_submissions | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch submitted sessions", status_code=500)


@router.get("/my-links", response_model=APIResponse[SessionPublishedLinkListResponse])
async def get_my_session_links(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:read")),
):
    logger.info(
        "REQUEST | get_my_session_links | user_id=%s | email=%s | skip=%s | limit=%s",
        current_user.user_id,
        current_user.email,
        skip,
        limit,
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SessionService(SessionRepository(db))
        result = await service.list_published_links_for_user(
            email=current_user.email,
            skip=skip,
            limit=limit,
        )
        return success_response(data=result, message="Session links fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_my_session_links | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_my_session_links | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch session links", status_code=500)


@router.get("/{session_id}/suggestions", response_model=APIResponse[SessionSuggestionListResponse])
async def get_session_suggestions(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:read")),
):
    logger.info(
        "REQUEST | get_session_suggestions | user_id=%s | session_id=%s",
        current_user.user_id,
        str(session_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SessionService(SessionRepository(db))
        result = await service.get_suggestions_for_user(
            session_id=session_id,
            email=current_user.email,
        )
        return success_response(data=result, message="Suggestions fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_session_suggestions | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_session_suggestions | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch suggestions", status_code=500)


@router.get("/{session_id}", response_model=APIResponse[SessionDetailsResponse])
async def get_session_details(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:read")),
):
    logger.info(
        "REQUEST | get_session_details | user_id=%s | session_id=%s",
        current_user.user_id,
        str(session_id),
    )
    db.info["user_id"] = current_user.user_id

    service = SessionService(SessionRepository(db))
    result = await service.get_session_details(session_id=session_id)
    return success_response(data=result, message="Session details fetched successfully")


@router.post("/{session_id}/generate-google-form", response_model=APIResponse[SessionGoogleFormResponse])
async def generate_google_form(
    session_id: UUID,
    payload: SessionGenerateFormRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:update")),
):
    logger.info(
        "REQUEST | generate_google_form | user_id=%s | session_id=%s | force_regenerate=%s",
        current_user.user_id,
        str(session_id),
        payload.force_regenerate,
    )
    db.info["user_id"] = current_user.user_id

    service = SessionService(SessionRepository(db))
    result = await service.generate_google_form(
        session_id=session_id,
        force_regenerate=payload.force_regenerate,
    )
    return success_response(data=result, message="Google Form generated successfully")


@router.get("/{session_id}/form/preview", response_model=APIResponse[SessionFormConfigResponse])
async def get_session_form_preview(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:read")),
):
    logger.info(
        "REQUEST | get_session_form_preview | user_id=%s | session_id=%s",
        current_user.user_id,
        str(session_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SessionService(SessionRepository(db))
        result = await service.get_form_config(session_id, include_unpublished=True)
        return success_response(data=result, message="Session form preview fetched successfully")
    except BusinessException as e:
        logger.warning(
            "BUSINESS_ERROR | get_session_form_preview | user_id=%s | %s",
            current_user.user_id,
            e.message,
        )
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_session_form_preview | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch session form preview", status_code=500)


@router.get("/{session_id}/form", response_model=APIResponse[SessionFormConfigResponse])
async def get_session_form(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        "REQUEST | get_session_form | session_id=%s | client=%s",
        str(session_id),
        request.client.host if request.client else "unknown",
    )
    db.info["user_id"] = 0

    try:
        service = SessionService(SessionRepository(db))
        result = await service.get_form_config(session_id, include_unpublished=False)
        return success_response(data=result, message="Session form fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_session_form | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_session_form")
        return error_response(message="Failed to fetch session form", status_code=500)


@router.post("/{session_id}/publish", response_model=APIResponse[SessionFormConfigResponse])
async def publish_session_form(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("sessions:update")),
):
    logger.info(
        "REQUEST | publish_session_form | user_id=%s | session_id=%s",
        current_user.user_id,
        str(session_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        service = SessionService(SessionRepository(db))
        result = await service.publish_form(session_id)
        return success_response(data=result, message="Session form published successfully")
    except BusinessException as e:
        logger.warning(
            "BUSINESS_ERROR | publish_session_form | user_id=%s | %s",
            current_user.user_id,
            e.message,
        )
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | publish_session_form | user_id=%s", current_user.user_id)
        return error_response(message="Failed to publish session form", status_code=500)


@router.post("/{session_id}/form/submit", response_model=APIResponse[SessionFormSubmissionResponse])
async def submit_session_form(
    session_id: UUID,
    payload: SessionFormSubmissionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    logger.info(
        "REQUEST | submit_session_form | session_id=%s | client=%s",
        str(session_id),
        request.client.host if request.client else "unknown",
    )
    db.info["user_id"] = 0

    try:
        service = SessionService(SessionRepository(db))
        result = await service.submit_form(session_id, payload)
        return success_response(data=result, message="Session form submitted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | submit_session_form | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | submit_session_form | %s", e.errors())
        return error_response(
            message="Invalid submission payload",
            status_code=422,
            errors=e.errors(),
        )
    except Exception:
        logger.exception("ERROR | submit_session_form")
        return error_response(message="Failed to submit session form", status_code=500)
