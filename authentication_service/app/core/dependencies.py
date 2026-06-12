import logging

from authentication_service.app.core.db import get_db
from authentication_service.app.repositories.revoked_token_repo import (
    RevokedTokenRepository,
)
from authentication_service.app.repositories.user_repo import AuthUserRepository
from authentication_service.app.schemas.auth import TokenUser
from fastapi import Depends, HTTPException, status
from authentication_service.app.core.security import oauth2_scheme, verify_access_token

from sqlalchemy.ext.asyncio import AsyncSession


_logger = logging.getLogger(__name__)


async def _enrich_with_company_user(db: AsyncSession, email: str) -> dict:
    """Look up the requester in `company_users` to recover the multi-tenant
    context (tenant_id, department_id, role_id) that the legacy JWT does not
    carry. Returns an empty dict if no matching CompanyUser exists (e.g.
    platform-level users such as SUPER ADMIN).
    """
    if not email:
        return {}
    try:
        from config_service.app.repositories.company_users import UserRepository

        record = await UserRepository(db).get_by_email(email)
    except Exception:
        return {}

    if record is None:
        return {}

    return {
        "tenant_id": getattr(record, "company_id", None),
        "department_id": getattr(record, "department_id", None),
        "role_id": getattr(record, "role_id", None),
    }


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> TokenUser:
    payload = verify_access_token(token)

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    # Reject tokens that were explicitly revoked via the /logout endpoint.
    # Tokens issued before jti was introduced have no jti and skip this check;
    # they expire naturally within ACCESS_TOKEN_EXPIRE_MINUTES.
    jti = payload.get("jti")
    if jti and await RevokedTokenRepository(db).exists(jti):
        # Diagnostic: log the rejected jti + iat so post-logout-then-relogin
        # 401s can be traced to a stale-token-on-client issue. Each fresh
        # login should produce a unique jti (uuid.uuid4 in
        # create_access_token), so a hit here means the request is carrying
        # the pre-logout token instead of the post-login one — check
        # frontend localStorage / interceptors / open tabs.
        _logger.warning(
            "REVOKED_TOKEN_REJECT | user_id=%s | jti=%s | iat=%s | "
            "Hint: this jti is in revoked_tokens. Client is sending an "
            "old token; verify the login response's access_token is "
            "replacing stored auth before the next request fires.",
            user_id, jti, payload.get("iat"),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await AuthUserRepository(db).get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is inactive",
        )

    # JWT payload takes precedence (so platform admin tokens can override),
    # but fall back to enriching from the company_users table when the token
    # doesn't carry tenant/department/role info.
    tenant_id = payload.get("tenant_id")
    department_id = payload.get("department_id")
    role_id = payload.get("role_id")
    if tenant_id is None and department_id is None and role_id is None:
        enriched = await _enrich_with_company_user(db, user.email)
        tenant_id = enriched.get("tenant_id")
        department_id = enriched.get("department_id")
        role_id = enriched.get("role_id")

    return TokenUser(
        user_id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        tenant_id=tenant_id,
        department_id=str(department_id) if department_id is not None else None,
        role_id=role_id,
        is_platform_admin=bool(payload.get("is_platform_admin", False)),
        vendor_id=payload.get("vendor_id"),
    )
