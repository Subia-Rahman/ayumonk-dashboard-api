from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.models.kpi_scoring import KPIScoring

class KPIScoringRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def delete_by_question(self, question_id):
        stmt = delete(KPIScoring).where(KPIScoring.question_id == question_id)
        await self.db.execute(stmt)
        await self.db.commit()

    async def create(self, obj: KPIScoring) -> KPIScoring:
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def list_by_question(self, question_id):
        stmt = (
            select(KPIScoring)
            .where(
                KPIScoring.question_id == question_id,
                KPIScoring.is_deleted == False,
            )
            .order_by(KPIScoring.option_number.asc())
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_by_question_id_and_option(self, question_id: str, option: str):
        result = await self.db.execute(
            select(KPIScoring)
            .where(
                KPIScoring.question_id == question_id,
                KPIScoring.option_text == option
            )
        )
        return result.scalar_one_or_none()
