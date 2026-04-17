from sqlalchemy import or_, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.models.kpi_questions import KPIQuestion
from config_service.app.models.kpi_scoring import KPIScoring
from config_service.app.models.kpi import KPI
from config_service.app.models.theme import Theme

class KPIQuestionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_code(self, code: str) -> KPIQuestion | None:
        stmt = select(KPIQuestion).where(KPIQuestion.question_code == code)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_question(self, question_text: str) -> KPIQuestion | None:
        stmt = select(KPIQuestion).where(KPIQuestion.question_text == question_text)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, obj: KPIQuestion) -> KPIQuestion:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def save(self, obj: KPIQuestion) -> KPIQuestion:
        """Save or update a KPIQuestion object"""
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, question_id):
        stmt = select(KPIQuestion).where(
            KPIQuestion.id == question_id,
            KPIQuestion.is_deleted == False,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_hierarchy_rows(self):
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
            .order_by(
                Theme.theme_display_name.asc(),
                KPI.display_name.asc(),
                KPIQuestion.question_text.asc(),
                KPIScoring.option_number.asc(),
            )
        )
        res = await self.db.execute(stmt)
        return res.all()

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        kpi_key=None,
        theme_key=None,
        search: str | None = None,
        is_active: bool | None = True,
    ):
        stmt = select(KPIQuestion).where(KPIQuestion.is_deleted == False)
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
