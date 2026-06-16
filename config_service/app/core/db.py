from __future__ import annotations
from authentication_service.app.schemas.auth import TokenUser
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from config_service.app.core.config import settings
from fastapi import Depends
Base = declarative_base()

# Async engine with explicit pool sizing. The reminder dispatcher fans out
# work concurrently, so the default (pool_size=5, max_overflow=10) is too
# tight under load. pool_pre_ping silently swaps dead connections instead of
# raising on the next checkout.
engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    echo=False,
    future=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    pool_pre_ping=True,
)

# Async session factory
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Dependency for FastAPI
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session