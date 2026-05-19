from datetime import datetime
from uuid import UUID, uuid4
from uuid import UUID as UUIDType

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.config import settings
from config_service.app.models.session import Session
from config_service.app.models.kpi import KPI
from config_service.app.schemas.sessions import (
    SessionCreateRequest,
    SessionDetailsResponse,
    SessionFormConfigResponse,
    SessionFormQuestionResponse,
    SessionFormSubmissionRequest,
    SessionFormSubmissionResponse,
    SessionGoogleFormResponse,
    SessionKPIResponse,
    SessionQuestionAddRequest,
    SessionQuestionRemoveRequest,
    SessionQuestionSetRequest,
    SessionQuestionOrderUpdateRequest,
    SessionQuestionResponse,
    SessionPublishedLinkListResponse,
    SessionPublishedLinkResponse,
    SessionSuggestionItem,
    SessionSuggestionListResponse,
    SessionSuggestionTrigger,
    SessionSummaryResponse,
    SessionThemeResponse,
    SessionUpdateRequest,
)
from config_service.app.services.google_form_generation import GoogleFormGenerationService
from config_service.app.services.email_client import EmailClient
from config_service.app.repositories.company_users import UserRepository as CompanyUserRepository
import logging
from config_service.app.services.employee_form import EmployeeFormService
from config_service.app.repositories.employee_form import EmployeeFormRepository
from config_service.app.repositories.kpi_questions import KPIQuestionRepository
from config_service.app.repositories.kpi_scoring import KPIScoringRepository
from config_service.app.models.session_question import SessionQuestion
from config_service.app.models.kpi_suggestion_mapping import KPISuggestionMapping
from config_service.app.models.suggestion import Suggestion
from sqlalchemy import select, func


