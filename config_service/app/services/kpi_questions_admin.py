from __future__ import annotations
from config_service.app.core.business_exceptions import BusinessException
from sqlalchemy.exc import IntegrityError
from config_service.app.core.config import settings
from config_service.app.models.kpi_questions import KPIQuestion
from config_service.app.models.kpi_scoring import KPIScoring
from config_service.app.schemas.kpi_questions_admin import (
    KPIQuestionCreateRequest,
    KPIQuestionListResponse,
    KPIQuestionResponse,
    KPIQuestionUpdateRequest,
    KPIScoringOptionResponse,
)


class KPIQuestionAdminService:
    def __init__(self, question_repo, scoring_repo, theme_repo, kpi_repo):
        self.question_repo = question_repo
        self.scoring_repo = scoring_repo
        self.theme_repo = theme_repo
        self.kpi_repo = kpi_repo

    async def create(self, payload: KPIQuestionCreateRequest) -> KPIQuestionResponse:
        if not payload.company_id:
            raise BusinessException(message="company_id is required", status_code=400)

        await self._validate_refs(payload.theme_key, payload.kpi_key, payload.company_id)

        existing = await self.question_repo.get_by_code(payload.question_code, payload.company_id)
        if existing:
            raise BusinessException(message="Question code already exists", status_code=409)

        try:
            question = await self.question_repo.create(
                KPIQuestion(
                    company_id=payload.company_id,
                    theme=payload.theme_key,
                    kpi=payload.kpi_key,
                    question_code=payload.question_code,
                    question_text=payload.question_text,
                    reverse_code=payload.reverse_code,
                )
            )
        except IntegrityError as e:
            raise BusinessException(message="Question code already exists", status_code=409) from e

        await self.scoring_repo.delete_by_question(question.id)
        for option in payload.options:
            await self.scoring_repo.create(
                KPIScoring(
                    company_id=question.company_id,
                    question_id=question.id,
                    option_number=option.option_number,
                    option_text=option.option_text,
                    score=option.score,
                )
            )

        return await self._build_response(question)

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        company_id=None,
        kpi_key=None,
        theme_key=None,
        search: str | None,
        is_active: bool | None = True,
    ) -> KPIQuestionListResponse:
        items, total = await self.question_repo.list(
            skip=skip,
            limit=limit,
            company_id=company_id,
            kpi_key=kpi_key,
            theme_key=theme_key,
            search=search,
            is_active=is_active,
        )
        responses = []
        for item in items:
            responses.append(await self._build_response(item))
        return KPIQuestionListResponse(items=responses, total=total, skip=skip, limit=limit)

    async def get(self, question_id) -> KPIQuestionResponse:
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            raise BusinessException(message="KPI question not found", status_code=404)
        return await self._build_response(question)

    async def update(self, question_id, payload: KPIQuestionUpdateRequest) -> KPIQuestionResponse:
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            raise BusinessException(message="KPI question not found", status_code=404)

        if payload.theme_key is not None or payload.kpi_key is not None:
            await self._validate_refs(
                payload.theme_key or question.theme,
                payload.kpi_key or question.kpi,
            )

        if payload.question_code and payload.question_code != question.question_code:
            existing = await self.question_repo.get_by_code(payload.question_code)
            if existing and existing.id != question.id:
                raise BusinessException(message="Question code already exists", status_code=409)
            question.question_code = payload.question_code

        if payload.question_text is not None:
            question.question_text = payload.question_text
        if payload.reverse_code is not None:
            question.reverse_code = payload.reverse_code
        if payload.theme_key is not None:
            question.theme = payload.theme_key
        if payload.kpi_key is not None:
            question.kpi = payload.kpi_key

        try:
            question = await self.question_repo.save(question)
        except IntegrityError as e:
            raise BusinessException(message="Question code already exists", status_code=409) from e

        if payload.options is not None:
            await self.scoring_repo.delete_by_question(question.id)
            for option in payload.options:
                await self.scoring_repo.create(
                    KPIScoring(
                        company_id=question.company_id,
                        question_id=question.id,
                        option_number=option.option_number,
                        option_text=option.option_text,
                        score=option.score,
                    )
                )

        return await self._build_response(question)

    async def delete(self, question_id) -> KPIQuestionResponse:
        question = await self.question_repo.get_by_id(question_id)
        if not question:
            raise BusinessException(message="KPI question not found", status_code=404)

        question.is_active = False
        question.is_deleted = True
        question = await self.question_repo.save(question)
        return await self._build_response(question)

    async def _build_response(self, question: KPIQuestion) -> KPIQuestionResponse:
        try:
            options = await self.scoring_repo.list_by_question(question.id)
        except Exception as e:
            raise BusinessException(
                message="Failed to load scoring options",
                status_code=500,
                errors=str(e) if settings.DEBUG_ERRORS else None,
            )
        option_responses = [
            KPIScoringOptionResponse(
                option_number=o.option_number,
                option_text=o.option_text or "",
                score=o.score,
            )
            for o in options
        ]
        return KPIQuestionResponse(
            id=question.id,
            company_id=question.company_id,
            theme_key=question.theme,
            kpi_key=question.kpi,
            question_code=question.question_code,
            question_text=question.question_text,
            reverse_code=bool(question.reverse_code),
            is_active=bool(question.is_active),
            options=option_responses,
        )

    async def _validate_refs(self, theme_key, kpi_key, company_id=None) -> None:
        theme = await self.theme_repo.get_by_id(theme_key, company_id)
        if not theme:
            raise BusinessException(message="Theme not found", status_code=404)
        kpi = await self.kpi_repo.get_by_id(kpi_key, company_id)
        if not kpi:
            raise BusinessException(message="KPI not found", status_code=404)
