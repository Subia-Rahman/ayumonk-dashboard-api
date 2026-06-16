from __future__ import annotations
from uuid import UUID

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.theme import Theme
from config_service.app.schemas.theme import (
    ThemeCreateRequest,
    ThemeListResponse,
    ThemeResponse,
    ThemeUpdateRequest,
)


class ThemeService:
    def __init__(self, repo):
        self.repo = repo

    async def create(self, payload: ThemeCreateRequest) -> ThemeResponse:
        existing = await self.repo.get_by_name_ci(payload.theme_display_name, payload.company_id)
        if existing:
            raise BusinessException(message="Theme name already exists", status_code=409)

        theme = await self.repo.create(
            Theme(
                company_id=payload.company_id,
                theme_display_name=payload.theme_display_name,
                description=payload.description,
                duration_days=payload.duration_days,
                target_audience=payload.target_audience,
            )
        )
        return self._to_response(theme)

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        company_id: UUID | None = None,
        search: str | None = None,
        is_active: bool | None = True,
    ) -> ThemeListResponse:
        items, total = await self.repo.list(
            skip=skip,
            limit=limit,
            company_id=company_id,
            search=search,
            is_active=is_active,
        )
        return ThemeListResponse(
            items=[self._to_response(item) for item in items],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get(self, theme_key, company_id: UUID | None = None) -> ThemeResponse:
        theme = await self.repo.get_by_id(theme_key, company_id)
        if not theme:
            raise BusinessException(message="Theme not found", status_code=404)
        return self._to_response(theme)

    async def update(self, theme_key, payload: ThemeUpdateRequest, company_id: UUID | None = None) -> ThemeResponse:
        theme = await self.repo.get_by_id(theme_key, company_id)
        if not theme:
            raise BusinessException(message="Theme not found", status_code=404)

        if payload.theme_display_name and payload.theme_display_name != theme.theme_display_name:
            existing = await self.repo.get_by_name_ci(payload.theme_display_name, theme.company_id)
            if existing and existing.theme_key != theme.theme_key:
                raise BusinessException(message="Theme name already exists", status_code=409)
            theme.theme_display_name = payload.theme_display_name

        if payload.is_active is not None:
            theme.is_active = payload.is_active
        if payload.description is not None:
            theme.description = payload.description
        if payload.duration_days is not None:
            theme.duration_days = payload.duration_days
        if payload.target_audience is not None:
            theme.target_audience = payload.target_audience

        theme = await self.repo.update(theme)
        return self._to_response(theme)

    async def delete(self, theme_key, company_id: UUID | None = None) -> ThemeResponse:
        theme = await self.repo.get_by_id(theme_key, company_id)
        if not theme:
            raise BusinessException(message="Theme not found", status_code=404)

        theme.is_active = False
        theme.is_deleted = True
        theme = await self.repo.update(theme)
        return self._to_response(theme)

    @staticmethod
    def _to_response(theme: Theme) -> ThemeResponse:
        return ThemeResponse(
            theme_key=theme.theme_key,
            company_id=theme.company_id,
            theme_display_name=theme.theme_display_name,
            description=theme.description,
            duration_days=theme.duration_days,
            target_audience=theme.target_audience,
            is_active=bool(theme.is_active),
            created_at=theme.created_at,
            updated_at=theme.updated_at,
        )
