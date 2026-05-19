from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.repositories.role_repo import RoleRepository
from authentication_service.app.repositories.permission_repo import PermissionRepository
from authentication_service.app.repositories.role_permission_repo import RolePermissionRepository
from authentication_service.app.repositories.user_permission_repo import UserPermissionRepository
from authentication_service.app.repositories.policy_repo import PolicyRepository
from authentication_service.app.services.access_control_cache import SimpleCache


permissions_cache = SimpleCache(ttl_seconds=300)
policies_cache = SimpleCache(ttl_seconds=300)


class AccessControlService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.role_repo = RoleRepository(db)
        self.permission_repo = PermissionRepository(db)
        self.role_perm_repo = RolePermissionRepository(db)
        self.user_perm_repo = UserPermissionRepository(db)
        self.policy_repo = PolicyRepository(db)

    async def resolve_permissions(self, user, tenant_id: UUID) -> list[str]:
        cache_key = ("permissions", str(tenant_id), user.id)
        cached = permissions_cache.get(cache_key)
        if cached is not None:
            return cached

        role = await self.role_repo.get_by_name((user.role or "").upper(), tenant_id)
        role_permissions: list[str] = []
        if role:
            role_perm = await self.role_perm_repo.list_by_role(role.id, tenant_id)
            if role_perm:
                perms = await self.permission_repo.list()
                perm_map = {p.id: p for p in perms}
                for rp in role_perm:
                    perm = perm_map.get(rp.permission_id)
                    if perm:
                        role_permissions.append(perm.name)

        overrides = await self.user_perm_repo.list_by_user(user.id, tenant_id)
        now = datetime.now(timezone.utc)
        allow = set()
        deny = set()
        for ov in overrides:
            if ov.valid_from and ov.valid_from > now:
                continue
            if ov.valid_to and ov.valid_to < now:
                continue
            if ov.is_allowed:
                allow.add(ov.permission_id)
            else:
                deny.add(ov.permission_id)

        perm_map = {p.id: p.name for p in await self.permission_repo.list()}
        user_allowed = {perm_map.get(pid) for pid in allow if perm_map.get(pid)}
        user_denied = {perm_map.get(pid) for pid in deny if perm_map.get(pid)}

        final = set(role_permissions)
        final |= user_allowed
        final -= user_denied

        result = sorted(final)
        permissions_cache.set(cache_key, result)
        return result

    async def list_policies(self, tenant_id: UUID, module: str | None = None):
        cache_key = ("policies", str(tenant_id), module)
        cached = policies_cache.get(cache_key)
        if cached is not None:
            return cached
        policies = await self.policy_repo.list(tenant_id=tenant_id, module=module)
        policies_cache.set(cache_key, policies)
        return policies

    def invalidate_permissions(self, tenant_id: UUID, user_id: int | None = None):
        if user_id:
            permissions_cache.invalidate_prefix(("permissions", str(tenant_id), user_id))
        else:
            permissions_cache.invalidate_prefix(("permissions", str(tenant_id)))

    def invalidate_policies(self, tenant_id: UUID):
        policies_cache.invalidate_prefix(("policies", str(tenant_id)))
