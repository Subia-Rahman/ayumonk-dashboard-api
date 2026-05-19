from enum import Enum


class MenuAccessLevel(str, Enum):
    NONE = "none"
    VIEW = "view"
    FULL = "full"


MENU_ACCESS_LEVEL_RANK = {
    MenuAccessLevel.NONE.value: 0,
    MenuAccessLevel.VIEW.value: 1,
    MenuAccessLevel.FULL.value: 2,
}


class PolicyScope(str, Enum):
    GLOBAL = "global"
    TENANT = "tenant"
    DEPARTMENT = "department"
    SELF = "self"


POLICY_SCOPE_RANK = {
    PolicyScope.GLOBAL.value: 0,
    PolicyScope.TENANT.value: 1,
    PolicyScope.DEPARTMENT.value: 2,
    PolicyScope.SELF.value: 3,
}


ACCESS_LEVEL_PERMISSION_MAP = {
    MenuAccessLevel.VIEW.value: ["{resource}:read"],
    MenuAccessLevel.FULL.value: [
        "{resource}:read",
        "{resource}:create",
        "{resource}:update",
        "{resource}:delete",
    ],
}


PERMISSION_ACTIONS = ["read", "create", "update", "delete"]


RBAC_RESOURCES = [
    "company_master",
    "company_users",
    "departments",
    "themes",
    "kpis",
    "challenges",
    "suggestion",
    "sessions",
    "hr_analytics",
    "hr_dashboard",
    "ayufinity",
    "platform",
]


RBAC_MENUS = [
    {"name": "Company Data", "slug": "company-data"},
    {"name": "Company Users", "slug": "company-users"},
    {"name": "Departments", "slug": "departments"},
    {"name": "Questions", "slug": "questions"},
    {"name": "Themes", "slug": "themes"},
    {"name": "KPIs", "slug": "kpis"},
    {"name": "Challenges", "slug": "challenges"},
    {"name": "Sessions", "slug": "sessions"},
    {"name": "Suggestion Master", "slug": "suggestion-master"},
    {"name": "KPI Suggestion Mapping", "slug": "kpi-suggestion-mapping"},
    {"name": "Profile", "slug": "profile"},
    {"name": "Company Details", "slug": "company-details"},
    {"name": "HR Dashboard", "slug": "hr-dashboard"},
]


MENU_SLUG_TO_RESOURCE = {
    "company-data": "company_master",
    "company-details": "company_master",
    "company-users": "company_users",
    "departments": "departments",
    "themes": "themes",
    "kpis": "kpis",
    "questions": "kpis",
    "challenges": "challenges",
    "sessions": "sessions",
    # Employee-facing "View my submissions" menu reuses the sessions resource
    # so granting submissions:view auto-derives sessions:read without exposing
    # the admin-only Sessions menu in the sidebar.
    "submissions": "sessions",
    "suggestion-master": "suggestion",
    "kpi-suggestion-mapping": "suggestion",
    "profile": "platform",
    "hr-dashboard": "hr_dashboard",
}


RBAC_ROLES = [
    "Employee",
    "HR Manager",
    "CXO",
    "Company Admin",
    "Ayumonk Admin",
    "Super Admin",
]

# Platform-wide roles span all tenants and are stored with tenant_id = NULL.
# Runtime access for these roles is gated by the JWT `is_platform_admin` flag,
# so they do NOT get role_menus / role_permissions / role_policies rows.
# The per-tenant seed loop must skip these names.
PLATFORM_ROLES: set[str] = {"Super Admin", "Ayumonk Admin"}

# Legacy `users.role` string values that map to platform-admin status.
# Compared against `user.role.upper()`. Used by the login token issuer to set
# the JWT `is_platform_admin` flag, and by config_service request gates to
# bypass tenant scoping.
PLATFORM_LEGACY_ROLES: set[str] = {
    "SUPER ADMIN",
    "SUPERADMIN",
    "AYUMONK ADMIN",
    "AYUMONKADMIN",
}


