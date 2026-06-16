from __future__ import annotations
from uuid import UUID

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.badge_master import BadgeMaster
from config_service.app.repositories.badge_master import BadgeMasterRepository
from config_service.app.schemas.badge_admin import (
    BadgeCreateRequest,
    BadgeListResponse,
    BadgeResponse,
    BadgeUpdateRequest,
)


class BadgeAdminService:
    """
    CRUD for badges_master. Validation rules enforced here so the API
    returns consistent 400/409 errors instead of leaking DB constraint
    violations.

    Validation summary:
      * trigger_type='level'           => kpi_key MUST be NULL
      * trigger_type='kpi_completions' => kpi_key MUST be set
      * trigger_type='streak'          => kpi_key either NULL or set
      * (trigger_type, trigger_value, kpi_key) unique (matches the DB
        constraint uq_badges_master_trigger_scoped NULLS NOT DISTINCT)
      * badge_key unique (case-insensitive)

    Edits to a badge after users have earned it leave the existing
    user_badges rows untouched ("freeze on edit"). Re-triggering for the
    new rule happens naturally as users hit the new threshold.
    """

    def __init__(self, repo: BadgeMasterRepository):
        self.repo = repo

    # -------------------------------------------------------------------------
    # Create
    # -------------------------------------------------------------------------

    async def create(self, payload: BadgeCreateRequest) -> BadgeResponse:
        self._validate_trigger_scope(payload.trigger_type, payload.kpi_key)

        # Uniqueness: badge_key
        if await self.repo.get_by_badge_key(payload.badge_key):
            raise BusinessException(
                message=f"badge_key '{payload.badge_key}' already exists",
                status_code=409,
            )

        # Uniqueness: (trigger_type, trigger_value, kpi_key)
        if await self.repo.get_by_trigger(
            trigger_type=payload.trigger_type,
            trigger_value=payload.trigger_value,
            kpi_key=payload.kpi_key,
        ):
            raise BusinessException(
                message=(
                    "Another badge already covers this trigger "
                    f"({payload.trigger_type}, {payload.trigger_value}, "
                    f"kpi_key={payload.kpi_key})"
                ),
                status_code=409,
            )

        badge = await self.repo.create(BadgeMaster(
            badge_key=payload.badge_key,
            label=payload.label,
            icon=payload.icon,
            level=payload.level,
            trigger_type=payload.trigger_type,
            trigger_value=payload.trigger_value,
            kpi_key=payload.kpi_key,
        ))
        return self._to_response(badge)

    # -------------------------------------------------------------------------
    # Read
    # -------------------------------------------------------------------------

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        kpi_key: UUID | None = None,
        trigger_type: str | None = None,
        level: str | None = None,
        is_active: bool | None = None,
        search: str | None = None,
    ) -> BadgeListResponse:
        items, total = await self.repo.list(
            skip=skip, limit=limit,
            kpi_key=kpi_key, trigger_type=trigger_type, level=level,
            is_active=is_active, search=search,
        )
        return BadgeListResponse(
            items=[self._to_response(i) for i in items],
            total=total, skip=skip, limit=limit,
        )

    async def get(self, badge_id: UUID) -> BadgeResponse:
        badge = await self.repo.get_by_id(badge_id)
        if not badge:
            raise BusinessException(message="Badge not found", status_code=404)
        return self._to_response(badge)

    # -------------------------------------------------------------------------
    # Update
    # -------------------------------------------------------------------------

    async def update(self, badge_id: UUID, payload: BadgeUpdateRequest) -> BadgeResponse:
        badge = await self.repo.get_by_id(badge_id)
        if not badge:
            raise BusinessException(message="Badge not found", status_code=404)

        # Compose the post-update state to re-validate scope + uniqueness.
        new_trigger_type = payload.trigger_type or badge.trigger_type
        new_trigger_value = (
            payload.trigger_value if payload.trigger_value is not None
            else badge.trigger_value
        )
        if payload.clear_kpi_key:
            new_kpi_key = None
        elif payload.kpi_key is not None:
            new_kpi_key = payload.kpi_key
        else:
            new_kpi_key = badge.kpi_key

        self._validate_trigger_scope(new_trigger_type, new_kpi_key)

        # Uniqueness re-check if the trigger triple changed
        if (
            new_trigger_type != badge.trigger_type
            or new_trigger_value != badge.trigger_value
            or new_kpi_key != badge.kpi_key
        ):
            clash = await self.repo.get_by_trigger(
                trigger_type=new_trigger_type,
                trigger_value=new_trigger_value,
                kpi_key=new_kpi_key,
            )
            if clash and clash.id != badge.id:
                raise BusinessException(
                    message=(
                        "Another badge already covers this trigger "
                        f"({new_trigger_type}, {new_trigger_value}, "
                        f"kpi_key={new_kpi_key})"
                    ),
                    status_code=409,
                )

        if payload.label is not None:
            badge.label = payload.label
        if payload.icon is not None:
            badge.icon = payload.icon
        if payload.level is not None:
            badge.level = payload.level
        badge.trigger_type = new_trigger_type
        badge.trigger_value = new_trigger_value
        badge.kpi_key = new_kpi_key
        if payload.is_active is not None:
            badge.is_active = payload.is_active

        badge = await self.repo.update(badge)
        return self._to_response(badge)

    # -------------------------------------------------------------------------
    # Delete (soft)
    # -------------------------------------------------------------------------

    async def delete(self, badge_id: UUID) -> BadgeResponse:
        badge = await self.repo.get_by_id(badge_id)
        if not badge:
            raise BusinessException(message="Badge not found", status_code=404)

        # Soft delete keeps user_badges history intact (badge_id FK still
        # resolves). Hard delete would break that history.
        badge.is_active = False
        badge.is_deleted = True
        badge = await self.repo.update(badge)
        return self._to_response(badge)

    # -------------------------------------------------------------------------
    # Internals
    # -------------------------------------------------------------------------

    @staticmethod
    def _validate_trigger_scope(trigger_type: str, kpi_key) -> None:
        if trigger_type == "level" and kpi_key is not None:
            raise BusinessException(
                message="trigger_type='level' badges must have kpi_key=NULL "
                        "(they are global)",
                status_code=400,
            )
        if trigger_type == "kpi_completions" and kpi_key is None:
            raise BusinessException(
                message="trigger_type='kpi_completions' badges require kpi_key",
                status_code=400,
            )
        # 'streak' accepts either.

    @staticmethod
    def _to_response(badge: BadgeMaster) -> BadgeResponse:
        return BadgeResponse(
            id=badge.id,
            badge_key=badge.badge_key,
            label=badge.label,
            icon=badge.icon,
            level=badge.level,
            trigger_type=badge.trigger_type,
            trigger_value=badge.trigger_value,
            kpi_key=badge.kpi_key,
            is_active=bool(badge.is_active),
            is_deleted=bool(badge.is_deleted),
            created_at=badge.created_at,
            updated_at=badge.updated_at,
        )
