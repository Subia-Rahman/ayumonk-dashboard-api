from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from authentication_service.app.repositories.menu_repo import MenuRepository
from authentication_service.app.repositories.role_menu_repo import RoleMenuRepository
from authentication_service.app.repositories.user_menu_repo import UserMenuRepository
from authentication_service.app.services.access_control_cache import SimpleCache


menu_cache = SimpleCache(ttl_seconds=300)


class MenuService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.menu_repo = MenuRepository(db)
        self.role_menu_repo = RoleMenuRepository(db)
        self.user_menu_repo = UserMenuRepository(db)

    async def resolve_menus(self, user, role_id: int, tenant_id: UUID):
        cache_key = ("menus", str(tenant_id), user.user_id)
        cached = menu_cache.get(cache_key)
        if cached is not None:
            return cached

        role_menus = await self.role_menu_repo.list_by_role(role_id, tenant_id)
        user_menus = await self.user_menu_repo.list_by_user(user.user_id, tenant_id)
        menu_ids = {rm.menu_id for rm in role_menus}
        for um in user_menus:
            if um.is_active:
                menu_ids.add(um.menu_id)
            else:
                menu_ids.discard(um.menu_id)

        menus = await self.menu_repo.list()
        menu_map = {m.id: m for m in menus}

        final_ids = set(menu_ids)
        for mid in list(menu_ids):
            parent_id = menu_map.get(mid).parent_id if menu_map.get(mid) else None
            while parent_id:
                final_ids.add(parent_id)
                parent_id = menu_map.get(parent_id).parent_id if menu_map.get(parent_id) else None

        result = [menu_map[mid] for mid in final_ids if mid in menu_map]
        menu_cache.set(cache_key, result)
        return result

    def invalidate(self, tenant_id: UUID, user_id: int | None = None):
        if user_id:
            menu_cache.invalidate_prefix(("menus", str(tenant_id), user_id))
        else:
            menu_cache.invalidate_prefix(("menus", str(tenant_id)))

    def invalidate_all(self):
        """Wipe every cached menu resolution. Use after platform-wide menu
        catalog changes (CRUD on the global menus table)."""
        menu_cache.invalidate_prefix(("menus",))
