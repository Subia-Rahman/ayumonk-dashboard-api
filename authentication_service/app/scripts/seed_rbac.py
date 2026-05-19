"""RBAC seed script.

Seeds menus, permissions, role-menu access mappings, default policies and
role-policy assignments for a given tenant (company).

Tenant ID is the UUID of a row in the `companies` table.

Usage:
    python -m authentication_service.app.scripts.seed_rbac --tenant-id 6f1a4f2e-8a37-4f7d-bf4d-bcb0c4d5e9c1
"""

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from authentication_service.app.core.db import AsyncSessionLocal
from authentication_service.app.core.rbac_constants import (
    DEFAULT_POLICIES,
    PERMISSION_ACTIONS,
    PLATFORM_ROLES,
    RBAC_MENUS,
    RBAC_RESOURCES,
    RBAC_ROLES,
    ROLE_MENU_ACCESS_MATRIX,
    ROLE_POLICY_ASSIGNMENTS,
    access_level_to_permissions,
)
from authentication_service.app.models.menu import Menu
from authentication_service.app.models.permission import Permission
from authentication_service.app.models.policy import Policy
from authentication_service.app.models.role import Role
from authentication_service.app.models.role_menu import RoleMenu
from authentication_service.app.models.role_permission import RolePermission
from authentication_service.app.models.role_policy import RolePolicy


async def seed_menus(db, tenant_id: UUID) -> dict[str, Menu]:
    """Look up the global menu catalog (tenant_id IS NULL) by slug.

    Menus became a tenant-agnostic catalog: one row per slug stored with
    `tenant_id = NULL`. Per-tenant role_menus rows reference these global
    rows. This function therefore does NOT create per-tenant menu copies —
    it just resolves slug -> Menu so the caller can build role_menus.
    """
    existing = (
        (await db.execute(select(Menu))).scalars().all()
    )
    by_slug = {m.slug: m for m in existing if m.slug}

    resolved: dict[str, Menu] = {}
    for entry in RBAC_MENUS:
        slug = entry["slug"]
        menu = by_slug.get(slug)
        if menu is None:
            # Platform menus may not yet be seeded (run seed_rbac_super_admin.sql
            # first). Skip silently so the rest of the per-tenant seed still
            # makes progress.
            continue
        resolved[slug] = menu
    return resolved


async def seed_permissions(db) -> dict[str, Permission]:
    existing = (await db.execute(select(Permission))).scalars().all()
    by_codename = {p.codename: p for p in existing if p.codename}
    by_name = {p.name: p for p in existing}

    created: dict[str, Permission] = {}
    for resource in RBAC_RESOURCES:
        for action in PERMISSION_ACTIONS:
            codename = f"{resource}:{action}"
            name = codename
            perm = by_codename.get(codename) or by_name.get(name)
            if perm is None:
                perm = Permission(
                    name=name,
                    codename=codename,
                    resource=resource,
                    module=resource,
                    action=action,
                )
                db.add(perm)
            else:
                changed = False
                if perm.codename != codename:
                    perm.codename = codename
                    changed = True
                if perm.resource != resource:
                    perm.resource = resource
                    changed = True
                if changed:
                    db.add(perm)
            created[codename] = perm
    await db.commit()
    for perm in created.values():
        await db.refresh(perm)
    return created


async def seed_roles(db, tenant_id: UUID) -> dict[str, Role]:
    """Seed per-tenant roles. Platform-wide roles are handled separately
    by `seed_platform_roles` and are excluded here."""
    existing = (
        (await db.execute(select(Role).where(Role.tenant_id == tenant_id))).scalars().all()
    )
    by_name = {r.name: r for r in existing}

    created: dict[str, Role] = {}
    for name in RBAC_ROLES:
        if name in PLATFORM_ROLES:
            continue
        role = by_name.get(name)
        if role is None:
            role = Role(name=name, tenant_id=tenant_id, is_active=True)
            db.add(role)
        created[name] = role
    await db.commit()
    for role in created.values():
        await db.refresh(role)
    return created


async def seed_platform_roles(db) -> dict[str, Role]:
    """Seed platform-wide roles (Super Admin, Ayumonk Admin) with
    tenant_id = NULL. Idempotent. Runtime access for these roles is granted
    via the JWT `is_platform_admin` flag, so no role_menus / role_permissions
    / role_policies rows are created.
    """
    existing = (
        (await db.execute(select(Role).where(Role.tenant_id.is_(None))))
        .scalars()
        .all()
    )
    by_name = {r.name: r for r in existing}

    created: dict[str, Role] = {}
    for name in PLATFORM_ROLES:
        role = by_name.get(name)
        if role is None:
            role = Role(name=name, tenant_id=None, is_active=True)
            db.add(role)
        created[name] = role
    await db.commit()
    for role in created.values():
        await db.refresh(role)
    return created


