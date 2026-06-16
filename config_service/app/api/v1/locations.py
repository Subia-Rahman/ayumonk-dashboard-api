from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.dependencies import get_current_user
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import error_response, success_response
from config_service.app.schemas.locations import LocationListResponse, LocationResponse
from config_service.app.services.locations import list_locations


logger = get_file_logger(name="locations_api", prefix="locations_api")

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("", response_model=APIResponse[LocationListResponse])
async def list_all_locations(
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    search: str | None = Query(default=None, description="Case-insensitive substring filter on the location name"),
    is_active: bool | None = Query(default=True),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    logger.info(
        "REQUEST | list_locations | user_id=%s | skip=%s | limit=%s | search=%s | is_active=%s",
        current_user.user_id,
        skip,
        limit,
        search,
        is_active,
    )
    db.info["user_id"] = current_user.user_id

    try:
        items, total = await list_locations(
            db,
            skip=skip,
            limit=limit,
            search=search,
            is_active=is_active,
        )
        payload = LocationListResponse(
            items=[LocationResponse.model_validate(item) for item in items],
            total=total,
            skip=skip,
            limit=limit,
        )
        return success_response(data=payload, message="Locations fetched successfully")
    except Exception:
        logger.exception("ERROR | list_locations | user_id=%s", current_user.user_id)
        return error_response(message="Failed to fetch locations", status_code=500)
