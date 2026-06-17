from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from config_service.app.schemas.tenant_health import TenantHealthRow

TENANT_HEALTH_SQL = text("""
    SELECT
        c.id AS id,
        c.company_name AS company_name,
        c.industry AS industry,
        c.size_bucket AS size_bucket,
        c.no_of_employees AS no_of_employees,
        COUNT(DISTINCT cu.id) FILTER (WHERE cu.is_deleted = false) AS registered_employees,
        COALESCE(efr.active_employees, 0) AS active_employees,
        efr.last_activity AS last_activity
    FROM companies c
    LEFT JOIN company_users cu ON cu.company_id = c.id
    LEFT JOIN (
        SELECT company_id,
               COUNT(DISTINCT employee_email) AS active_employees,
               MAX(submitted_at) AS last_activity
        FROM employee_form_response
        WHERE is_deleted = false
        GROUP BY company_id
    ) efr ON efr.company_id = c.id::text
    WHERE c.is_deleted = false
    GROUP BY c.id, c.company_name, c.industry, c.size_bucket,
             c.no_of_employees, efr.active_employees, efr.last_activity
    ORDER BY c.company_name
""")


class TenantHealthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_tenant_health(self) -> list[TenantHealthRow]:
        result = await self.db.execute(TENANT_HEALTH_SQL)
        rows = result.mappings().all()
        now = datetime.now(timezone.utc)
        out: list[TenantHealthRow] = []
        for r in rows:
            registered = r["registered_employees"] or 0
            active = r["active_employees"] or 0
            onboarding_pct = round((active / registered) * 100, 1) if registered else 0.0
            last_activity = r["last_activity"]
            days_since = None
            if last_activity is not None:
                la = last_activity
                if la.tzinfo is None:
                    la = la.replace(tzinfo=timezone.utc)
                days_since = (now - la).days
            out.append(TenantHealthRow(
                id=r["id"],
                company_name=r["company_name"],
                industry=r["industry"],
                size_bucket=r["size_bucket"],
                no_of_employees=r["no_of_employees"],
                registered_employees=registered,
                active_employees=active,
                onboarding_pct=onboarding_pct,
                last_activity=last_activity,
                days_since_activity=days_since,
            ))
        return out
