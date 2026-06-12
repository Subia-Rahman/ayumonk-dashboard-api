import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.employee_form_answer import EmployeeFormAnswer
from config_service.app.models.employee_form_response import EmployeeFormResponse
from datetime import datetime


_logger = logging.getLogger(__name__)


class EmployeeFormService:
    def __init__(
        self,
        form_repo,
        question_repo,
        scoring_repo
    ):
        self.form_repo = form_repo
        self.question_repo = question_repo
        self.scoring_repo = scoring_repo

    async def process_submission(self, payload):

        company_id = payload["company_id"]
        form_id = payload["form_id"] 
        data = payload["form_data"] 

        # System fields
        response_id = data.get("response_id")
        email = data.get("email")
        if not response_id:
            raise ValueError("response_id is required in form_data")
        if not email:
            raise ValueError("email is required in form_data")

        if await self.form_repo.response_exists(response_id):
            return response_id

        submitted_at = datetime.utcnow()

        # Deactivate previous response of form
        await self.form_repo.deactivate_previous_responses(
            email=email,
            form_id=form_id
        )

        # Save response 
        await self.form_repo.create_response(
            EmployeeFormResponse(
                company_id=company_id,
                employee_email=email,
                response_id=response_id,
                submitted_at=submitted_at,
                raw_payload=payload,
                form_id=form_id
            )
        )

        SYSTEM_FIELDS = {"email", "response_id", "submitted_at"}

        # process dynamic questions
        for question_text, selected_option in data.items():

            if question_text in SYSTEM_FIELDS:
                continue

            question = await self.question_repo.get_by_question(question_text)
            if not question:
                continue   

            question_code = question.question_code
            question_id = question.id
            # Fetch score
            scoring = await self.scoring_repo.get_by_question_id_and_option(
                question_id, selected_option
            )

            raw_score = scoring.score if scoring else 0

            # Spec §8: reverse-scored questions write `6 - raw` so
            # downstream aggregates are correctly signed without every
            # consumer re-applying the rule.
            if getattr(question, "reverse_code", False):
                score = 6 - raw_score if raw_score is not None else 0
            else:
                score = raw_score

            # Save answer
            await self.form_repo.create_answer(
                EmployeeFormAnswer(
                    response_id=response_id,
                    question_code=question_code,
                    selected_option=selected_option,
                    score=score
                )
            )

        # Persist the headline Wellness Index for this submission. Failures
        # here must not roll back the form-answer writes — log and continue.
        try:
            from config_service.app.services.wellness_scoring import (
                WellnessScoringService,
            )
            await WellnessScoringService(self.form_repo.db).persist_for_response(
                response_id=response_id,
                employee_email=email,
                company_id=company_id,
            )
        except Exception:
            _logger.exception(
                "WELLNESS_INDEX_PERSIST_FAILED | response_id=%s | email=%s",
                response_id,
                email,
            )

        # Run the two-tier suggestion engine and persist its picks (up to
        # 2 Aahar + 2 Vihar + 2 Aushadh per spec §9). Same fire-and-log
        # contract as the WI persist — submission must succeed even when
        # the engine has a transient hiccup.
        try:
            from config_service.app.services.suggestion_engine import (
                SuggestionEngineService,
            )
            await SuggestionEngineService(self.form_repo.db).compute_and_persist(
                response_id=response_id,
                employee_email=email,
                company_id=company_id,
            )
        except Exception:
            _logger.exception(
                "SUGGESTION_ENGINE_FAILED | response_id=%s | email=%s",
                response_id,
                email,
            )

        return response_id

    async def get_scores(self, email=None):
        rows = await self.form_repo.get_scores(email)

        forms = {}

        for row in rows:
            form_id = row.form_id
            employee = row.employee_email

            if form_id not in forms:
                forms[form_id] = {}

            if employee not in forms[form_id]:
                forms[form_id][employee] = {
                    "form_id": form_id,
                    "response_id": row.response_id,
                    "employee_email": employee,
                    "submitted_at": row.submitted_at,
                    "total_score": 0,
                    "questions": []
                }

            forms[form_id][employee]["questions"].append({
                "question_code": row.question_code,
                "question_text": row.question_text,
                "selected_option": row.selected_option,
                "score": row.score
            })

            forms[form_id][employee]["total_score"] += row.score

            # KPI aggregation
            kpi_key = row.kpi
            kpi_name = row.display_name
            kpi_scores = forms[form_id][employee].setdefault("kpi_scores", {})
            if kpi_key not in kpi_scores:
                kpi_scores[kpi_key] = {
                    "kpi_key": kpi_key,
                    "kpi_name": kpi_name,
                    "total_score": 0,
                    "question_count": 0,
                    "average_score": 0.0,
                }
            kpi_scores[kpi_key]["total_score"] += row.score
            kpi_scores[kpi_key]["question_count"] += 1
            kpi_scores[kpi_key]["average_score"] = (
                kpi_scores[kpi_key]["total_score"] / kpi_scores[kpi_key]["question_count"]
            )

        # flatten structure
        output = []
        for form_id in forms:
            responses = list(forms[form_id].values())
            for response in responses:
                if isinstance(response.get("kpi_scores"), dict):
                    response["kpi_scores"] = list(response["kpi_scores"].values())
            output.append({
                "form_id": form_id,
                "responses": responses
            })

        return output


