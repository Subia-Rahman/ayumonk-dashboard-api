from __future__ import annotations
"""Static defaults seeded into every new company.

These constants are the data-only definition of what RBAC rows a newly
created tenant must have (roles, role-menu access, role-permission grants,
per-tenant policies and role-policy assignments). They were captured from
the canonical reference tenant and are intentionally frozen here so company
creation does not depend on any other company's data living in the DB.

ID fields (role_id, menu_id, permission_id, policy_id) are NEVER hardcoded:
- menus and permissions are global catalogs looked up by slug / codename at
  seed time.
- roles and policies are created fresh per tenant; their generated integer
  ids are mapped by name inside the seeder.
"""


DEFAULT_ROLES: list[dict] = [
    {"name": "Company Admin", "is_active": True},
    {"name": "Employee", "is_active": True},
    {"name": "HR Manager", "is_active": True},
    {"name": "CXO", "is_active": True},
]


DEFAULT_POLICIES: list[dict] = [
    {
        "name": "Tenant Access",
        "description": "See all records within own company",
        "module": "global",
        "scope": "tenant",
        "conditions": {"tenant_id": "user.tenant_id"},
        "effect": "allow",
        "is_active": True,
    },
    {
        "name": "Self Access",
        "description": "See only own records",
        "module": "global",
        "scope": "self",
        "conditions": {"tenant_id": "user.tenant_id", "user_id": "user.user_id"},
        "effect": "allow",
        "is_active": True,
    },
    {
        "name": "Department Access",
        "description": "See records within own department only",
        "module": "global",
        "scope": "department",
        "conditions": {
            "tenant_id": "user.tenant_id",
            "department_id": "user.department_id",
        },
        "effect": "allow",
        "is_active": True,
    },
    {
        "name": "Global Access",
        "description": "See all tenants",
        "module": "global",
        "scope": "global",
        "conditions": {},
        "effect": "allow",
        "is_active": True,
    },
]


DEFAULT_ROLE_MENUS: dict[str, list[dict]] = {
    "Company Admin": [
        {"menu_slug": "dashboard", "access_level": "view"},
        {"menu_slug": "company-data", "access_level": "view"},
        {"menu_slug": "company-users", "access_level": "full"},
        {"menu_slug": "kpis", "access_level": "full"},
        {"menu_slug": "profile", "access_level": "full"},
    ],
    "Employee": [
        {"menu_slug": "challenges", "access_level": "view"},
        {"menu_slug": "profile", "access_level": "full"},
        {"menu_slug": "user-dashboard", "access_level": "full"},
        {"menu_slug": "submissions", "access_level": "full"},
    ],
    "HR Manager": [
        {"menu_slug": "company-data", "access_level": "view"},
        {"menu_slug": "company-users", "access_level": "view"},
        {"menu_slug": "profile", "access_level": "full"},
        {"menu_slug": "hr-dashboard", "access_level": "full"},
    ],
    "CXO": [
        {"menu_slug": "company-data", "access_level": "view"},
        {"menu_slug": "company-users", "access_level": "view"},
        {"menu_slug": "profile", "access_level": "full"},
        {"menu_slug": "hr-dashboard", "access_level": "full"},
    ],
}


def _crud(resource: str) -> list[dict]:
    return [
        {"codename": f"{resource}:read", "is_override": False, "is_granted": True},
        {"codename": f"{resource}:create", "is_override": False, "is_granted": True},
        {"codename": f"{resource}:update", "is_override": False, "is_granted": True},
        {"codename": f"{resource}:delete", "is_override": False, "is_granted": True},
    ]


def _read_only(resource: str) -> dict:
    return {"codename": f"{resource}:read", "is_override": False, "is_granted": True}


DEFAULT_ROLE_PERMISSIONS: dict[str, list[dict]] = {
    "Company Admin": (
        _crud("company_master")
        + _crud("company_users")
        + _crud("themes")
        + _crud("kpis")
        + _crud("challenges")
        + _crud("sessions")
        + _crud("suggestion")
        + _crud("platform")
        + _crud("departments")
    ),
    "Employee": [
        _read_only("challenges"),
        _read_only("sessions"),
        *_crud("platform"),
    ],
    "HR Manager": [
        _read_only("company_users"),
        _read_only("themes"),
        _read_only("kpis"),
        _read_only("challenges"),
        *_crud("sessions"),
        _read_only("suggestion"),
        *_crud("platform"),
        _read_only("departments"),
        *_crud("hr_dashboard"),
    ],
    "CXO": [
        _read_only("company_master"),
        _read_only("company_users"),
        _read_only("themes"),
        _read_only("kpis"),
        _read_only("challenges"),
        _read_only("sessions"),
        _read_only("suggestion"),
        *_crud("platform"),
        _read_only("departments"),
        *_crud("hr_dashboard"),
    ],
}


DEFAULT_ROLE_POLICIES: dict[str, list[str]] = {
    "Company Admin": ["Tenant Access"],
    "Employee": ["Self Access"],
    "HR Manager": ["Department Access"],
    "CXO": ["Tenant Access"],
}


# Per-user default assignments. The reference tenant has zero rows in each of
# these tables, so no default rows are produced at company creation time.
# Each per-user table is populated when an actual user is created/assigned
# downstream (e.g. via user_menus / user_permissions admin APIs).
DEFAULT_USER_MENUS: list[dict] = []
DEFAULT_USER_POLICIES: list[dict] = []
DEFAULT_USER_PERMISSIONS: list[dict] = []
