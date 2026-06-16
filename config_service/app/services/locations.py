from __future__ import annotations
"""Location master helpers.

`get_or_create_location` is the single entry point used by both the
company CRUD services and the backfill migration script. It owns the
normalization rules so they can't drift between live writes and bulk
backfills.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.models.location import Location


def normalize_location_name(raw: Optional[str]) -> Optional[tuple[str, str]]:
    """Return `(display_name, name_normalized)` or None for blank input.

    - Trim leading/trailing whitespace.
    - Collapse internal runs of whitespace to a single space.
    - `name_normalized` is the lowercase form (uniqueness key).
    - `name` is the title-cased canonical form (display).
    """
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    canonical = " ".join(stripped.split())
    return canonical.title(), canonical.lower()


async def get_or_create_location(
    raw_name: Optional[str],
    db: AsyncSession,
) -> Optional[UUID]:
    """Resolve a free-text location to a `locations.id`.

    Concurrency: the insert runs inside a SAVEPOINT so a unique-violation
    raised by a competing transaction is recovered locally — the outer
    transaction stays alive and the helper re-fetches the row the winner
    inserted. The caller owns the final commit.
    """
    parts = normalize_location_name(raw_name)
    if parts is None:
        return None
    display_name, normalized = parts

    res = await db.execute(
        select(Location).where(Location.name_normalized == normalized)
    )
    existing = res.scalar_one_or_none()
    if existing is not None:
        return existing.id

    try:
        async with db.begin_nested():
            new_loc = Location(name=display_name, name_normalized=normalized)
            db.add(new_loc)
            await db.flush()
        return new_loc.id
    except IntegrityError:
        res = await db.execute(
            select(Location).where(Location.name_normalized == normalized)
        )
        winner = res.scalar_one()
        return winner.id


async def get_location_names(
    location_ids,
    db: AsyncSession,
) -> dict:
    """Return `{location_id: name}` for the given ids (drops Nones)."""
    ids = [lid for lid in location_ids if lid is not None]
    if not ids:
        return {}
    res = await db.execute(
        select(Location.id, Location.name).where(Location.id.in_(ids))
    )
    return {row[0]: row[1] for row in res.all()}


async def list_locations(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    is_active: Optional[bool] = True,
) -> tuple[list[Location], int]:
    """Return `(items, total)` for the locations master list.

    `search` matches against `name_normalized` with a case-insensitive
    substring filter (input is normalized through the same rules so
    "  mumbai " and "Mumbai" hit the same prefix).
    """
    filters = [Location.is_deleted == False]  # noqa: E712
    if is_active is not None:
        filters.append(Location.is_active == is_active)
    if search:
        parts = normalize_location_name(search)
        if parts is not None:
            _, normalized = parts
            filters.append(Location.name_normalized.like(f"%{normalized}%"))

    total = (
        await db.execute(select(func.count(Location.id)).where(*filters))
    ).scalar_one()

    res = await db.execute(
        select(Location)
        .where(*filters)
        .order_by(Location.name.asc())
        .offset(skip)
        .limit(limit)
    )
    items = res.scalars().all()
    return items, int(total or 0)
