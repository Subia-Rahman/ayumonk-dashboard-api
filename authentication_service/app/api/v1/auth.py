from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from authentication_service.app.schemas.auth import LoginRequest, LoginResponse
from authentication_service.app.services.auth_service import AuthService
from authentication_service.app.core.db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])

@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    return await AuthService(db).login(payload.username, payload.password)


@router.post("/token", response_model=LoginResponse)
async def login_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    return await AuthService(db).login(form_data.username, form_data.password)

