from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.badge_master import BadgeMaster
from config_service.app.models.kpi import KPI
from config_service.app.models.user_badge import UserBadge
from config_service.app.repositories.company_users import UserRepository as CompanyUserRepository
from config_service.app.schemas.badges import BadgeWithStatus, MyBadgesResponse


class BadgesService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.company_user_repo = CompanyUserRepository(db)

    async def list_for_user(self, *, user_id: int, user_email: str) -> MyBadgesResponse:
        """
        Return every visible badge for this user with earned/locked status.

        Visibility rule: include the badge if it's global (kpi_key IS NULL) OR
        scoped to a KPI in the caller's company. Other companies' KPI badges
        are filtered out so the UI doesn't render tiles the user can never
        earn.

        Ordering: global badges first (kpi_key NULLS FIRST), then per-KPI
        groups, then by trigger_value ascending so tiers within a group
        render Bronze → Silver → Gold left-to-right.
        """
        company_user = await self.company_user_repo.get_by_email(user_email)
        if not company_user:
            raise BusinessException(message="Company not found for user", status_code=403)

        stmt = (
            select(
                BadgeMaster,
                UserBadge.earned_at,
                KPI.display_name,
            )
            .select_from(BadgeMaster)
            .outerjoin(
                UserBadge,
                (UserBadge.badge_id == BadgeMaster.id)
                & (UserBadge.user_id == user_id),
            )
            .outerjoin(KPI, KPI.kpi_key == BadgeMaster.kpi_key)
            .where(
                BadgeMaster.is_active == True,    # noqa: E712
                BadgeMaster.is_deleted == False,  # noqa: E712
                or_(
                    BadgeMaster.kpi_key.is_(None),
                    KPI.company_id == company_user.company_id,
                ),
            )
            .order_by(
                BadgeMaster.kpi_key.asc().nullsfirst(),
                BadgeMaster.trigger_type.asc(),
                BadgeMaster.trigger_value.asc(),
            )
        )
        rows = (await self.db.execute(stmt)).all()

        badges: list[BadgeWithStatus] = []
        earned = 0
        for badge, earned_at, kpi_display_name in rows:
            is_earned = earned_at is not None
            if is_earned:
                earned += 1
            badges.append(
                BadgeWithStatus(
                    badge_key=badge.badge_key,
                    label=badge.label,
                    icon=badge.icon,
                    level=badge.level,
                    trigger_type=badge.trigger_type,
                    trigger_value=badge.trigger_value,
                    kpi_key=badge.kpi_key,
                    kpi_display_name=kpi_display_name,
                    earned=is_earned,
                    earned_at=earned_at,
                )
            )

        return MyBadgesResponse(
            badges=badges,
            earned_count=earned,
            total_count=len(badges),
        )
