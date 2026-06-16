from __future__ import annotations
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.suggestion import Suggestion
from config_service.app.repositories.suggestions import SuggestionRepository
from config_service.app.schemas.suggestions import (
    SuggestionCreateRequest,
    SuggestionListResponse,
    SuggestionResponse,
    SuggestionUpdateRequest,
)


class SuggestionService:
    def __init__(self, repo: SuggestionRepository):
        self.repo = repo

    async def create(self, payload: SuggestionCreateRequest) -> SuggestionResponse:
        suggestion = await self.repo.create(
            Suggestion(
                suggestion_type=payload.suggestion_type,
                title=payload.title,
                description=payload.description,
                url=payload.url,
                dosha_type=payload.dosha_type,
                difficulty=payload.difficulty,
                duration_mins=payload.duration_mins,
                is_active=payload.is_active,
            )
        )
        return SuggestionResponse.model_validate(suggestion)

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        search: str | None,
        suggestion_type: str | None,
        is_active: bool | None,
    ) -> SuggestionListResponse:
        items, total = await self.repo.list(
            skip=skip,
            limit=limit,
            search=search,
            suggestion_type=suggestion_type,
            is_active=is_active,
        )
        return SuggestionListResponse(
            items=[SuggestionResponse.model_validate(item) for item in items],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get(self, suggestion_id) -> SuggestionResponse:
        suggestion = await self.repo.get_by_id(suggestion_id)
        if not suggestion:
            raise BusinessException(message="Suggestion not found", status_code=404)
        return SuggestionResponse.model_validate(suggestion)

    async def update(self, suggestion_id, payload: SuggestionUpdateRequest) -> SuggestionResponse:
        suggestion = await self.repo.get_by_id(suggestion_id)
        if not suggestion:
            raise BusinessException(message="Suggestion not found", status_code=404)

        if payload.suggestion_type is not None:
            suggestion.suggestion_type = payload.suggestion_type
        if payload.title is not None:
            suggestion.title = payload.title
        if payload.description is not None:
            suggestion.description = payload.description
        if payload.url is not None:
            suggestion.url = payload.url
        if payload.dosha_type is not None:
            suggestion.dosha_type = payload.dosha_type
        if payload.difficulty is not None:
            suggestion.difficulty = payload.difficulty
        if payload.duration_mins is not None:
            suggestion.duration_mins = payload.duration_mins
        if payload.is_active is not None:
            suggestion.is_active = payload.is_active

        suggestion = await self.repo.update(suggestion)
        return SuggestionResponse.model_validate(suggestion)

    async def delete(self, suggestion_id) -> SuggestionResponse:
        suggestion = await self.repo.get_by_id(suggestion_id)
        if not suggestion:
            raise BusinessException(message="Suggestion not found", status_code=404)

        suggestion.is_active = False
        suggestion.is_deleted = True
        suggestion = await self.repo.update(suggestion)
        return SuggestionResponse.model_validate(suggestion)
