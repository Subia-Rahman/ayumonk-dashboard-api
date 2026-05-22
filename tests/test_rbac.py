"""RBAC tests for the CXO endpoints.

* admin (company-tier) calling another company's mapping -> 403.
* hr calling PUT -> 403.

Both checks happen in `cxo_metrics_dependencies` before the endpoint runs,
so we test them in isolation rather than driving FastAPI.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from config_service.app.core import cxo_metrics_dependencies as deps
from config_service.app.core.cxo_metrics_dependencies import (
    require_cxo_metrics_read,
    require_cxo_metrics_write,
)


def _token_user(*, role: str, is_platform_admin: bool = False, tenant_id=None, email: str = "u@example.com"):
    user = MagicMock()
    user.user_id = 1
    user.username = "u"
    user.email = email
    user.role = role
    user.is_platform_admin = is_platform_admin
    user.tenant_id = tenant_id
    return user


@pytest.mark.asyncio
async def test_admin_cannot_access_other_company():
    """A company admin's company_id query param must match their tenant."""
    own_tenant = uuid4()
    other_tenant = uuid4()

    fake_user = _token_user(role="ADMIN", tenant_id=own_tenant)
    fake_requester = MagicMock()
    fake_requester.company_id = own_tenant
    fake_requester.role_id = None
    db = MagicMock()

    with patch.object(deps, "UserRepository") as repo_cls:
        repo_inst = MagicMock()
        repo_inst.get_by_email = AsyncMock(return_value=fake_requester)
        repo_cls.return_value = repo_inst

        with pytest.raises(HTTPException) as exc:
            await require_cxo_metrics_read(
                company_id=other_tenant, db=db, current_user=fake_user
            )
        assert exc.value.status_code == 403
        assert "company_id" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_hr_cannot_write_cxo_mapping():
    """HR Manager calling the write-protected dependency must get 403."""

    fake_user = _token_user(role="USER")  # legacy role doesn't carry HR signal
    fake_requester = MagicMock()
    fake_requester.company_id = uuid4()
    fake_requester.role_id = 999
    fake_role = MagicMock()
    fake_role.name = "HR Manager"
    db = MagicMock()

    with (
        patch.object(deps, "UserRepository") as repo_cls,
        patch.object(deps, "RoleRepository") as role_cls,
    ):
        repo_inst = MagicMock()
        repo_inst.get_by_email = AsyncMock(return_value=fake_requester)
        repo_cls.return_value = repo_inst
        role_inst = MagicMock()
        role_inst.get_by_id = AsyncMock(return_value=fake_role)
        role_cls.return_value = role_inst

        with pytest.raises(HTTPException) as exc:
            await require_cxo_metrics_write(db=db, current_user=fake_user)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_platform_admin_can_read_any_company():
    fake_user = _token_user(role="SUPER ADMIN", is_platform_admin=True)
    db = MagicMock()
    other_tenant = uuid4()

    ctx = await require_cxo_metrics_read(
        company_id=other_tenant, db=db, current_user=fake_user
    )
    assert ctx.is_platform_admin is True
    assert ctx.resolved_role == "super_admin"