class SessionService:
    def __init__(self, session_repo):
        self.session_repo = session_repo
        self.form_generator = GoogleFormGenerationService()
        self.logger = logging.getLogger(__name__)

    async def create_session(self, payload: SessionCreateRequest) -> SessionSummaryResponse:
        if not payload.company_id:
            raise BusinessException(message="company_id is required", status_code=422)
        session = await self.session_repo.create_session(
            Session(
                title=payload.title.strip(),
                description=payload.description,
                company_id=payload.company_id,
            )
        )
        return self._to_summary(session)

    async def list_sessions(self, skip: int = 0, limit: int = 100, company_id=None) -> list[SessionSummaryResponse]:
        sessions = await self.session_repo.list_sessions(skip=skip, limit=limit, company_id=company_id)
        return [self._to_summary(session) for session in sessions]

    async def add_questions(self, session_id: UUID, payload: SessionQuestionAddRequest) -> list[SessionQuestionResponse]:
        session = await self.session_repo.get_session(session_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        unique_question_ids = list(dict.fromkeys(payload.question_ids))
        available_questions = await self.session_repo.get_questions_by_ids(unique_question_ids)
        available_question_ids = {q.id for q in available_questions}
        missing_question_ids = [str(qid) for qid in unique_question_ids if qid not in available_question_ids]
        if missing_question_ids:
            raise BusinessException(
                message="Some questions do not exist",
                status_code=400,
                errors={"missing_question_ids": missing_question_ids},
            )

        existing_ids = await self.session_repo.get_existing_session_question_ids(session_id)
        ids_to_add = [qid for qid in unique_question_ids if qid not in existing_ids]
        if not ids_to_add:
            return await self._build_ordered_questions(session_id)

        existing_rows = await self.session_repo.list_session_questions_all(session_id)
        existing_by_question = {row.question_id: row for row in existing_rows}

        max_order = await self.session_repo.get_max_display_order(session_id)
        order = max_order
        new_entities = []
        for question_id in ids_to_add:
            order += 1
            row = existing_by_question.get(question_id)
            if row:
                row.is_deleted = False
                row.display_order = order
            else:
                new_entities.append(
                    SessionQuestion(
                        session_id=session_id,
                        question_id=question_id,
                        display_order=order,
                    )
                )

        if new_entities:
            self.session_repo.db.add_all(new_entities)
        await self.session_repo.db.commit()
        return await self._build_ordered_questions(session_id)

    async def set_questions(self, session_id: UUID, payload: SessionQuestionSetRequest) -> list[SessionQuestionResponse]:
        session = await self.session_repo.get_session(session_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        unique_question_ids = list(dict.fromkeys(payload.question_ids))
        available_questions = await self.session_repo.get_questions_by_ids(unique_question_ids)
        available_question_ids = {q.id for q in available_questions}
        missing_question_ids = [str(qid) for qid in unique_question_ids if qid not in available_question_ids]
        if missing_question_ids:
            raise BusinessException(
                message="Some questions do not exist",
                status_code=400,
                errors={"missing_question_ids": missing_question_ids},
            )

        await self.session_repo.set_session_questions(session_id, unique_question_ids)
        return await self._build_ordered_questions(session_id)

    async def remove_questions(self, session_id: UUID, payload: SessionQuestionRemoveRequest) -> list[SessionQuestionResponse]:
        session = await self.session_repo.get_session(session_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        existing_ids = await self.session_repo.get_existing_session_question_ids(session_id)
        ids_to_remove = [qid for qid in payload.question_ids if qid in existing_ids]
        if not ids_to_remove:
            return await self._build_ordered_questions(session_id)

        await self.session_repo.remove_session_questions(session_id, ids_to_remove)
        return await self._build_ordered_questions(session_id)

    async def update_question_order(
        self,
        session_id: UUID,
        payload: SessionQuestionOrderUpdateRequest,
    ) -> list[SessionQuestionResponse]:
        session = await self.session_repo.get_session(session_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        existing = await self.session_repo.list_session_questions(session_id)
        existing_ids = {row.question_id for row in existing}
        incoming_ids = {item.question_id for item in payload.items}
        incoming_orders = sorted(item.display_order for item in payload.items)

        if existing_ids != incoming_ids:
            raise BusinessException(
                message="Order payload must include exactly all session questions",
                status_code=400,
                errors={
                    "expected_question_ids": [str(qid) for qid in existing_ids],
                    "provided_question_ids": [str(qid) for qid in incoming_ids],
                },
            )
        expected_orders = list(range(1, len(payload.items) + 1))
        if incoming_orders != expected_orders:
            raise BusinessException(
                message="display_order must be a contiguous sequence starting at 1",
                status_code=400,
                errors={"expected_orders": expected_orders},
            )

        order_map = {item.question_id: item.display_order for item in payload.items}
        await self.session_repo.set_question_orders(session_id, order_map)
        return await self._build_ordered_questions(session_id)

    async def update_session_status(self, session_id: UUID, is_active: bool, company_id=None) -> SessionSummaryResponse:
        session = await self.session_repo.get_session(session_id, company_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        updated = await self.session_repo.update_session_status(session, is_active)
        return self._to_summary(updated)

    async def update_session_details(self, session_id: UUID, payload: SessionUpdateRequest, company_id=None) -> SessionSummaryResponse:
        session = await self.session_repo.get_session(session_id, company_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        title = payload.title.strip() if payload.title is not None else None
        updated = await self.session_repo.update_session_details(
            session,
            title=title,
            description=payload.description,
            company_id=payload.company_id,
        )
        return self._to_summary(updated)

    async def delete_session(self, session_id: UUID, company_id=None) -> SessionSummaryResponse:
        session = await self.session_repo.get_session(session_id, company_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        updated = await self.session_repo.soft_delete_session(session)
        return self._to_summary(updated)

    async def get_session_details(self, session_id: UUID) -> SessionDetailsResponse:
        session = await self.session_repo.get_session(session_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        rows = await self.session_repo.get_session_detail_rows(session_id)
        themes: dict = {}

        for row in rows:
            theme_key = row.theme_key
            kpi_key = row.kpi_key

            if theme_key not in themes:
                themes[theme_key] = {
                    "theme_key": theme_key,
                    "theme_display_name": row.theme_display_name,
                    "kpis": {},
                }

            if kpi_key not in themes[theme_key]["kpis"]:
                themes[theme_key]["kpis"][kpi_key] = {
                    "kpi_key": kpi_key,
                    "display_name": row.display_name,
                    "questions": [],
                }

            themes[theme_key]["kpis"][kpi_key]["questions"].append(
                SessionQuestionResponse(
                    question_id=row.id,
                    question_code=row.question_code,
                    question_text=row.question_text,
                    reverse_code=bool(row.reverse_code),
                    display_order=row.display_order,
                )
            )

        theme_response = []
        for theme_data in themes.values():
            kpi_response = [
                SessionKPIResponse(
                    kpi_key=kpi_data["kpi_key"],
                    display_name=kpi_data["display_name"],
                    questions=kpi_data["questions"],
                )
                for kpi_data in theme_data["kpis"].values()
            ]
            theme_response.append(
                SessionThemeResponse(
                    theme_key=theme_data["theme_key"],
                    theme_display_name=theme_data["theme_display_name"],
                    kpis=kpi_response,
                )
            )

        return SessionDetailsResponse(
            id=session.id,
            company_id=session.company_id,
            title=session.title,
            description=session.description,
            is_active=session.is_active,
            is_published=session.is_published,
            published_at=session.published_at,
            google_form_id=session.google_form_id,
            google_form_responder_url=session.google_form_responder_url,
            created_at=session.created_at,
            updated_at=session.updated_at,
            themes=theme_response,
        )

    async def generate_google_form(
        self,
        session_id: UUID,
        force_regenerate: bool,
    ) -> SessionGoogleFormResponse:
        session = await self.session_repo.get_session(session_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        if session.google_form_id and session.google_form_responder_url and not force_regenerate:
            return SessionGoogleFormResponse(
                session_id=session.id,
                form_id=session.google_form_id,
                responder_url=session.google_form_responder_url,
                script_id=None,
            )

        session_questions = await self.session_repo.list_session_questions(session_id)
        if not session_questions:
            raise BusinessException(
                message="Cannot generate form for a session without questions",
                status_code=400,
            )

        question_ids = [sq.question_id for sq in session_questions]
        questions = await self.session_repo.get_questions_by_ids(question_ids)
        question_by_id = {q.id: q for q in questions}

        missing = [str(qid) for qid in question_ids if qid not in question_by_id]
        if missing:
            raise BusinessException(
                message="Session has missing questions",
                status_code=400,
                errors={"missing_question_ids": missing},
            )

        question_payload = []
        for sq in session_questions:
            question = question_by_id[sq.question_id]
            options = await self.session_repo.get_question_options(question.id)
            question_payload.append(
                {
                    "question_text": question.question_text,
                    "options": options,
                }
            )

        generated = self.form_generator.create_form(
            session_title=session.title,
            session_description=session.description,
            question_payload=question_payload,
        )
        script_id = self.form_generator.provision_form_webhook_script(
            form_id=generated["form_id"],
            company_id=self._resolve_company_id(session),
        )

        updated = await self.session_repo.update_google_form_links(
            session=session,
            form_id=generated["form_id"],
            responder_url=generated["responder_url"],
        )

        return SessionGoogleFormResponse(
            session_id=updated.id,
            form_id=updated.google_form_id,
            responder_url=updated.google_form_responder_url,
            script_id=script_id,
        )

    async def get_form_config(self, session_id: UUID, include_unpublished: bool) -> SessionFormConfigResponse:
        session = await self.session_repo.get_session(session_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        if not include_unpublished and not session.is_published:
            raise BusinessException(message="Session is not published", status_code=403)

        rows = await self.session_repo.get_session_detail_rows(session_id)
        if not rows:
            raise BusinessException(
                message="Session has no questions",
                status_code=400,
            )

        questions: list[SessionFormQuestionResponse] = []
        for row in rows:
            options = await self.session_repo.get_question_options(row.id)
            questions.append(
                SessionFormQuestionResponse(
                    question_id=row.id,
                    question_code=row.question_code,
                    question_text=row.question_text,
                    reverse_code=bool(row.reverse_code),
                    display_order=row.display_order,
                    theme_key=row.theme_key,
                    theme_display_name=row.theme_display_name,
                    kpi_key=row.kpi_key,
                    kpi_display_name=row.display_name,
                    options=options,
                )
            )

        preview_url = self._build_frontend_url(
            settings.SESSION_FORM_PREVIEW_PATH.format(session_id=session.id)
        )
        final_url = None
        if session.is_published:
            final_url = self._build_frontend_url(
                settings.SESSION_FORM_PATH.format(session_id=session.id)
            )

        return SessionFormConfigResponse(
            session_id=session.id,
            company_id=session.company_id,
            title=session.title,
            description=session.description,
            is_published=bool(session.is_published),
            published_at=session.published_at,
            preview_url=preview_url,
            final_url=final_url,
            questions=questions,
        )

    async def publish_form(self, session_id: UUID) -> SessionFormConfigResponse:
        session = await self.session_repo.get_session(session_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        session_questions = await self.session_repo.list_session_questions(session_id)
        if not session_questions:
            raise BusinessException(
                message="Cannot publish a session without questions",
                status_code=400,
            )

        updated = await self.session_repo.update_session_publish(session, True)
        result = await self.get_form_config(updated.id, include_unpublished=True)

        await self._send_publish_emails(updated, result.final_url)
        return result

    async def submit_form(
        self,
        session_id: UUID,
        payload: SessionFormSubmissionRequest,
    ) -> SessionFormSubmissionResponse:
        session = await self.session_repo.get_session(session_id)
        if not session:
            raise BusinessException(message="Session not found", status_code=404)

        if not session.is_published:
            raise BusinessException(message="Session is not published", status_code=403)

        session_questions = await self.session_repo.list_session_questions(session_id)
        if not session_questions:
            raise BusinessException(
                message="Session has no questions",
                status_code=400,
            )

        allowed_question_ids = {row.question_id for row in session_questions}
        requested_ids = {answer.question_id for answer in payload.answers}
        invalid = [str(qid) for qid in requested_ids if qid not in allowed_question_ids]
        if invalid:
            raise BusinessException(
                message="Submission contains questions that do not belong to this session",
                status_code=400,
                errors={"invalid_question_ids": invalid},
            )

        questions = await self.session_repo.get_questions_by_ids(list(allowed_question_ids))
        question_by_id = {q.id: q for q in questions}

        response_id = str(uuid4())
        form_data = {
            "email": payload.email,
            "response_id": response_id,
        }

        for answer in payload.answers:
            question = question_by_id.get(answer.question_id)
            if not question:
                continue
            form_data[question.question_text] = answer.selected_option

        form_payload = {
            "company_id": self._resolve_company_id(session),
            "form_id": str(session.id),
            "form_data": form_data,
        }

        svc = EmployeeFormService(
            EmployeeFormRepository(self.session_repo.db),
            KPIQuestionRepository(self.session_repo.db),
            KPIScoringRepository(self.session_repo.db),
        )
        await svc.process_submission(form_payload)

        return SessionFormSubmissionResponse(response_id=response_id)

    async def get_user_submitted_sessions(self, email: str) -> list[dict]:
        svc = EmployeeFormService(
            EmployeeFormRepository(self.session_repo.db),
            KPIQuestionRepository(self.session_repo.db),
            KPIScoringRepository(self.session_repo.db),
        )
        form_scores = await svc.get_scores(email)
        kpi_weights_map = await self._get_kpi_weights_map(form_scores)

        output: list[dict] = []
        for form_entry in form_scores:
            form_id = form_entry.get("form_id")
            try:
                session_id = UUIDType(str(form_id))
            except Exception:
                continue

            session = await self.session_repo.get_session(session_id)
            if not session:
                continue

            responses = []
            for response in form_entry.get("responses", []):
                kpi_scores = response.get("kpi_scores", [])
                responses.append(
                    {
                        "response_id": response.get("response_id"),
                        "employee_email": response.get("employee_email"),
                        "submitted_at": response.get("submitted_at"),
                        "total_score": response.get("total_score"),
                        "weighted_index": self.calculate_weighted_index(kpi_scores, kpi_weights_map),
                        "questions": response.get("questions", []),
                        "kpi_scores": kpi_scores,
                    }
                )

            if responses:
                output.append(
                    {
                        "session_id": session.id,
                        "company_id": session.company_id,
                        "title": session.title,
                        "description": session.description,
                        "responses": responses,
                    }
                )

        return output

    def calculate_weighted_index(self, kpi_scores, kpi_weights_map: dict) -> float:
        weighted_sum = 0.0
        total_weight = 0.0

        for kpi_score in kpi_scores or []:
            kpi_key = kpi_score.get("kpi_key")
            if kpi_key is None:
                continue

            weight = float(kpi_weights_map.get(str(kpi_key), 0.0) or 0.0)
            average_score = float(kpi_score.get("average_score", 0.0) or 0.0)

            weighted_sum += weight * average_score
            total_weight += weight

        if total_weight == 0:
            return 0.0

        return round(weighted_sum / total_weight, 2)

    async def _get_kpi_weights_map(self, form_scores: list[dict]) -> dict[str, float]:
        kpi_keys: set = set()
        for form_entry in form_scores:
            for response in form_entry.get("responses", []):
                for kpi_score in response.get("kpi_scores", []) or []:
                    kpi_key = kpi_score.get("kpi_key")
                    if kpi_key is not None:
                        kpi_keys.add(kpi_key)

        if not kpi_keys:
            return {}

        stmt = select(KPI.kpi_key, KPI.wi_weight).where(KPI.kpi_key.in_(list(kpi_keys)))
        result = await self.session_repo.db.execute(stmt)
        return {
            str(kpi_key): float(wi_weight or 0.0)
            for kpi_key, wi_weight in result.all()
        }

    async def list_published_links_for_user(
        self,
        *,
        email: str,
        skip: int,
        limit: int,
    ) -> SessionPublishedLinkListResponse:
        user_repo = CompanyUserRepository(self.session_repo.db)
        company_user = await user_repo.get_by_email(email)
        if not company_user or not company_user.company_id:
            raise BusinessException(message="Company user not found", status_code=404)

        sessions, total = await self.session_repo.list_published_sessions_by_company_excluding_user(
            company_id=company_user.company_id,
            user_email=email,
            skip=skip,
            limit=limit,
        )

        items = []
        for session in sessions:
            form_url = self._build_frontend_url(
                settings.SESSION_FORM_PATH.format(session_id=session.id)
            )
            items.append(
                SessionPublishedLinkResponse(
                    session_id=session.id,
                    title=session.title,
                    description=session.description,
                    published_at=session.published_at,
                    form_url=form_url,
                )
            )

        return SessionPublishedLinkListResponse(
            items=items,
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get_suggestions_for_user(
        self,
        *,
        session_id: UUID,
        email: str,
    ) -> SessionSuggestionListResponse:
        form_repo = EmployeeFormRepository(self.session_repo.db)
        latest = await form_repo.get_latest_response(email=email, form_id=str(session_id))
        if not latest:
            raise BusinessException(message="No submission found for this session", status_code=404)

        rows = await form_repo.get_answers_with_kpi(latest.response_id)
        if not rows:
            return SessionSuggestionListResponse(
                session_id=session_id,
                response_id=latest.response_id,
                submitted_at=latest.submitted_at,
                items=[],
            )

        # Build KPI averages and question scores
        kpi_stats: dict = {}
        question_scores: dict = {}
        for row in rows:
            kpi_key = row.kpi_key
            kpi_display_name = row.kpi_display_name
            score = float(row.score or 0)

            if kpi_key not in kpi_stats:
                kpi_stats[kpi_key] = {
                    "kpi_key": kpi_key,
                    "kpi_display_name": kpi_display_name,
                    "total": 0.0,
                    "count": 0,
                    "average": 0.0,
                }
            kpi_stats[kpi_key]["total"] += score
            kpi_stats[kpi_key]["count"] += 1
            kpi_stats[kpi_key]["average"] = (
                kpi_stats[kpi_key]["total"] / kpi_stats[kpi_key]["count"]
            )

            question_scores[row.question_key] = {
                "question_key": row.question_key,
                "question_text": row.question_text,
                "kpi_key": kpi_key,
                "kpi_display_name": kpi_display_name,
                "score": score,
            }

        def classify(avg: float) -> str:
            if avg >= 4.0:
                return "good"
            if avg >= 3.0:
                return "moderate"
            return "risk"

        kpi_levels = {
            kpi_key: classify(stats["average"])
            for kpi_key, stats in kpi_stats.items()
        }

        # Fetch mappings for KPI risk (moderate/risk)
        kpi_keys = [k for k, v in kpi_levels.items() if v in {"moderate", "risk"}]
        kpi_level_set = {v for v in kpi_levels.values() if v in {"moderate", "risk"}}

        kpi_mappings = []
        if kpi_keys:
            stmt = (
                select(KPISuggestionMapping, Suggestion)
                .join(Suggestion, Suggestion.id == KPISuggestionMapping.suggestion_id)
                .where(
                    KPISuggestionMapping.is_deleted == False,
                    KPISuggestionMapping.is_active == True,
                    Suggestion.is_deleted == False,
                    Suggestion.is_active == True,
                    KPISuggestionMapping.kpi_key.in_(kpi_keys),
                    func.lower(KPISuggestionMapping.trigger_mode).in_(["kpi_risk", "both"]),
                    func.lower(KPISuggestionMapping.risk_level).in_(
                        [lvl.lower() for lvl in kpi_level_set]
                    ),
                )
            )
            res = await self.session_repo.db.execute(stmt)
            kpi_mappings = res.all()

        # Fetch mappings for question scores
        question_keys = list(question_scores.keys())
        question_mappings = []
        if question_keys:
            stmt = (
                select(KPISuggestionMapping, Suggestion)
                .join(Suggestion, Suggestion.id == KPISuggestionMapping.suggestion_id)
                .where(
                    KPISuggestionMapping.is_deleted == False,
                    KPISuggestionMapping.is_active == True,
                    Suggestion.is_deleted == False,
                    Suggestion.is_active == True,
                    KPISuggestionMapping.question_key.in_(question_keys),
                    func.lower(KPISuggestionMapping.trigger_mode).in_(["question_score", "both"]),
                )
            )
            res = await self.session_repo.db.execute(stmt)
            question_mappings = res.all()

        # Build suggestion items with triggers
        suggestion_map: dict = {}

        for mapping, suggestion in kpi_mappings:
            level = kpi_levels.get(mapping.kpi_key)
            if not level or level == "good":
                continue
            trigger = SessionSuggestionTrigger(
                trigger_mode=mapping.trigger_mode,
                risk_level=level,
                kpi_key=mapping.kpi_key,
                kpi_display_name=kpi_stats[mapping.kpi_key]["kpi_display_name"],
                kpi_average_score=kpi_stats[mapping.kpi_key]["average"],
                priority=mapping.priority,
            )
            item = suggestion_map.setdefault(
                suggestion.id,
                SessionSuggestionItem(
                    suggestion_id=suggestion.id,
                    suggestion_type=suggestion.suggestion_type,
                    title=suggestion.title,
                    description=suggestion.description,
                    url=suggestion.url,
                    dosha_type=suggestion.dosha_type,
                    difficulty=suggestion.difficulty,
                    duration_mins=suggestion.duration_mins,
                    triggers=[],
                ),
            )
            item.triggers.append(trigger)

        for mapping, suggestion in question_mappings:
            qs = question_scores.get(mapping.question_key)
            if not qs:
                continue
            score = qs["score"]
            below = mapping.score_threshold_below
            above = mapping.score_threshold_above
            match = False
            if below is not None and score < below:
                match = True
            if above is not None and score > above:
                match = True
            if not match:
                continue

            trigger = SessionSuggestionTrigger(
                trigger_mode=mapping.trigger_mode,
                question_key=qs["question_key"],
                question_text=qs["question_text"],
                question_score=score,
                kpi_key=qs["kpi_key"],
                kpi_display_name=qs["kpi_display_name"],
                score_threshold_below=below,
                score_threshold_above=above,
                priority=mapping.priority,
            )
            item = suggestion_map.setdefault(
                suggestion.id,
                SessionSuggestionItem(
                    suggestion_id=suggestion.id,
                    suggestion_type=suggestion.suggestion_type,
                    title=suggestion.title,
                    description=suggestion.description,
                    url=suggestion.url,
                    dosha_type=suggestion.dosha_type,
                    difficulty=suggestion.difficulty,
                    duration_mins=suggestion.duration_mins,
                    triggers=[],
                ),
            )
            item.triggers.append(trigger)

        items = list(suggestion_map.values())
        items.sort(key=lambda x: min((t.priority for t in x.triggers), default=1))

        return SessionSuggestionListResponse(
            session_id=session_id,
            response_id=latest.response_id,
            submitted_at=latest.submitted_at,
            items=items,
        )

    async def _build_ordered_questions(self, session_id: UUID) -> list[SessionQuestionResponse]:
        links = await self.session_repo.list_session_questions(session_id)
        question_ids = [row.question_id for row in links]
        questions = await self.session_repo.get_questions_by_ids(question_ids)
        question_by_id = {q.id: q for q in questions}

        output: list[SessionQuestionResponse] = []
        for link in links:
            question = question_by_id.get(link.question_id)
            if question is None:
                continue
            output.append(
                SessionQuestionResponse(
                    question_id=question.id,
                    question_code=question.question_code,
                    question_text=question.question_text,
                    reverse_code=bool(question.reverse_code),
                    display_order=link.display_order,
                )
            )
        return output

    def _to_summary(self, session: Session) -> SessionSummaryResponse:
        return SessionSummaryResponse(
            id=session.id,
            company_id=session.company_id,
            title=session.title,
            description=session.description,
            is_active=session.is_active,
            is_published=session.is_published,
            published_at=session.published_at,
            google_form_id=session.google_form_id,
            google_form_responder_url=session.google_form_responder_url,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )

    def _resolve_company_id(self, session: Session) -> str:
        if session.company_id:
            return str(session.company_id)
        return "ALL"

    async def _send_publish_emails(self, session: Session, final_url: str | None) -> None:
        if not settings.EMAIL_SEND_ON_PUBLISH:
            return
        if not session.company_id:
            self.logger.info("EMAIL_SKIP | publish_session | session_id=%s | reason=no_company", session.id)
            return
        if not final_url:
            self.logger.info("EMAIL_SKIP | publish_session | session_id=%s | reason=no_final_url", session.id)
            return

        user_repo = CompanyUserRepository(self.session_repo.db)
        users = await user_repo.list_by_company(session.company_id)
        emails = [u.email for u in users if u.email]
        if not emails:
            self.logger.info("EMAIL_SKIP | publish_session | session_id=%s | reason=no_recipients", session.id)
            return

        subject = settings.EMAIL_PUBLISH_SUBJECT_TEMPLATE.format(session_title=session.title)
        base = (settings.FRONTEND_BASE_URL or "").rstrip("/")
        if final_url and final_url.startswith("http"):
            full_url = final_url
        elif final_url:
            full_url = f"{final_url.lstrip('/')}" if base else final_url
        else:
            full_url = ""
        body = settings.EMAIL_PUBLISH_BODY_TEMPLATE.format(
            session_title=session.title,
            form_url=full_url,
            frontend_base_url=base,
        )
        batch_size = max(1, settings.EMAIL_SEND_BATCH_SIZE)

        client = EmailClient()
        for i in range(0, len(emails), batch_size):
            batch = emails[i : i + batch_size]
            try:
                await client.send_email(to=batch, subject=subject, body=body, html=False)
            except BusinessException as exc:
                self.logger.warning(
                    "EMAIL_FAILED | publish_session | session_id=%s | error=%s",
                    session.id,
                    exc.message,
                )

    def _build_frontend_url(self, path: str) -> str:
        base = (settings.FRONTEND_BASE_URL or "").strip()
        if not base:
            return path
        return f"{base.rstrip('/')}/{path.lstrip('/')}"
