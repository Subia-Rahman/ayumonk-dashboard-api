from __future__ import annotations
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.employee_form_answer import EmployeeFormAnswer
from config_service.app.models.employee_form_response import EmployeeFormResponse
from config_service.app.models.kpi_questions import KPIQuestion
from config_service.app.models.kpi import KPI
from config_service.app.models.kpi_scoring import KPIScoring


class EmployeeFormRepository:
    def __init__(self, db):
        self.db = db

    async def create_response(self, obj):
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def create_answer(self, obj):
        self.db.add(obj)
        await self.db.commit()
        return obj

    async def get_scores(self, email=None):

        q = (
            select(
                EmployeeFormResponse.form_id,
                EmployeeFormResponse.response_id,
                EmployeeFormResponse.employee_email,
                EmployeeFormResponse.submitted_at,
                KPIQuestion.question_code,
                KPIQuestion.question_text,
                KPIQuestion.kpi,
                KPI.display_name,
                EmployeeFormAnswer.selected_option,
                EmployeeFormAnswer.score
            )
            .join(EmployeeFormAnswer,
                EmployeeFormResponse.response_id == EmployeeFormAnswer.response_id)
            .join(KPIQuestion,
                KPIQuestion.question_code == EmployeeFormAnswer.question_code)
            .join(KPI, KPI.kpi_key == KPIQuestion.kpi)
            .where(EmployeeFormResponse.is_latest == True)
        )

        if email:
            q = q.where(EmployeeFormResponse.employee_email == email)

        q = q.order_by(
            EmployeeFormResponse.form_id,
            EmployeeFormResponse.employee_email,
            EmployeeFormResponse.submitted_at.desc()
        )

        result = await self.db.execute(q)
        return result.all()


    async def get_by_question_and_option(self, question_id, option_text):
        stmt = select(KPIScoring).where(
            KPIScoring.question_id == question_id,
            KPIScoring.option_text == option_text
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()


    async def deactivate_previous_responses(self, email: str, form_id: str):
        await self.db.execute(
            update(EmployeeFormResponse)
            .where(
                EmployeeFormResponse.employee_email == email,
                EmployeeFormResponse.form_id == form_id,
                EmployeeFormResponse.is_latest == True
            )
            .values(is_latest=False)
        )
        await self.db.commit()

    async def response_exists(self, response_id: str) -> bool:
        stmt = select(EmployeeFormResponse.id).where(
            EmployeeFormResponse.response_id == response_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def get_latest_response(self, email: str, form_id: str) -> EmployeeFormResponse | None:
        stmt = (
            select(EmployeeFormResponse)
            .where(
                EmployeeFormResponse.employee_email == email,
                EmployeeFormResponse.form_id == form_id,
                EmployeeFormResponse.is_latest == True,
            )
            .order_by(EmployeeFormResponse.submitted_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_answers_with_kpi(self, response_id: str):
        stmt = (
            select(
                EmployeeFormAnswer.question_code,
                EmployeeFormAnswer.score,
                KPIQuestion.id.label("question_key"),
                KPIQuestion.question_text,
                KPIQuestion.kpi.label("kpi_key"),
                KPI.display_name.label("kpi_display_name"),
            )
            .join(KPIQuestion, KPIQuestion.question_code == EmployeeFormAnswer.question_code)
            .join(KPI, KPI.kpi_key == KPIQuestion.kpi)
            .where(EmployeeFormAnswer.response_id == response_id)
        )
        result = await self.db.execute(stmt)
        return result.all()
