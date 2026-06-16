from __future__ import annotations
from authentication_service.app.schemas.auth import TokenUser
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from config_service.app.core.config import settings
from fastapi import Depends
Base = declarative_base()

# Async engine
engine = create_async_engine(
    settings.SQLALCHEMY_DATABASE_URI,  
    echo=False,
    future=True
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