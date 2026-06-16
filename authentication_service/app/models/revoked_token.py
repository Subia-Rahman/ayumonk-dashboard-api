from __future__ import annotations
from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from authentication_service.app.core.db import Base


class RevokedToken(Base):
    """A token that has been invalidated before its natural expiry.

    `jti` is the JWT ID claim issued when the access token was minted; it is
    the stable identifier we use to deny re-use. `expires_at` matches the
    token's `exp` claim so a periodic cleanup can drop rows after the token
    would have expired on its own.
    """

    __tablename__ = "revoked_tokens"

    id = Column(BigInteger, primary_key=True, index=True)
    jti = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    revoked_at = Column(DateTime, server_default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)
