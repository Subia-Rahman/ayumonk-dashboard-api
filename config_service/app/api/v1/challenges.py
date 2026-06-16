from __future__ import annotations
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from authentication_service.app.core.rbac import require_permission
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.repositories.challenge import ChallengeRepository
from config_service.app.repositories.company_users import UserRepository
from config_service.app.repositories.kpi import KPIRepository
from config_service.app.repositories.kpi_challenge import KPIChallengeRepository
from config_service.app.core.audit_helper import safe_audit_log
from config_service.app.schemas.challenge import (
    ChallengeCreateRequest,
    ChallengeDetailResponse,
    ChallengeKPIMappingRequest,
    ChallengeKPIMappingResponse,
    ChallengeListResponse,
    ChallengeResponse,
    ChallengeUpdateRequest,
    KPIChallengeUpdateRequest,
)
from config_service.app.schemas.challenge_schedule import (
    ChallengeKpiSummary,
    ChallengeScheduleItem,
    ChallengeScheduleResponse,
)
from config_service.app.services.challenge import ChallengeService
from config_service.app.services.challenge_schedule import ChallengeScheduleService


logger = get_file_logger(name="challenge_api", prefix="challenge_api")
router = APIRouter(prefix="/challenges", tags=["challenges"])


async def _resolve_company_id(current_user, db: AsyncSession, company_id_param: UUID | None = None):
    if getattr(current_user, "is_platform_admin", False):
        return company_id_param
    tenant_id = getattr(current_user, "tenant_id", None)
    if tenant_id is None:
        raise BusinessException(message="Admin company not found", status_code=403)
    return tenant_id


def _make_service(db):
    return ChallengeService(ChallengeRepository(db), KPIRepository(db), KPIChallengeRepository(db))


