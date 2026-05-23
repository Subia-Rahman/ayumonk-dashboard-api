"""Seeder for the default RBAC rows attached to every newly created tenant.

`assign_default_company_data` is invoked from inside the company-creation
transaction (after the company row has been flushed but before commit). The
function uses the same `db` session as its caller and never commits or
rolls back — that responsibility stays with the caller so company creation
and default seeding succeed or fail atomically.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authentication_service.app.models.menu import Menu
from authentication_service.app.models.permission import Permission
from authentication_service.app.models.policy import Policy
from authentication_service.app.models.role import Role
from authentication_service.app.models.role_menu import RoleMenu
from authentication_service.app.models.role_permission import RolePermission
from authentication_service.app.models.role_policy import RolePolicy
from authentication_service.app.models.user_menu import UserMenu
from authentication_service.app.models.user_permission import UserPermission
from authentication_service.app.models.user_policy import UserPolicy
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.core.default_company_data import (
    DEFAULT_POLICIES,
    DEFAULT_ROLE_MENUS,
    DEFAULT_ROLE_PERMISSIONS,
    DEFAULT_ROLE_POLICIES,
    DEFAULT_ROLES,
    DEFAULT_USER_MENUS,
    DEFAULT_USER_PERMISSIONS,
    DEFAULT_USER_POLICIES,
)


logger = get_file_logger(
    name="company_defaults_service",
    prefix="company_defaults_service",
)


async def assign_default_company_data(
    company_id: str | UUID,
    db: AsyncSession,
) -> dict[str, Any]:
    """Automatically assign default RBAC rows to a newly created company.

    Called inside the same transaction as the company INSERT so the company
    row and its default RBAC scaffolding either both persist or both roll
    back together. Does not commit or rollback the session.

    Returns a summary dict of how many rows were inserted per table.
    """
    tenant_id = UUID(company_id) if isinstance(company_id, str) else company_id

    logger.info("Assigning default data to company: %s", tenant_id)

    # ------------------------------------------------------------------
    # Step 1 — Create per-tenant roles, build role_id_map (name -> id).
    # ------------------------------------------------------------------
    role_id_map: dict[str, int] = {}
    role_objs: list[Role] = []
    for entry in DEFAULT_ROLES:
        role = Role(
            name=entry["name"],
            tenant_id=tenant_id,
            is_active=entry.get("is_active", True),
        )
        db.add(role)
        role_objs.append(role)
    await db.flush()
    for role in role_objs:
        role_id_map[role.name] = role.id
    logger.info(
        "Default roles created: %s",
        [r.name for r in role_objs],
    )

    # ------------------------------------------------------------------
    # Look up the global menu catalog (tenant_id IS NULL) by slug. Missing
    # slugs are skipped — the catalog is the source of truth.
    # ------------------------------------------------------------------
    menu_rows = (await db.execute(select(Menu))).scalars().all()
    menu_id_by_slug: dict[str, int] = {m.slug: m.id for m in menu_rows if m.slug}

    # Permission catalog is global too.
    perm_rows = (await db.execute(select(Permission))).scalars().all()
    perm_id_by_codename: dict[str, int] = {
        p.codename: p.id for p in perm_rows if p.codename
    }

    # ------------------------------------------------------------------
    # Step 2 — Role menu assignments.
    # ------------------------------------------------------------------
    role_menus_assigned = 0
    for role_name, entries in DEFAULT_ROLE_MENUS.items():
        role_id = role_id_map.get(role_name)
        if role_id is None:
            continue
        for entry in entries:
            menu_id = menu_id_by_slug.get(entry["menu_slug"])
            if menu_id is None:
                continue
            db.add(
                RoleMenu(
                    role_id=role_id,
                    menu_id=menu_id,
                    tenant_id=tenant_id,
                    access_level=entry["access_level"],
                )
            )
            role_menus_assigned += 1

    # ------------------------------------------------------------------
    # Step 3 — Role permission grants.
    # ------------------------------------------------------------------
    role_permissions_assigned = 0
    for role_name, entries in DEFAULT_ROLE_PERMISSIONS.items():
        role_id = role_id_map.get(role_name)
        if role_id is None:
            continue
        for entry in entries:
            perm_id = perm_id_by_codename.get(entry["codename"])
            if perm_id is None:
                continue
            db.add(
                RolePermission(
                    role_id=role_id,
                    permission_id=perm_id,
                    tenant_id=tenant_id,
                    is_override=entry.get("is_override", False),
                    is_granted=entry.get("is_granted", True),
                )
            )
            role_permissions_assigned += 1

    # ------------------------------------------------------------------
    # Step 4 — Create per-tenant policies, then assign them to roles.
    # ------------------------------------------------------------------
    policy_id_by_name: dict[str, int] = {}
    policy_objs: list[Policy] = []
    for entry in DEFAULT_POLICIES:
        policy = Policy(
            name=entry["name"],
            description=entry["description"],
            module=entry["module"],
            scope=entry["scope"],
            conditions=entry["conditions"],
            condition_json=entry["conditions"] or {},
            effect=entry["effect"],
            tenant_id=tenant_id,
            is_active=entry.get("is_active", True),
        )
        db.add(policy)
        policy_objs.append(policy)
    await db.flush()
    for policy in policy_objs:
        policy_id_by_name[policy.name] = policy.id

    role_policies_assigned = 0
    for role_name, policy_names in DEFAULT_ROLE_POLICIES.items():
        role_id = role_id_map.get(role_name)
        if role_id is None:
            continue
        for policy_name in policy_names:
            policy_id = policy_id_by_name.get(policy_name)
            if policy_id is None:
                continue
            db.add(
                RolePolicy(
                    role_id=role_id,
                    policy_id=policy_id,
                    tenant_id=tenant_id,
                )
            )
            role_policies_assigned += 1

    # ------------------------------------------------------------------
    # Steps 5-7 — Per-user defaults. The reference tenant has zero rows in
    # user_menus / user_policies / user_permissions, so no rows are inserted
    # here. If DEFAULT_USER_* ever grow entries, this loop will handle them.
    # ------------------------------------------------------------------
    user_menus_assigned = 0
    for entry in DEFAULT_USER_MENUS:
        menu_id = menu_id_by_slug.get(entry["menu_slug"])
        if menu_id is None:
            continue
        db.add(
            UserMenu(
                user_id=entry["user_id"],
                menu_id=menu_id,
                is_active=entry.get("is_active", True),
                tenant_id=tenant_id,
                access_level=entry["access_level"],
            )
        )
        user_menus_assigned += 1

    user_policies_assigned = 0
    for entry in DEFAULT_USER_POLICIES:
        policy_id = policy_id_by_name.get(entry["policy_name"])
        if policy_id is None:
            continue
        db.add(
            UserPolicy(
                user_id=entry["user_id"],
                policy_id=policy_id,
                tenant_id=tenant_id,
            )
        )
        user_policies_assigned += 1

    user_permissions_assigned = 0
    for entry in DEFAULT_USER_PERMISSIONS:
        perm_id = perm_id_by_codename.get(entry["codename"])
        if perm_id is None:
            continue
        db.add(
            UserPermission(
                user_id=entry["user_id"],
                permission_id=perm_id,
                is_allowed=entry.get("is_allowed", True),
                is_granted=entry.get("is_granted", True),
                tenant_id=tenant_id,
            )
        )
        user_permissions_assigned += 1

    await db.flush()

    summary = {
        "roles_created": len(role_id_map),
        "role_menus_assigned": role_menus_assigned,
        "role_permissions_assigned": role_permissions_assigned,
        "role_policies_assigned": role_policies_assigned,
        "policies_created": len(policy_id_by_name),
        "user_menus_assigned": user_menus_assigned,
        "user_policies_assigned": user_policies_assigned,
        "user_permissions_assigned": user_permissions_assigned,
    }
    logger.info("Default data assignment complete: %s", summary)
    return summary