ROLE_MENU_ACCESS_MATRIX: dict[str, dict[str, str]] = {
    # Super Admin / Ayumonk Admin are intentionally absent — they are
    # platform-wide roles (see PLATFORM_ROLES) and bypass role_menus via the
    # JWT `is_platform_admin` flag.
    "Company Admin": {
        "company-data": MenuAccessLevel.FULL.value,
        "company-details": MenuAccessLevel.FULL.value,
        "company-users": MenuAccessLevel.FULL.value,
        "departments": MenuAccessLevel.FULL.value,
        "themes": MenuAccessLevel.FULL.value,
        "kpis": MenuAccessLevel.FULL.value,
        "questions": MenuAccessLevel.FULL.value,
        "challenges": MenuAccessLevel.FULL.value,
        "sessions": MenuAccessLevel.FULL.value,
        "suggestion-master": MenuAccessLevel.FULL.value,
        "kpi-suggestion-mapping": MenuAccessLevel.FULL.value,
        "profile": MenuAccessLevel.FULL.value,
    },
    "CXO": {
        "company-data": MenuAccessLevel.VIEW.value,
        "company-details": MenuAccessLevel.VIEW.value,
        "company-users": MenuAccessLevel.VIEW.value,
        "departments": MenuAccessLevel.VIEW.value,
        "themes": MenuAccessLevel.VIEW.value,
        "kpis": MenuAccessLevel.VIEW.value,
        "questions": MenuAccessLevel.VIEW.value,
        "challenges": MenuAccessLevel.VIEW.value,
        "sessions": MenuAccessLevel.VIEW.value,
        "suggestion-master": MenuAccessLevel.VIEW.value,
        "kpi-suggestion-mapping": MenuAccessLevel.VIEW.value,
        "profile": MenuAccessLevel.FULL.value,
        "hr-dashboard": MenuAccessLevel.FULL.value,
    },
    "HR Manager": {
        "company-users": MenuAccessLevel.VIEW.value,
        "departments": MenuAccessLevel.VIEW.value,
        "themes": MenuAccessLevel.VIEW.value,
        "kpis": MenuAccessLevel.VIEW.value,
        "questions": MenuAccessLevel.VIEW.value,
        "challenges": MenuAccessLevel.VIEW.value,
        "sessions": MenuAccessLevel.FULL.value,
        "suggestion-master": MenuAccessLevel.VIEW.value,
        "kpi-suggestion-mapping": MenuAccessLevel.VIEW.value,
        "profile": MenuAccessLevel.FULL.value,
        "hr-dashboard": MenuAccessLevel.FULL.value,
    },
    "Employee": {
        "challenges": MenuAccessLevel.VIEW.value,
        "submissions": MenuAccessLevel.VIEW.value,
        "profile": MenuAccessLevel.FULL.value,
    },
}


ROLE_POLICY_ASSIGNMENTS: dict[str, str] = {
    # Super Admin / Ayumonk Admin are intentionally absent — see PLATFORM_ROLES.
    "Company Admin": "Tenant Access",
    "CXO": "Tenant Access",
    "HR Manager": "Department Access",
    "Employee": "Self Access",
}


DEFAULT_POLICIES = [
    {
        "name": "Global Access",
        "description": "See all tenants",
        "scope": PolicyScope.GLOBAL.value,
        "conditions": {},
    },
    {
        "name": "Tenant Access",
        "description": "See all records within own company",
        "scope": PolicyScope.TENANT.value,
        "conditions": {"tenant_id": "user.tenant_id"},
    },
    {
        "name": "Department Access",
        "description": "See records within own department only",
        "scope": PolicyScope.DEPARTMENT.value,
        "conditions": {
            "tenant_id": "user.tenant_id",
            "department_id": "user.department_id",
        },
    },
    {
        "name": "Self Access",
        "description": "See only own records",
        "scope": PolicyScope.SELF.value,
        "conditions": {
            "tenant_id": "user.tenant_id",
            "user_id": "user.user_id",
        },
    },
]


def access_level_to_permissions(resource: str, access_level: str) -> list[str]:
    templates = ACCESS_LEVEL_PERMISSION_MAP.get(access_level, [])
    return [tpl.format(resource=resource) for tpl in templates]


def is_at_least(actual: str, required: str) -> bool:
    return MENU_ACCESS_LEVEL_RANK.get(actual, 0) >= MENU_ACCESS_LEVEL_RANK.get(required, 0)
