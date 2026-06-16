from __future__ import annotations
from typing import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.kpi import KPI
from config_service.app.models.kpi_questions import KPIQuestion
from config_service.app.models.kpi_scoring import KPIScoring
from config_service.app.models.employee_form_response import EmployeeFormResponse
from config_service.app.models.session import Session
from config_service.app.models.session_question import SessionQuestion
from config_service.app.models.theme import Theme


class SessionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(self, session: Session) -> Session:
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def list_sessions(self, skip: int = 0, limit: int = 100, company_id=None) -> list[Session]:
        stmt = select(Session).where(Session.is_deleted == False)
        if company_id is not None:
            stmt = stmt.where(Session.company_id == company_id)
        stmt = stmt.order_by(Session.created_at.desc()).offset(skip).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def list_published_sessions_by_company(
        self,
        *,
        company_id: UUID,
        skip: int,
        limit: int,
    ) -> tuple[list[Session], int]:
        stmt = select(Session).where(
            Session.is_deleted == False,
            Session.is_published == True,
            Session.is_active == True,
            Session.company_id == company_id,
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Session.published_at.desc()).offset(skip).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total

    async def list_published_sessions_by_company_excluding_user(
        self,
        *,
        company_id: UUID,
        user_email: str,
        skip: int,
        limit: int,
    ) -> tuple[list[Session], int]:
        submitted_forms = select(EmployeeFormResponse.form_id).where(
            EmployeeFormResponse.employee_email == user_email,
            EmployeeFormResponse.is_latest == True,
        )

        stmt = select(Session).where(
            Session.is_deleted == False,
            Session.is_published == True,
            Session.is_active == True,
            Session.company_id == company_id,
            cast(Session.id, String).notin_(submitted_forms),
        )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(Session.published_at.desc()).offset(skip).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total

    async def get_session(self, session_id: UUID, company_id=None) -> Session | None:
        stmt = select(Session).where(
            Session.id == session_id,
            Session.is_deleted == False,
        )
        if company_id is not None:
            stmt = stmt.where(Session.company_id == company_id)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_session_questions(self, session_id: UUID) -> list[SessionQuestion]:
        stmt = (
            select(SessionQuestion)
            .where(
                SessionQuestion.session_id == session_id,
                SessionQuestion.is_deleted == False,
            )
            .order_by(SessionQuestion.display_order.asc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def list_session_questions_all(self, session_id: UUID) -> list[SessionQuestion]:
        stmt = select(SessionQuestion).where(SessionQuestion.session_id == session_id)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_existing_session_question_ids(self, session_id: UUID) -> set[UUID]:
        stmt = select(SessionQuestion.question_id).where(
            SessionQuestion.session_id == session_id,
            SessionQuestion.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return set(res.scalars().all())

    async def get_max_display_order(self, session_id: UUID) -> int:
        stmt = select(func.max(SessionQuestion.display_order)).where(
            SessionQuestion.session_id == session_id,
            SessionQuestion.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        max_order = res.scalar_one_or_none()
        return int(max_order or 0)

    async def bulk_add_session_questions(
        self,
        session_id: UUID,
        question_ids: Sequence[UUID],
        start_from: int,
    ) -> list[SessionQuestion]:
        entities: list[SessionQuestion] = []
        order = start_from

        for question_id in question_ids:
            order += 1
            entities.append(
                SessionQuestion(
                    session_id=session_id,
                    question_id=question_id,
                    display_order=order,
                )
            )

        self.db.add_all(entities)
        await self.db.commit()
        return entities

    async def set_question_orders(self, session_id: UUID, order_map: dict[UUID, int]) -> None:
        stmt = select(SessionQuestion).where(
            SessionQuestion.session_id == session_id,
            SessionQuestion.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        questions = res.scalars().all()

        # Avoid unique (session_id, display_order) conflicts during swaps.
        temp_offset = 100000
        for question in questions:
            question.display_order = question.display_order + temp_offset
        await self.db.flush()

        for question in questions:
            if question.question_id in order_map:
                question.display_order = order_map[question.question_id]

        await self.db.commit()

    async def set_session_questions(
        self,
        session_id: UUID,
        question_ids: Sequence[UUID],
    ) -> None:
        existing_rows = await self.list_session_questions_all(session_id)
        existing_by_question = {row.question_id: row for row in existing_rows}

        # Avoid unique (session_id, display_order) conflicts during swaps.
        temp_offset = 100000
        for row in existing_rows:
            if row.display_order is not None:
                row.display_order = row.display_order + temp_offset
        await self.db.flush()

        desired_set = set(question_ids)
        order = 0
        for question_id in question_ids:
            order += 1
            row = existing_by_question.get(question_id)
            if row:
                row.is_deleted = False
                row.display_order = order
            else:
                self.db.add(
                    SessionQuestion(
                        session_id=session_id,
                        question_id=question_id,
                        display_order=order,
                    )
                )

        for row in existing_rows:
            if row.question_id not in desired_set:
                row.is_deleted = True

        await self.db.commit()

    async def remove_session_questions(self, session_id: UUID, question_ids: Sequence[UUID]) -> None:
        await self.db.execute(
            delete(SessionQuestion).where(
                SessionQuestion.session_id == session_id,
                SessionQuestion.question_id.in_(question_ids),
            )
        )
        await self.db.commit()

    async def update_session_status(self, session: Session, is_active: bool) -> Session:
        session.is_active = is_active
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def update_session_details(
        self,
        session: Session,
        *,
        title: str | None,
        description: str | None,
        company_id: UUID | None,
    ) -> Session:
        if title is not None:
            session.title = title
        if description is not None:
            session.description = description
        if company_id is not None:
            session.company_id = company_id
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def soft_delete_session(self, session: Session) -> Session:
        session.is_deleted = True
        session.is_active = False
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def update_session_publish(self, session: Session, is_published: bool) -> Session:
        session.is_published = is_published
        session.published_at = datetime.utcnow() if is_published else None
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def update_google_form_links(
        self,
        session: Session,
        form_id: str,
        responder_url: str,
    ) -> Session:
        session.google_form_id = form_id
        session.google_form_responder_url = responder_url
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def get_questions_by_ids(self, question_ids: Sequence[UUID]) -> list[KPIQuestion]:
        if not question_ids:
            return []
        stmt = select(KPIQuestion).where(
            KPIQuestion.id.in_(question_ids),
            KPIQuestion.is_deleted == False,
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_session_detail_rows(self, session_id: UUID):
        stmt = (
            select(
                SessionQuestion.display_order,
                Theme.theme_key,
                Theme.theme_display_name,
                KPI.kpi_key,
                KPI.display_name,
                KPIQuestion.id,
                KPIQuestion.question_code,
                KPIQuestion.question_text,
                KPIQuestion.reverse_code,
            )
            .join(KPIQuestion, KPIQuestion.id == SessionQuestion.question_id)
            .join(KPI, KPI.kpi_key == KPIQuestion.kpi)
            .join(Theme, Theme.theme_key == KPIQuestion.theme)
            .where(
                SessionQuestion.session_id == session_id,
                SessionQuestion.is_deleted == False,
                KPIQuestion.is_deleted == False,
                KPI.is_deleted == False,
                Theme.is_deleted == False,
            )
            .order_by(
                SessionQuestion.display_order.asc(),
            )
        )
        res = await self.db.execute(stmt)
        return res.all()

    async def get_question_options(self, question_id: UUID) -> list[str]:
        stmt = (
            select(KPIScoring.option_text)
            .where(
                KPIScoring.question_id == question_id,
                KPIScoring.is_deleted == False,
                KPIScoring.option_text.isnot(None),
            )
            .order_by(KPIScoring.option_number.asc())
        )
        res = await self.db.execute(stmt)
        return [option for option in res.scalars().all() if option]
