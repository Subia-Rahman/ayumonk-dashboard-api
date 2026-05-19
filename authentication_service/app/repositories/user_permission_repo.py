from uuid import UUID

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.models.user_permission import UserPermission


class UserPermissionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, override: UserPermission) -> UserPermission:
        self.db.add(override)
        await self.db.commit()
        await self.db.refresh(override)
        return override

    async def upsert(
        self,
        user_id: int,
        permission_id: int,
        tenant_id: UUID,
        is_granted: bool,
        is_allowed: bool | None = None,
        valid_from=None,
        valid_to=None,
    ) -> UserPermission:
        res = await self.db.execute(
            select(UserPermission).where(
                UserPermission.user_id == user_id,
                UserPermission.permission_id == permission_id,
                UserPermission.tenant_id == tenant_id,
            )
        )
        row = res.scalars().first()
        effective_allowed = is_granted if is_allowed is None else is_allowed
        if row:
            row.is_granted = is_granted
            row.is_allowed = effective_allowed
            row.valid_from = valid_from
            row.valid_to = valid_to
            self.db.add(row)
        else:
            row = UserPermission(
                user_id=user_id,
                permission_id=permission_id,
                tenant_id=tenant_id,
                is_granted=is_granted,
                is_allowed=effective_allowed,
                valid_from=valid_from,
                valid_to=valid_to,
            )
            self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def list_by_user(self, user_id: int, tenant_id: UUID):
        res = await self.db.execute(
            select(UserPermission).where(
                UserPermission.user_id == user_id,
                UserPermission.tenant_id == tenant_id,
            )
        )
        return res.scalars().all()

    async def delete_for_user(self, user_id: int, tenant_id: UUID):
        await self.db.execute(
            delete(UserPermission).where(
                UserPermission.user_id == user_id,
                UserPermission.tenant_id == tenant_id,
            )
        )
        await self.db.commit()
