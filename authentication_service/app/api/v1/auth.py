from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.core.custom_loggers import get_file_logger
from authentication_service.app.core.db import get_db
from authentication_service.app.core.jwt import ACCESS_TOKEN_EXPIRE_MINUTES
from authentication_service.app.core.security import oauth2_scheme, verify_access_token
from authentication_service.app.repositories.revoked_token_repo import (
    RevokedTokenRepository,
)
from authentication_service.app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
)
from authentication_service.app.services.auth_service import AuthService


logger = get_file_logger(name="auth_api", prefix="auth_api")
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


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Invalidate the current access token by recording its `jti` claim in the
    `revoked_tokens` table. Every subsequent request that presents the same
    token will be rejected with 401 by `get_current_user`.

    The token must still be valid (not expired, not malformed) — `verify_access_token`
    will raise 401 otherwise. Calling logout a second time with the same token
    is a no-op success; the row insert collides on the unique `jti` index and
    is swallowed by the repository.
    """
    payload = verify_access_token(token)

    jti = payload.get("jti")
    user_id = payload.get("user_id")
    username = payload.get("sub")

    if not jti:
        # Token was issued before jti was introduced — nothing to revoke
        # server-side. Client must still drop the token locally. The token
        # will expire on its own within ACCESS_TOKEN_EXPIRE_MINUTES.
        logger.info(
            "LOGOUT | user_id=%s | username=%s | legacy_token_no_jti",
            user_id, username,
        )
        return LogoutResponse(
            success=True,
            message="Logged out. Token has no jti claim and will expire on its own.",
        )

    exp = payload.get("exp")
    if exp:
        expires_at = datetime.utcfromtimestamp(int(exp))
    else:
        # Defensive fallback: assume worst-case expiry from policy.
        expires_at = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    await RevokedTokenRepository(db).add(
        jti=jti,
        user_id=user_id if isinstance(user_id, int) else None,
        expires_at=expires_at,
    )

    logger.info(
        "LOGOUT | user_id=%s | username=%s | jti=%s | revoked",
        user_id, username, jti,
    )
    return LogoutResponse(success=True, message="Logged out successfully.")

