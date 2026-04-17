from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from config_service.app.models.company import Company

class CompanyRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, company: Company) -> Company:
        self.db.add(company)
        await self.db.commit()
        await self.db.refresh(company)
        return company

    async def update(self, company: Company) -> Company:
        self.db.add(company)
        await self.db.commit()
        await self.db.refresh(company)
        return company

    async def get_by_id(self, company_id) -> Optional[Company]:
        q = select(Company).where(
            Company.id == company_id,
            Company.is_deleted == False
        )
        res = await self.db.execute(q)
        return res.scalars().first()

    async def get_by_name(self, name: str) -> Optional[Company]:
        q = select(Company).where(
            Company.company_name == name,
            Company.is_deleted == False
        )
        res = await self.db.execute(q)
        return res.scalars().first()

    async def list(self, skip: int = 0, limit: int = 100) -> List[Company]:
        q = (
            select(Company)
            .where(Company.is_deleted == False)
            .offset(skip)
            .limit(limit)
            .order_by(Company.created_at.desc())
        )
        res = await self.db.execute(q)
        return res.scalars().all()
