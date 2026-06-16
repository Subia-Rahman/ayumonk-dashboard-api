from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List
from authentication_service.app.models.user import User


class AuthUserRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # -----------------------------
    # CREATE USER
    # -----------------------------
    async def create(self, user: User) -> User:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # -----------------------------
    # GET BY ID
    # -----------------------------
    async def get_by_id(self, user_id: int) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalars().first()

    # -----------------------------
    # GET BY USERNAME
    # -----------------------------
    async def get_by_username(self, username: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        return result.scalars().first()

    # -----------------------------
    # GET BY EMAIL
    # -----------------------------
    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalars().first()

    # -----------------------------
    # LIST USERS
    # -----------------------------
    async def list(self, skip: int = 0, limit: int = 100) -> List[User]:
        result = await self.db.execute(
            select(User)
            .offset(skip)
            .limit(limit)
            .order_by(User.created_at.desc())
        )
        return result.scalars().all()

    async def list_by_emails_and_role(self, emails: list[str], role: str) -> List[User]:
        if not emails:
            return []
        result = await self.db.execute(
            select(User).where(
                User.email.in_(emails),
                User.role == role,
            )
        )
        return result.scalars().all()

    # -----------------------------
    # UPDATE USER
    # -----------------------------
    async def update(self, user: User) -> User:
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # -----------------------------
    # DELETE USER
    # -----------------------------
    async def delete(self, user: User):
        await self.db.delete(user)
        await self.db.commit()
