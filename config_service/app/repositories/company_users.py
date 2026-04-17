from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.company_users import CompanyUser


class UserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, user: CompanyUser) -> CompanyUser:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def get_by_email(self, email: str) -> Optional[CompanyUser]:
        q = select(CompanyUser).where(
            CompanyUser.email == email,
            CompanyUser.is_deleted == False,
        )
        res = await self.db.execute(q)
        return res.scalars().first()

    async def get_by_email_and_company(self, company_id, email: str) -> Optional[CompanyUser]:
        q = select(CompanyUser).where(
            CompanyUser.company_id == company_id,
            CompanyUser.email == email,
            CompanyUser.is_deleted == False,
        )
        res = await self.db.execute(q)
        return res.scalars().first()

    async def get_by_emp_id_and_company(self, company_id, emp_id: str) -> Optional[CompanyUser]:
        q = select(CompanyUser).where(
            CompanyUser.company_id == company_id,
            CompanyUser.emp_id == emp_id,
            CompanyUser.is_deleted == False,
        )
        res = await self.db.execute(q)
        return res.scalars().first()

    async def get_by_id(self, user_id) -> Optional[CompanyUser]:
        q = select(CompanyUser).where(
            CompanyUser.id == user_id,
            CompanyUser.is_deleted == False,
        )
        res = await self.db.execute(q)
        return res.scalars().first()

    async def update(self, user: CompanyUser) -> CompanyUser:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        company_id=None,
        search: str | None = None,
        is_active: bool | None = True,
    ):
        q = select(CompanyUser).where(CompanyUser.is_deleted == False)
        if is_active is not None:
            q = q.where(CompanyUser.is_active == is_active)
        if company_id:
            q = q.where(CompanyUser.company_id == company_id)
        if search:
            like = f"%{search.lower()}%"
            q = q.where(
                func.lower(CompanyUser.full_name).like(like)
                | func.lower(CompanyUser.email).like(like)
                | func.lower(CompanyUser.emp_id).like(like)
            )

        count_stmt = select(func.count()).select_from(q.subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        q = q.order_by(CompanyUser.created_at.desc()).offset(skip).limit(limit)
        res = await self.db.execute(q)
        return list(res.scalars().all()), total

    async def list_by_company(self, company_id):
        q = select(CompanyUser).where(
            CompanyUser.company_id == company_id,
            CompanyUser.is_deleted == False,
            CompanyUser.is_active == True,
        )
        res = await self.db.execute(q)
        return list(res.scalars().all())

    async def list_by_company_ids(self, company_ids: list):
        if not company_ids:
            return []
        q = select(CompanyUser).where(
            CompanyUser.company_id.in_(company_ids),
            CompanyUser.is_deleted == False,
        )
        res = await self.db.execute(q)
        return list(res.scalars().all())
