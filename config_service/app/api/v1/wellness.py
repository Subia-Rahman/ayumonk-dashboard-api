"""Wellness endpoints (Phase 3).

  * GET  /api/v1/wellness/index — returns the headline donut value +
    risk band + week_delta for the authenticated user. Read-only
    lookup against ``theme_submission_scores``; rows are populated
    synchronously by the form-submission write path.

  * POST /api/v1/wellness/mood  — single 5-emoji tap. Persists to
    ``user_mood_log``. 1=😞 / 2=😕 / 3=😐 / 4=🙂 / 5=😄.

Both endpoints are user-scoped: the JWT subject's email is the lookup /
write key. No company_id query param — the user's own row is the answer
regardless of which company they belong to.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.schemas.wellness import (
    WellnessIndexResponse,
    WellnessMoodRequest,
    WellnessMoodResponse,
    WellnessMoodTodayResponse,
)
from config_service.app.services.wellness import (
    WellnessIndexService,
    WellnessMoodService,
)


logger = get_file_logger(name="wellness_api", prefix="wellness_api")
router = APIRouter(prefix="/wellness", tags=["wellness"])


@router.get("/index", response_model=APIResponse[WellnessIndexResponse])
async def get_wellness_index(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Returns the most recent Wellness Index row for the caller.

    Spec §8.2: powers the donut centre (``overall_score`` 0-100), the
    risk-band label below, and the ``▲/▼ X%`` delta badge vs prior
    submission. 404 when the user has never submitted a scorable
    wellness form.
    """
    logger.info(
        "REQUEST | get_wellness_index | user_id=%s | email=%s",
        current_user.user_id,
        current_user.email,
    )
    db.info["user_id"] = current_user.user_id

    try:
        row = await WellnessIndexService(db).get_latest_for_email(
            current_user.email
        )
        return success_response(
            data=WellnessIndexResponse(
                overall_score=row.overall_score,
                risk_level=row.risk_level,
                week_delta=row.week_delta,
                computed_at=row.created_at,
                response_id=row.response_id,
                theme_key=row.theme_key,
            ),
            message="Wellness index fetched successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | get_wellness_index | %s", e.message)
        return error_response(
            message=e.message, status_code=e.status_code, errors=e.errors
        )
    except Exception:
        logger.exception(
            "ERROR | get_wellness_index | user_id=%s", current_user.user_id
        )
        return error_response(
            message="Failed to fetch wellness index", status_code=500
        )


@router.get("/mood/today", response_model=APIResponse[WellnessMoodTodayResponse])
async def get_mood_today(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Returns the caller's most-recent mood entry for today (server-time
    date), or ``logged=False`` when nothing's been logged yet.

    Frontend uses this to lock the 5-emoji card on the Wellness page —
    replaces the localStorage-based check that leaked between users on
    a shared browser (the JWT email scopes the answer per-user)."""
    logger.info(
        "REQUEST | get_mood_today | user_id=%s | email=%s",
        current_user.user_id,
        current_user.email,
    )
    db.info["user_id"] = current_user.user_id

    try:
        row = await WellnessMoodService(db).get_today_for_email(
            current_user.email
        )
        if row is None:
            return success_response(
                data=WellnessMoodTodayResponse(logged=False),
                message="No mood logged yet for today",
            )
        return success_response(
            data=WellnessMoodTodayResponse(
                logged=True,
                id=row.id,
                score=row.score,
                logged_at=row.logged_at,
            ),
            message="Today's mood fetched successfully",
        )
    except Exception:
        logger.exception(
            "ERROR | get_mood_today | user_id=%s", current_user.user_id
        )
        return error_response(
            message="Failed to fetch today's mood", status_code=500
        )


@router.post("/mood", response_model=APIResponse[WellnessMoodResponse])
async def submit_mood(
    payload: WellnessMoodRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Persist a single 5-emoji mood tap to ``user_mood_log``.

    Spec §8.2: one-tap submission feeds the future EMOTIONAL_KPI rollup
    (the rollup itself is Phase 3.5+; this endpoint stops at
    persistence so the UI button is wired today).
    """
    logger.info(
        "REQUEST | submit_mood | user_id=%s | email=%s | score=%s",
        current_user.user_id,
        current_user.email,
        payload.score,
    )
    db.info["user_id"] = current_user.user_id

    try:
        # Best-effort resolution of company_id + UUID user_id (matches
        # company_users.id). When the JWT subject isn't yet a
        # CompanyUsers row, leave both NULL — the mood row is still
        # usable via employee_email + actor_user_id (from JWT).
        company_id: UUID | None = getattr(current_user, "tenant_id", None)
        row = await WellnessMoodService(db).submit(
            email=current_user.email,
            score=payload.score,
            company_id=company_id,
            user_id=None,
            actor_user_id=current_user.user_id,
        )
        return success_response(
            data=WellnessMoodResponse(
                id=row.id,
                score=row.score,
                logged_at=row.logged_at,
            ),
            message="Mood logged successfully",
        )
    except BusinessException as e:
        logger.warning("BUSINESS_ERROR | submit_mood | %s", e.message)
        return error_response(
            message=e.message, status_code=e.status_code, errors=e.errors
        )
    except ValidationError as e:
        logger.warning("VALIDATION_ERROR | submit_mood | %s", e.errors())
        return error_response(
            message="Invalid mood payload", status_code=422, errors=e.errors()
        )
    except Exception:
        logger.exception("ERROR | submit_mood | user_id=%s", current_user.user_id)
        return error_response(message="Failed to submit mood", status_code=500)
