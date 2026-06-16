from __future__ import annotations
from datetime import datetime, timedelta
import jwt
from fastapi import HTTPException
from authentication_service.app.repositories.user_repo import AuthUserRepository
from authentication_service.app.schemas.auth import *
from authentication_service.app.models.user import User
from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.core.jwt import create_access_token
from authentication_service.app.core.rbac_constants import PLATFORM_LEGACY_ROLES
from authentication_service.app.core.security import verify_password

SECRET_KEY = "demo_secret_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

class AuthService:
    def __init__(self, db: AsyncSession):
        self.user_repo = AuthUserRepository(db)


    async def login(self, username: str, password: str):
        user = await self.user_repo.get_by_username(username)

        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        is_platform_admin = (user.role or "").upper() in PLATFORM_LEGACY_ROLES

        token = create_access_token({
            "sub": user.username,
            "role": user.role,
            "email": user.email,
            "user_id": user.id,
            "is_platform_admin": is_platform_admin,
        })

        return LoginResponse(
            access_token=token,
            token_type="bearer",
            user=user
        )

    async def create_admin(self, payload: CreateAdminRequest) -> UserResponse:
        existing_username = await self.user_repo.get_by_username(payload.username)
        if existing_username:
            raise HTTPException(status_code=409, detail="Username already exists")
        existing_email = await self.user_repo.get_by_email(payload.email)
        if existing_email:
            raise HTTPException(status_code=409, detail="Email already exists")

        user = User(
            username=payload.username,
            email=payload.email,
            hashed_password=payload.password,
            role="ADMIN",
            is_active=payload.is_active,
        )
        user = await self.user_repo.create(user)
        return UserResponse.model_validate(user)
