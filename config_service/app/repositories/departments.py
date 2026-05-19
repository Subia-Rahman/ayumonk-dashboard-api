from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.department import Department


class DepartmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, dept: Department) -> Department:
        self.db.add(dept)
        await self.db.commit()
        await self.db.refresh(dept)
        return dept

    async def get_by_id(self, dept_id: UUID, company_id: UUID | None = None) -> Optional[Department]:
        q = select(Department).where(
            Department.id == dept_id,
            Department.is_deleted == False,
        )
        if company_id is not None:
            q = q.where(Department.company_id == company_id)
        res = await self.db.execute(q)
        return res.scalars().first()

    async def get_by_name(self, name: str, company_id: UUID) -> Optional[Department]:
        q = select(Department).where(
            Department.company_id == company_id,
            func.lower(Department.name) == name.lower(),
            Department.is_deleted == False,
        )
        res = await self.db.execute(q)
        return res.scalars().first()

    async def list_by_company(
        self,
        company_id: UUID,
        *,
        is_active: bool | None = True,
    ) -> list[Department]:
        q = select(Department).where(
            Department.company_id == company_id,
            Department.is_deleted == False,
        )
        if is_active is not None:
            q = q.where(Department.is_active == is_active)
        q = q.order_by(Department.name.asc())
        res = await self.db.execute(q)
        return list(res.scalars().all())

    async def list_by_company_paginated(
        self,
        company_id: UUID,
        *,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
        is_active: bool | None = True,
    ) -> tuple[list[Department], int]:
        filters = [
            Department.company_id == company_id,
            Department.is_deleted == False,
        ]
        if is_active is not None:
            filters.append(Department.is_active == is_active)
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(func.lower(Department.name).like(term))

        total = (
            await self.db.execute(select(func.count(Department.id)).where(*filters))
        ).scalar_one()

        q = (
            select(Department)
            .where(*filters)
            .order_by(Department.name.asc())
            .offset(skip)
            .limit(limit)
        )
        res = await self.db.execute(q)
        return list(res.scalars().all()), int(total or 0)

    async def update(self, dept: Department) -> Department:
        self.db.add(dept)
        await self.db.commit()
        await self.db.refresh(dept)
        return dept
