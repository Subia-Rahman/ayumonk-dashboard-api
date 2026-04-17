from authentication_service.app.core.db import get_db
from authentication_service.app.repositories.user_repo import AuthUserRepository
from authentication_service.app.schemas.auth import TokenUser
from fastapi import Depends, HTTPException, status
from authentication_service.app.core.security import oauth2_scheme, verify_access_token

from sqlalchemy.ext.asyncio import AsyncSession

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> TokenUser:
    payload = verify_access_token(token)

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )

    user = await AuthUserRepository(db).get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive"
        )

    return TokenUser(
        user_id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        vendor_id=payload.get("vendor_id")
    )

def require_roles(*roles: str):
    def role_checker(user = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden"
            )
        return user
    return role_checker
