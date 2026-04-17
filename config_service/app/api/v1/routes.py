from fastapi import APIRouter
from . import health
from . import companies
from . import company_users
from . import kpi_questions
from . import kpi
from . import kpi_questions_admin
from . import employee_forms
from . import sessions
from . import themes
from . import challenges
from . import dashboard
from . import admin_suggestions
from . import admin_kpi_suggestion_mappings

router = APIRouter(prefix="/api/v1")
router.include_router(health.router, prefix="/health", tags=["health"])
router.include_router(companies.router)
router.include_router(company_users.router)
router.include_router(employee_forms.router)
router.include_router(kpi_questions.router)
router.include_router(kpi_questions_admin.router)
router.include_router(kpi.router)
router.include_router(sessions.router)
router.include_router(themes.router)
router.include_router(challenges.router)
router.include_router(dashboard.router)
router.include_router(admin_suggestions.router)
router.include_router(admin_kpi_suggestion_mappings.router)