async def seed_role_menus(
    db,
    tenant_id: UUID,
    roles: dict[str, Role],
    menus: dict[str, Menu],
):
    existing_rows = (
        (await db.execute(select(RoleMenu).where(RoleMenu.tenant_id == tenant_id))).scalars().all()
    )
    existing_index = {(rm.role_id, rm.menu_id): rm for rm in existing_rows}

    for role_name, slug_to_level in ROLE_MENU_ACCESS_MATRIX.items():
        role = roles.get(role_name)
        if role is None:
            continue
        for slug, access_level in slug_to_level.items():
            menu = menus.get(slug)
            if menu is None:
                continue
            row = existing_index.get((role.id, menu.id))
            if row:
                if row.access_level != access_level:
                    row.access_level = access_level
                    db.add(row)
            else:
                db.add(
                    RoleMenu(
                        role_id=role.id,
                        menu_id=menu.id,
                        tenant_id=tenant_id,
                        access_level=access_level,
                    )
                )
    await db.commit()


async def seed_role_permissions(
    db,
    tenant_id: UUID,
    roles: dict[str, Role],
    menus: dict[str, Menu],
    permissions: dict[str, Permission],
):
    """Materialize role->permission rows from the role-menu access matrix.

    Permissions can be overridden manually via the API, so we only create
    rows for codenames derived from the access_level matrix.
    """
    from authentication_service.app.core.rbac_constants import MENU_SLUG_TO_RESOURCE

    existing_rows = (
        (await db.execute(select(RolePermission)))
        .scalars()
        .all()
    )
    # Track all (role_id, permission_id) pairs that already exist OR have been
    # queued in this run, since the unique constraint is global on
    # (role_id, permission_id) and multiple menu slugs can map to the same
    # resource (e.g. company-data and company-details both -> company_master).
    seen_pairs: set[tuple[int, int]] = {
        (rp.role_id, rp.permission_id) for rp in existing_rows
    }

    for role_name, slug_to_level in ROLE_MENU_ACCESS_MATRIX.items():
        role = roles.get(role_name)
        if role is None:
            continue
        for slug, level in slug_to_level.items():
            resource = MENU_SLUG_TO_RESOURCE.get(slug)
            if not resource:
                continue
            for codename in access_level_to_permissions(resource, level):
                perm = permissions.get(codename)
                if perm is None:
                    continue
                key = (role.id, perm.id)
                if key in seen_pairs:
                    continue
                db.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=perm.id,
                        tenant_id=tenant_id,
                        is_override=False,
                        is_granted=True,
                    )
                )
                seen_pairs.add(key)
    await db.commit()


async def seed_policies(db, tenant_id: UUID) -> dict[str, Policy]:
    existing = (
        (await db.execute(select(Policy).where(Policy.tenant_id == tenant_id))).scalars().all()
    )
    by_name = {p.name: p for p in existing}

    created: dict[str, Policy] = {}
    for entry in DEFAULT_POLICIES:
        name = entry["name"]
        policy = by_name.get(name)
        if policy is None:
            policy = Policy(
                name=name,
                description=entry["description"],
                module="global",
                scope=entry["scope"],
                conditions=entry["conditions"],
                condition_json=entry["conditions"] or {},
                effect="allow",
                tenant_id=tenant_id,
                is_active=True,
            )
            db.add(policy)
        else:
            changed = False
            if policy.scope != entry["scope"]:
                policy.scope = entry["scope"]
                changed = True
            if policy.description != entry["description"]:
                policy.description = entry["description"]
                changed = True
            if policy.conditions != entry["conditions"]:
                policy.conditions = entry["conditions"]
                changed = True
            if changed:
                db.add(policy)
        created[name] = policy
    await db.commit()
    for policy in created.values():
        await db.refresh(policy)
    return created


async def seed_role_policies(
    db,
    tenant_id: UUID,
    roles: dict[str, Role],
    policies: dict[str, Policy],
):
    existing = (
        (await db.execute(select(RolePolicy).where(RolePolicy.tenant_id == tenant_id)))
        .scalars()
        .all()
    )
    existing_index = {(rp.role_id, rp.policy_id) for rp in existing}

    for role_name, policy_name in ROLE_POLICY_ASSIGNMENTS.items():
        role = roles.get(role_name)
        policy = policies.get(policy_name)
        if role is None or policy is None:
            continue
        if (role.id, policy.id) in existing_index:
            continue
        db.add(
            RolePolicy(
                role_id=role.id,
                policy_id=policy.id,
                tenant_id=tenant_id,
            )
        )
    await db.commit()


async def run(tenant_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        print(f"Seeding RBAC for tenant_id={tenant_id}")

        menus = await seed_menus(db, tenant_id)
        print(f"  menus: {len(menus)}")

        permissions = await seed_permissions(db)
        print(f"  permissions: {len(permissions)}")

        roles = await seed_roles(db, tenant_id)
        print(f"  roles (per-tenant): {len(roles)}")

        platform_roles = await seed_platform_roles(db)
        print(f"  roles (platform): {len(platform_roles)}")

        await seed_role_menus(db, tenant_id, roles, menus)
        print("  role-menu access mappings seeded")

        await seed_role_permissions(db, tenant_id, roles, menus, permissions)
        print("  role-permission grants seeded")

        policies = await seed_policies(db, tenant_id)
        print(f"  policies: {len(policies)}")

        await seed_role_policies(db, tenant_id, roles, policies)
        print("  role-policy assignments seeded")

        print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed RBAC data")
    parser.add_argument(
        "--tenant-id",
        type=UUID,
        required=True,
        help="Tenant UUID (companies.id) to seed",
    )
    args = parser.parse_args()
    asyncio.run(run(args.tenant_id))


if __name__ == "__main__":
    main()
