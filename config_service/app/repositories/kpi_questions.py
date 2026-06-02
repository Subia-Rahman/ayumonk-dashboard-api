from sqlalchemy import or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.models.kpi_questions import KPIQuestion
from config_service.app.models.kpi_scoring import KPIScoring
from config_service.app.models.kpi import KPI
from config_service.app.models.theme import Theme


class KPIQuestionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_code(self, code: str, company_id=None) -> KPIQuestion | None:
        stmt = select(KPIQuestion).where(KPIQuestion.question_code == code)
        if company_id is not None:
            stmt = stmt.where(KPIQuestion.company_id == company_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_question(self, question_text: str, company_id=None) -> KPIQuestion | None:
        stmt = select(KPIQuestion).where(KPIQuestion.question_text == question_text)
        if company_id is not None:
            stmt = stmt.where(KPIQuestion.company_id == company_id)
        # question_text is not unique; tolerate duplicates by taking the first match.
        stmt = stmt.order_by(KPIQuestion.created_at.asc()).limit(1)
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def create(self, obj: KPIQuestion) -> KPIQuestion:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def save(self, obj: KPIQuestion) -> KPIQuestion:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, question_id, company_id=None):
        stmt = select(KPIQuestion).where(
            KPIQuestion.id == question_id,
            KPIQuestion.is_deleted == False,
        )
        if company_id is not None:
            stmt = stmt.where(KPIQuestion.company_id == company_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_ids(self, question_ids: list, company_id=None):
        if not question_ids:
            return []
        stmt = select(KPIQuestion).where(
            KPIQuestion.id.in_(question_ids),
            KPIQuestion.is_deleted == False,
        )
        if company_id is not None:
            stmt = stmt.where(KPIQuestion.company_id == company_id)
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_hierarchy_rows(self, company_id=None):
        stmt = (
            select(
                Theme.theme_key,
                Theme.theme_display_name,
                KPI.kpi_key,
                KPI.display_name,
                KPIQuestion.id,
                KPIQuestion.question_code,
                KPIQuestion.question_text,
                KPIQuestion.reverse_code,
                KPIScoring.option_number,
                KPIScoring.option_text,
                KPIScoring.score,
            )
            .outerjoin(KPI, KPI.theme_key == Theme.theme_key)
            .outerjoin(KPIQuestion, KPIQuestion.kpi == KPI.kpi_key)
            .outerjoin(KPIScoring, KPIScoring.question_id == KPIQuestion.id)
            .where(
                Theme.is_deleted == False,
                or_(KPI.is_deleted == False, KPI.kpi_key.is_(None)),
                or_(KPIQuestion.is_deleted == False, KPIQuestion.id.is_(None)),
                or_(KPIScoring.is_deleted == False, KPIScoring.id.is_(None)),
            )
        )
        if company_id is not None:
            stmt = stmt.where(Theme.company_id == company_id)
        stmt = stmt.order_by(
            Theme.theme_display_name.asc(),
            KPI.display_name.asc(),
            KPIQuestion.question_text.asc(),
            KPIScoring.option_number.asc(),
        )
        res = await self.db.execute(stmt)
        return res.all()

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        company_id=None,
        kpi_key=None,
        theme_key=None,
        search: str | None = None,
        is_active: bool | None = True,
    ):
        stmt = select(KPIQuestion).where(KPIQuestion.is_deleted == False)
        if company_id is not None:
            stmt = stmt.where(KPIQuestion.company_id == company_id)
        if is_active is not None:
            stmt = stmt.where(KPIQuestion.is_active == is_active)
        if kpi_key:
            stmt = stmt.where(KPIQuestion.kpi == kpi_key)
        if theme_key:
            stmt = stmt.where(KPIQuestion.theme == theme_key)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                func.lower(KPIQuestion.question_text).like(like)
                | func.lower(KPIQuestion.question_code).like(like)
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(KPIQuestion.question_text.asc()).offset(skip).limit(limit)
        res = await self.db.execute(stmt)
        return list(res.scalars().all()), total
