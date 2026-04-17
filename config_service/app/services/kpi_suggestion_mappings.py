from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.kpi import KPI
from config_service.app.models.kpi_questions import KPIQuestion
from config_service.app.models.kpi_suggestion_mapping import KPISuggestionMapping
from config_service.app.models.suggestion import Suggestion
from config_service.app.repositories.kpi import KPIRepository
from config_service.app.repositories.kpi_questions import KPIQuestionRepository
from config_service.app.repositories.kpi_suggestion_mappings import KPISuggestionMappingRepository
from config_service.app.repositories.suggestions import SuggestionRepository
from config_service.app.schemas.kpi_suggestion_mappings import (
    KPISuggestionMappingCreateRequest,
    KPISuggestionMappingListResponse,
    KPISuggestionMappingResponse,
    KPISuggestionMappingUpdateRequest,
)


class KPISuggestionMappingService:
    def __init__(
        self,
        mapping_repo: KPISuggestionMappingRepository,
        kpi_repo: KPIRepository,
        question_repo: KPIQuestionRepository,
        suggestion_repo: SuggestionRepository,
    ):
        self.mapping_repo = mapping_repo
        self.kpi_repo = kpi_repo
        self.question_repo = question_repo
        self.suggestion_repo = suggestion_repo

    async def create(self, payload: KPISuggestionMappingCreateRequest) -> KPISuggestionMappingResponse:
        await self._validate_fk(payload.kpi_key, payload.question_key, payload.suggestion_id)

        mapping = await self.mapping_repo.create(
            KPISuggestionMapping(
                kpi_key=payload.kpi_key,
                trigger_mode=payload.trigger_mode,
                risk_level=payload.risk_level,
                question_key=payload.question_key,
                score_threshold_below=payload.score_threshold_below,
                score_threshold_above=payload.score_threshold_above,
                kpi_score_below=payload.kpi_score_below,
                suggestion_id=payload.suggestion_id,
                priority=payload.priority,
                is_active=payload.is_active,
            )
        )
        return KPISuggestionMappingResponse.model_validate(mapping)

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        kpi_key=None,
        suggestion_id=None,
        trigger_mode: str | None,
        is_active: bool | None,
    ) -> KPISuggestionMappingListResponse:
        items, total = await self.mapping_repo.list(
            skip=skip,
            limit=limit,
            kpi_key=kpi_key,
            suggestion_id=suggestion_id,
            trigger_mode=trigger_mode,
            is_active=is_active,
        )
        return KPISuggestionMappingListResponse(
            items=[KPISuggestionMappingResponse.model_validate(item) for item in items],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get(self, mapping_id) -> KPISuggestionMappingResponse:
        mapping = await self.mapping_repo.get_by_id(mapping_id)
        if not mapping:
            raise BusinessException(message="KPI suggestion mapping not found", status_code=404)
        return KPISuggestionMappingResponse.model_validate(mapping)

    async def update(
        self,
        mapping_id,
        payload: KPISuggestionMappingUpdateRequest,
    ) -> KPISuggestionMappingResponse:
        mapping = await self.mapping_repo.get_by_id(mapping_id)
        if not mapping:
            raise BusinessException(message="KPI suggestion mapping not found", status_code=404)

        new_trigger_mode = payload.trigger_mode or mapping.trigger_mode
        new_risk_level = payload.risk_level if payload.risk_level is not None else mapping.risk_level
        new_question_key = payload.question_key if payload.question_key is not None else mapping.question_key
        new_score_below = (
            payload.score_threshold_below
            if payload.score_threshold_below is not None
            else mapping.score_threshold_below
        )
        new_score_above = (
            payload.score_threshold_above
            if payload.score_threshold_above is not None
            else mapping.score_threshold_above
        )
        self._enforce_rules(
            trigger_mode=new_trigger_mode,
            risk_level=new_risk_level,
            question_key=new_question_key,
            score_threshold_below=new_score_below,
            score_threshold_above=new_score_above,
        )

        if payload.kpi_key is not None:
            await self._validate_fk(payload.kpi_key, None, None)
            mapping.kpi_key = payload.kpi_key
        if payload.question_key is not None:
            await self._validate_fk(None, payload.question_key, None)
            mapping.question_key = payload.question_key
        if payload.suggestion_id is not None:
            await self._validate_fk(None, None, payload.suggestion_id)
            mapping.suggestion_id = payload.suggestion_id

        if payload.trigger_mode is not None:
            mapping.trigger_mode = payload.trigger_mode
        if payload.risk_level is not None:
            mapping.risk_level = payload.risk_level
        if payload.score_threshold_below is not None:
            mapping.score_threshold_below = payload.score_threshold_below
        if payload.score_threshold_above is not None:
            mapping.score_threshold_above = payload.score_threshold_above
        if payload.kpi_score_below is not None:
            mapping.kpi_score_below = payload.kpi_score_below
        if payload.priority is not None:
            mapping.priority = payload.priority
        if payload.is_active is not None:
            mapping.is_active = payload.is_active

        mapping = await self.mapping_repo.update(mapping)
        return KPISuggestionMappingResponse.model_validate(mapping)

    async def delete(self, mapping_id) -> KPISuggestionMappingResponse:
        mapping = await self.mapping_repo.get_by_id(mapping_id)
        if not mapping:
            raise BusinessException(message="KPI suggestion mapping not found", status_code=404)

        mapping.is_active = False
        mapping.is_deleted = True
        mapping = await self.mapping_repo.update(mapping)
        return KPISuggestionMappingResponse.model_validate(mapping)

    async def _validate_fk(
        self,
        kpi_key,
        question_key,
        suggestion_id,
    ):
        if kpi_key is not None:
            kpi = await self.kpi_repo.get_by_id(kpi_key)
            if not kpi:
                raise BusinessException(message="KPI not found", status_code=404)
        if question_key is not None:
            question = await self.question_repo.get_by_id(question_key)
            if not question:
                raise BusinessException(message="Question not found", status_code=404)
        if suggestion_id is not None:
            suggestion = await self.suggestion_repo.get_by_id(suggestion_id)
            if not suggestion:
                raise BusinessException(message="Suggestion not found", status_code=404)

    @staticmethod
    def _enforce_rules(
        *,
        trigger_mode: str,
        risk_level,
        question_key,
        score_threshold_below,
        score_threshold_above,
    ):
        mode = (trigger_mode or "").lower()
        if mode == "kpi_risk":
            if not risk_level:
                raise BusinessException(
                    message="risk_level is required when trigger_mode is kpi_risk",
                    status_code=422,
                )
            if question_key is not None:
                raise BusinessException(
                    message="question_key must be null when trigger_mode is kpi_risk",
                    status_code=422,
                )
            if score_threshold_below is not None or score_threshold_above is not None:
                raise BusinessException(
                    message="score thresholds must be null when trigger_mode is kpi_risk",
                    status_code=422,
                )
        elif mode == "question_score":
            if question_key is None:
                raise BusinessException(
                    message="question_key is required when trigger_mode is question_score",
                    status_code=422,
                )
            if score_threshold_below is None and score_threshold_above is None:
                raise BusinessException(
                    message="at least one score threshold is required",
                    status_code=422,
                )
            if risk_level is not None:
                raise BusinessException(
                    message="risk_level must be null when trigger_mode is question_score",
                    status_code=422,
                )
        elif mode == "both":
            if not risk_level:
                raise BusinessException(
                    message="risk_level is required when trigger_mode is both",
                    status_code=422,
                )
            if question_key is None:
                raise BusinessException(
                    message="question_key is required when trigger_mode is both",
                    status_code=422,
                )
            if score_threshold_below is None and score_threshold_above is None:
                raise BusinessException(
                    message="at least one score threshold is required",
                    status_code=422,
                )
