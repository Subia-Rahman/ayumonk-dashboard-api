from __future__ import annotations
from uuid import UUID

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.role_permission import RolePermission


class RolePermissionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(self, role_id: int, permission_id: int, tenant_id: UUID):
        self.db.add(
            RolePermission(
                role_id=role_id, permission_id=permission_id, tenant_id=tenant_id
            )
        )
        await self.db.commit()

    async def replace(self, role_id: int, permission_ids: list[int], tenant_id: UUID):
        await self.db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.tenant_id == tenant_id,
            )
        )
        for pid in permission_ids:
            self.db.add(
                RolePermission(role_id=role_id, permission_id=pid, tenant_id=tenant_id)
            )
        await self.db.commit()

    async def list_by_role(self, role_id: int, tenant_id: UUID):
        res = await self.db.execute(
            select(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.tenant_id == tenant_id,
            )
        )
        return res.scalars().all()

    async def add_many(
        self,
        role_id: int,
        permission_ids: list[int],
        tenant_id: UUID,
        is_override: bool = False,
        is_granted: bool = True,
    ):
        existing = {
            (rp.role_id, rp.permission_id): rp
            for rp in await self.list_by_role(role_id, tenant_id)
        }
        for pid in permission_ids:
            row = existing.get((role_id, pid))
            if row:
                row.is_override = is_override
                row.is_granted = is_granted
                self.db.add(row)
            else:
                self.db.add(
                    RolePermission(
                        role_id=role_id,
                        permission_id=pid,
                        tenant_id=tenant_id,
                        is_override=is_override,
                        is_granted=is_granted,
                    )
                )
        await self.db.commit()

    async def remove_many(self, role_id: int, permission_ids: list[int], tenant_id: UUID):
        await self.db.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role_id,
                RolePermission.tenant_id == tenant_id,
                RolePermission.permission_id.in_(permission_ids),
            )
        )
        await self.db.commit()

    async def count_by_permission(self, permission_id: int) -> int:
        res = await self.db.execute(
            select(func.count(RolePermission.permission_id)).where(
                RolePermission.permission_id == permission_id
            )
        )
        return int(res.scalar() or 0)