@router.get("", response_model=APIResponse[ChallengeListResponse])
async def list_challenges(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    search: str | None = None,
    is_active: bool | None = True,
    kpi_key: UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("challenges:read")),
):
    logger.info(
        "REQUEST | list_challenges | user_id=%s | skip=%s | limit=%s | active=%s",
        current_user.user_id, skip, limit, is_active,
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        result = await _make_service(db).list(
            skip=skip, limit=limit, company_id=resolved,
            search=search, is_active=is_active,
            kpi_key=kpi_key, start_date=start_date, end_date=end_date,
        )
        return success_response(data=result, message="Challenges fetched successfully")
    except BusinessException as e:
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | list_challenges | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch challenges", status_code=500)


_SCHEDULE_STATUSES = {"active", "upcoming", "ended", "paused"}


@router.get("/schedule", response_model=APIResponse[ChallengeScheduleResponse])
async def get_challenge_schedule(
    status: str | None = Query(
        default=None,
        description=(
            "Optional comma-separated status filter — any of "
            "'active', 'upcoming', 'ended', 'paused'. Omit to return all."
        ),
    ),
    kpi_key: UUID | None = Query(
        default=None,
        description="Optional — narrow to a single KPI.",
    ),
    company_id: UUID | None = Query(
        default=None,
        description=(
            "Required for platform admins; ignored for company-tier callers "
            "(forced to their own tenant)."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Timeline view of every kpi_challenges row for the caller's company.

    Returns two collections (see ``ChallengeScheduleResponse``):
      * ``items`` — one row per kpi_challenges, status + days_* computed.
      * ``kpi_summary`` — rolled up to one row per ``DISTINCT kpi_key``
        for the HR Analytics dashboard's KPI Schedule Calendar.

    Auth: any authenticated user. Tenant scoping uses the same pattern as
    every other endpoint in this router — platform admins may pass
    ``company_id`` explicitly; everyone else is forced to their tenant.
    """
    logger.info(
        "REQUEST | get_challenge_schedule | user_id=%s | status=%s | kpi_key=%s "
        "| company_id=%s",
        current_user.user_id, status, kpi_key, company_id,
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        status_filter: set[str] | None = None
        if status:
            requested = {s.strip().lower() for s in status.split(",") if s.strip()}
            unknown = requested - _SCHEDULE_STATUSES
            if unknown:
                raise BusinessException(
                    message=(
                        "Unknown status value(s): "
                        + ", ".join(sorted(unknown))
                        + ". Allowed: active, upcoming, ended, paused."
                    ),
                    status_code=400,
                )
            status_filter = requested

        result = await ChallengeScheduleService(db).get_schedule(
            company_id=resolved,
            status_filter=status_filter,
            kpi_key=kpi_key,
        )
        return success_response(
            data=ChallengeScheduleResponse(
                items=[ChallengeScheduleItem(**i) for i in result["items"]],
                kpi_summary=[
                    ChallengeKpiSummary(**s) for s in result["kpi_summary"]
                ],
            ),
            message="Challenge schedule fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_challenge_schedule | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception(
            "ERROR | get_challenge_schedule | user_id=%s", current_user.user_id
        )
        return error_response(message="Failed to fetch challenge schedule", status_code=500)


@router.get("/{challenge_key}", response_model=APIResponse[ChallengeDetailResponse])
async def get_challenge(
    challenge_key: UUID,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("challenges:read")),
):
    logger.info(
        "REQUEST | get_challenge | user_id=%s | challenge_key=%s",
        current_user.user_id, str(challenge_key),
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        result = await _make_service(db).get(challenge_key, resolved)
        return success_response(data=result, message="Challenge fetched successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_challenge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | get_challenge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch challenge", status_code=500)


@router.post("", response_model=APIResponse[ChallengeDetailResponse])
async def create_challenge(
    payload: ChallengeCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("challenges:create")),
):
    logger.info("REQUEST | create_challenge | user_id=%s", current_user.user_id)
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, payload.company_id)
        payload.company_id = resolved
        result = await _make_service(db).create(payload)
        return success_response(data=result, message="Challenge created successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | create_challenge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | create_challenge | %s", e.errors())
        return error_response(message="Invalid challenge payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | create_challenge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to create challenge", status_code=500)


@router.put("/{challenge_key}", response_model=APIResponse[ChallengeResponse])
async def update_challenge(
    challenge_key: UUID,
    payload: ChallengeUpdateRequest,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("challenges:update")),
):
    logger.info(
        "REQUEST | update_challenge | user_id=%s | challenge_key=%s",
        current_user.user_id, str(challenge_key),
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        result = await _make_service(db).update(challenge_key, payload, resolved)
        return success_response(data=result, message="Challenge updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_challenge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_challenge | %s", e.errors())
        return error_response(message="Invalid challenge payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | update_challenge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update challenge", status_code=500)


@router.delete("/{challenge_key}", response_model=APIResponse[ChallengeResponse])
async def delete_challenge(
    challenge_key: UUID,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("challenges:delete")),
):
    logger.info(
        "REQUEST | delete_challenge | user_id=%s | challenge_key=%s",
        current_user.user_id, str(challenge_key),
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        result = await _make_service(db).delete(challenge_key, resolved)
        return success_response(data=result, message="Challenge deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_challenge | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_challenge | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete challenge", status_code=500)


@router.post("/{challenge_key}/kpi-mappings", response_model=APIResponse[ChallengeKPIMappingResponse])
async def add_kpi_mapping(
    challenge_key: UUID,
    payload: ChallengeKPIMappingRequest,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("challenges:update")),
):
    logger.info(
        "REQUEST | add_kpi_mapping | user_id=%s | challenge_key=%s",
        current_user.user_id, str(challenge_key),
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        result = await _make_service(db).add_kpi_mapping(
            challenge_key=challenge_key, mapping=payload, company_id=resolved
        )
        await safe_audit_log(
            db,
            user_id=current_user.user_id,
            tenant_id=resolved,
            action="KPI_CHALLENGE_CREATED",
            entity="kpi_challenges",
            new_value={
                "id": result.id,
                "challenge_key": challenge_key,
                "kpi_key": result.kpi_key,
                "start_date": result.start_date,
                "end_date": result.end_date,
            },
            logger=logger,
        )
        return success_response(data=result, message="KPI mapping added successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | add_kpi_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | add_kpi_mapping | %s", e.errors())
        return error_response(message="Invalid KPI mapping payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | add_kpi_mapping | user_id=%s", current_user.user_id)
        return error_response(message="Failed to add KPI mapping", status_code=500)


@router.put(
    "/kpi-mappings/{mapping_id}",
    response_model=APIResponse[ChallengeKPIMappingResponse],
)
async def update_kpi_mapping(
    mapping_id: UUID,
    payload: KPIChallengeUpdateRequest,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("challenges:update")),
):
    """Patch start_date / end_date / is_active on an existing kpi_challenges
    row — covers the spec's extend / pause / resume workflows in a single
    endpoint. All three body fields are optional."""
    logger.info(
        "REQUEST | update_kpi_mapping | user_id=%s | mapping_id=%s",
        current_user.user_id, str(mapping_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        result, old_snapshot = await _make_service(db).update_kpi_mapping(
            mapping_id=mapping_id, payload=payload, company_id=resolved
        )
        await safe_audit_log(
            db,
            user_id=current_user.user_id,
            tenant_id=resolved,
            action="KPI_CHALLENGE_UPDATED",
            entity="kpi_challenges",
            old_value=old_snapshot,
            new_value={
                "id": result.id,
                "start_date": result.start_date,
                "end_date": result.end_date,
                # is_active not in ChallengeKPIMappingResponse — pulled from
                # payload because the service has already applied it.
                "is_active": (
                    payload.is_active
                    if payload.is_active is not None
                    else old_snapshot["is_active"]
                ),
            },
            logger=logger,
        )
        return success_response(data=result, message="KPI mapping updated successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | update_kpi_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | update_kpi_mapping | %s", e.errors())
        return error_response(message="Invalid KPI mapping payload", status_code=422, errors=e.errors())
    except Exception:
        logger.exception("ERROR | update_kpi_mapping | user_id=%s", current_user.user_id)
        return error_response(message="Failed to update KPI mapping", status_code=500)


@router.delete(
    "/kpi-mappings/{mapping_id}",
    response_model=APIResponse[ChallengeKPIMappingResponse],
)
async def delete_kpi_mapping(
    mapping_id: UUID,
    company_id: UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("challenges:delete")),
):
    """Soft-delete a kpi_challenges row. Sets ``is_deleted=TRUE`` +
    ``is_active=FALSE`` so it disappears from every existing list query
    and from the new ``/challenges/schedule`` endpoint."""
    logger.info(
        "REQUEST | delete_kpi_mapping | user_id=%s | mapping_id=%s",
        current_user.user_id, str(mapping_id),
    )
    db.info["user_id"] = current_user.user_id

    try:
        resolved = await _resolve_company_id(current_user, db, company_id)
        result, old_snapshot = await _make_service(db).delete_kpi_mapping(
            mapping_id=mapping_id, company_id=resolved
        )
        await safe_audit_log(
            db,
            user_id=current_user.user_id,
            tenant_id=resolved,
            action="KPI_CHALLENGE_DELETED",
            entity="kpi_challenges",
            old_value=old_snapshot,
            new_value={"id": result.id, "is_deleted": True, "is_active": False},
            logger=logger,
        )
        return success_response(data=result, message="KPI mapping deleted successfully")
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | delete_kpi_mapping | %s", e.message)
        return error_response(message=e.message, status_code=e.status_code, errors=e.errors)
    except Exception:
        logger.exception("ERROR | delete_kpi_mapping | user_id=%s", current_user.user_id)
        return error_response(message="Failed to delete KPI mapping", status_code=500)
