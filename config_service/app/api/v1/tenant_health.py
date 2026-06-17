from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.core.db import get_db
from config_service.app.core.response import APIResponse
from config_service.app.core.response_utils import success_response, error_response
from config_service.app.services.tenant_health import TenantHealthService
from config_service.app.schemas.tenant_health import TenantHealthRow
from authentication_service.app.core.rbac import require_permission

router = APIRouter(prefix="/tenant-health", tags=["tenant-health"])


@router.get("", response_model=APIResponse[list[TenantHealthRow]])
async def get_tenant_health(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_permission("company_master:read")),
):
    if not getattr(current_user, "is_platform_admin", False):
        return error_response(
            message="Tenant health is available to platform admins only",
            status_code=403,
        )
    db.info["user_id"] = current_user.user_id
    svc = TenantHealthService(db)
    data = await svc.get_tenant_health()
    return success_response(data=data, message="Tenant health fetched")
