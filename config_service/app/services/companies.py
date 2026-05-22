from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import pandas as pd

from config_service.app.repositories.companies import CompanyRepository
from config_service.app.repositories.company_users import UserRepository as CompanyUserRepository
from config_service.app.models.company import Company
from config_service.app.schemas.companies import (
    CompanyAdminCreateRequest,
    CompanyAdminUpdateRequest,
    CompanyCreateRequest,
    CompanyCreateWithAdminRequest,
    CompanyCreateWithAdminResponse,
    CompanyResponse,
    CompanyUpdateRequest,
)
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.company_users import CompanyUser
from config_service.app.schemas.company_users import CompanyUserResponse
from config_service.app.services.locations import (
    get_location_names,
    get_or_create_location,
)
from authentication_service.app.models.user import User
from authentication_service.app.repositories.user_repo import AuthUserRepository
from config_service.app.core.config import settings
from config_service.app.services.email_client import EmailClient
from config_service.app.core.custom_loggers import get_file_logger

class CompanyService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_file_logger(name="companies_service", prefix="companies_service")
        self.repo = CompanyRepository(db)
        self.company_user_repo = CompanyUserRepository(db)
        self.auth_repo = AuthUserRepository(db)

    async def list_companies(self, skip: int = 0, limit: int = 100) -> list[CompanyResponse]:
        companies = await self.repo.list(skip=skip, limit=limit)
        admin_map = await self._build_company_admin_map([c.id for c in companies])
        location_map = await get_location_names(
            [c.location_id for c in companies], self.db
        )
        results: list[CompanyResponse] = []
        for company in companies:
            resp = CompanyResponse.model_validate(company)
            resp.admin = admin_map.get(company.id)
            resp.location = location_map.get(company.location_id)
            results.append(resp)
        return results

    async def upload_companies_from_excel(self, file) -> dict:
        df = pd.read_excel(file)

        created = 0
        skipped = []

        def clean_str(v):
            if pd.isna(v):
                return None
            return str(v).strip()

        def clean_int(v):
            if pd.isna(v):
                return None
            return int(v)

        for _, row in df.iterrows():
            company_name = clean_str(row.get("company_name"))

            if not company_name:
                continue

            existing = await self.repo.get_by_name(company_name)
            if existing:
                skipped.append(company_name)
                continue

            location_id = await get_or_create_location(
                clean_str(row.get("location")), self.db
            )
            company = Company(
                company_name=company_name,
                industry=clean_str(row.get("industry")),
                size_bucket=clean_str(row.get("size_bucket")),
                email=clean_str(row.get("email")),
                phone=clean_str(row.get("phone")),
                location_id=location_id,
                no_of_employees=clean_int(row.get("no_of_employees"))
            )

            await self.repo.create(company)
            created += 1

        return {
            "created": created,
            "skipped": skipped
        }

    async def get_company(self, company_id) -> CompanyResponse:
        company = await self.repo.get_by_id(company_id)
        if not company:
            raise BusinessException(message="Company not found", status_code=404)
        admin_map = await self._build_company_admin_map([company.id])
        location_map = await get_location_names([company.location_id], self.db)
        resp = CompanyResponse.model_validate(company)
        resp.admin = admin_map.get(company.id)
        resp.location = location_map.get(company.location_id)
        return resp

    async def update_company(self, company_id, payload: CompanyUpdateRequest) -> CompanyResponse:
        company = await self.repo.get_by_id(company_id)
        if not company:
            raise BusinessException(message="Company not found", status_code=404)

        if payload.company_name and payload.company_name != company.company_name:
            existing = await self.repo.get_by_name(payload.company_name)
            if existing and existing.id != company.id:
                raise BusinessException(message="Company name already exists", status_code=409)
            company.company_name = payload.company_name.strip()

        if payload.industry is not None:
            company.industry = payload.industry
        if payload.size_bucket is not None:
            company.size_bucket = payload.size_bucket
        if payload.email is not None:
            company.email = payload.email
        if payload.phone is not None:
            company.phone = payload.phone
        if "location" in payload.model_fields_set:
            company.location_id = await get_or_create_location(
                payload.location, self.db
            )
        if payload.no_of_employees is not None:
            company.no_of_employees = payload.no_of_employees
        if payload.is_active is not None:
            company.is_active = payload.is_active

        company = await self.repo.update(company)

        if payload.admin is not None:
            await self._upsert_company_admin(company, payload.admin)

        admin_map = await self._build_company_admin_map([company.id])
        location_map = await get_location_names([company.location_id], self.db)
        resp = CompanyResponse.model_validate(company)
        resp.admin = admin_map.get(company.id)
        resp.location = location_map.get(company.location_id)
        return resp

    async def delete_company(self, company_id) -> CompanyResponse:
        """Hard-delete a company and every row that references it.

        Cascades through (in order, inside one transaction):
          1. Per-tenant config rows reachable from `companies.id` directly or
             via sessions / kpis / challenges / company_users.
          2. RBAC rows scoped by `tenant_id = company_id` (cross-Base FK).
          3. `company_users` rows + auth `users` rows whose email no longer
             appears in any remaining `company_users` row.
          4. The `companies` row itself.

        Returns the captured CompanyResponse (the row no longer exists in DB).
        """
        company = await self.repo.get_by_id(company_id)
        if not company:
            raise BusinessException(message="Company not found", status_code=404)

        # Capture the response before we wipe the row.
        location_map = await get_location_names([company.location_id], self.db)
        captured = CompanyResponse.model_validate(company)
        captured.location = location_map.get(company.location_id)
        captured.is_active = False

        params = {"cid": company_id, "cid_str": str(company_id)}

        # ---------- Phase 1: leaf data reachable via sessions/kpis/users ----------
        await self.db.execute(
            text(
                "DELETE FROM session_questions "
                "WHERE session_id IN (SELECT id FROM sessions WHERE company_id = :cid)"
            ),
            params,
        )
        await self.db.execute(
            text("DELETE FROM user_challenge_completions WHERE company_id = :cid"),
            params,
        )
        await self.db.execute(
            text(
                "DELETE FROM kpi_suggestion_mappings "
                "WHERE kpi_key IN (SELECT kpi_key FROM kpis WHERE company_id = :cid) "
                "   OR question_key IN (SELECT id FROM kpi_questions WHERE company_id = :cid)"
            ),
            params,
        )
        await self.db.execute(
            text("DELETE FROM kpi_challenges WHERE company_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM kpi_scoring WHERE company_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM kpi_questions WHERE company_id = :cid"), params
        )
        await self.db.execute(
            text(
                "DELETE FROM notifications "
                "WHERE company_id = :cid "
                "   OR user_id IN (SELECT id FROM company_users WHERE company_id = :cid)"
            ),
            params,
        )
        await self.db.execute(
            text(
                "DELETE FROM push_subscriptions "
                "WHERE user_id IN (SELECT id FROM company_users WHERE company_id = :cid)"
            ),
            params,
        )
        await self.db.execute(
            text(
                "DELETE FROM reminder_settings "
                "WHERE user_id IN (SELECT id FROM company_users WHERE company_id = :cid)"
            ),
            params,
        )
        await self.db.execute(
            text("DELETE FROM cxo_metric_kpi_mapping WHERE company_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM cxo_metric_signal_mapping WHERE company_id = :cid"),
            params,
        )
        # NOTE: cxo_metric_master is a global catalog in the live schema
        # (cxo_metrics_up.sql migration). The SQLAlchemy model declares a
        # per-tenant `company_id` column but the migrated DB doesn't have one,
        # so we deliberately do NOT delete from it here. The mappings above
        # are the per-tenant data.

        # ---------- Phase 2: mid-level tenant entities ----------
        await self.db.execute(
            text("DELETE FROM sessions WHERE company_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM kpis WHERE company_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM themes WHERE company_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM challenges WHERE company_id = :cid"), params
        )

        # ---------- Phase 3: RBAC rows scoped to this tenant ----------
        # NB: cross-Base FKs (rbac_3_layer.sql) — these all reference companies.id.
        # role_menus/user_menus/role_permissions/user_permissions and
        # role_policies/user_policies must be cleared before menus/roles/policies.
        await self.db.execute(
            text("DELETE FROM audit_logs WHERE tenant_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM user_menus WHERE tenant_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM role_menus WHERE tenant_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM user_permissions WHERE tenant_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM role_permissions WHERE tenant_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM user_policies WHERE tenant_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM role_policies WHERE tenant_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM policies WHERE tenant_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM menus WHERE tenant_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM roles WHERE tenant_id = :cid"), params
        )

        # ---------- Phase 4: company_users + orphaned auth users ----------
        # employee_form_response.company_id is a free-text String column, so we
        # match by the stringified UUID.
        await self.db.execute(
            text("DELETE FROM employee_form_response WHERE company_id = :cid_str"),
            params,
        )

        emails_result = await self.db.execute(
            text(
                "SELECT DISTINCT email FROM company_users "
                "WHERE company_id = :cid AND email IS NOT NULL"
            ),
            params,
        )
        emails = [row.email for row in emails_result.all()]

        await self.db.execute(
            text("DELETE FROM company_users WHERE company_id = :cid"), params
        )
        await self.db.execute(
            text("DELETE FROM departments WHERE company_id = :cid"), params
        )

        # Now scrub the auth `users` rows whose email no longer appears in any
        # remaining company_users row. user_menus/user_permissions/user_policies
        # rows for those user_ids in OTHER tenants have to go first.
        if emails:
            orphan_ids_result = await self.db.execute(
                text(
                    "SELECT id FROM users "
                    "WHERE email = ANY(:emails) "
                    "  AND NOT EXISTS ("
                    "      SELECT 1 FROM company_users cu WHERE cu.email = users.email"
                    "  )"
                ),
                {"emails": emails},
            )
            orphan_user_ids = [row.id for row in orphan_ids_result.all()]

            if orphan_user_ids:
                user_params = {"uids": orphan_user_ids}
                await self.db.execute(
                    text("DELETE FROM user_menus WHERE user_id = ANY(:uids)"),
                    user_params,
                )
                await self.db.execute(
                    text("DELETE FROM user_permissions WHERE user_id = ANY(:uids)"),
                    user_params,
                )
                await self.db.execute(
                    text("DELETE FROM user_policies WHERE user_id = ANY(:uids)"),
                    user_params,
                )
                await self.db.execute(
                    text("DELETE FROM users WHERE id = ANY(:uids)"), user_params
                )

        # ---------- Phase 5: the company row ----------
        await self.db.execute(
            text("DELETE FROM companies WHERE id = :cid"), params
        )

        await self.db.commit()
        return captured

    async def create_company_with_admin(
        self,
        payload: CompanyCreateWithAdminRequest,
    ) -> CompanyCreateWithAdminResponse:
        existing = await self.repo.get_by_name(payload.company.company_name)
        if existing:
            raise BusinessException(message="Company name already exists", status_code=409)

        location_id = await get_or_create_location(payload.company.location, self.db)
        company = await self.repo.create(
            Company(
                company_name=payload.company.company_name.strip(),
                industry=payload.company.industry,
                size_bucket=payload.company.size_bucket,
                email=payload.company.email,
                phone=payload.company.phone,
                location_id=location_id,
                no_of_employees=payload.company.no_of_employees,
            )
        )
        admin_resp = None
        if payload.admin is not None:
            admin_resp = await self._create_company_admin(company, payload.admin)

        location_map = await get_location_names([company.location_id], self.db)
        company_resp = CompanyResponse.model_validate(company)
        company_resp.location = location_map.get(company.location_id)
        return CompanyCreateWithAdminResponse(
            company=company_resp,
            admin=admin_resp,
        )

    async def assign_company_admin(
        self,
        company_id,
        payload: CompanyAdminCreateRequest,
    ) -> CompanyUserResponse:
        company = await self.repo.get_by_id(company_id)
        if not company:
            raise BusinessException(message="Company not found", status_code=404)

        if not payload.emp_id:
            raise BusinessException(message="emp_id is required for admin", status_code=422)

        existing_username = await self.auth_repo.get_by_username(payload.emp_id)
        if existing_username:
            raise BusinessException(message="Admin emp_id already exists", status_code=409)

        existing_user = await self.company_user_repo.get_by_email(payload.email)
        if existing_user:
            raise BusinessException(message="User email already exists", status_code=409)

        existing_auth_user = await self.auth_repo.get_by_email(payload.email)
        if existing_auth_user:
            raise BusinessException(message="User email already exists", status_code=409)

        admin_user = await self.company_user_repo.create(
            CompanyUser(
                emp_id=payload.emp_id,
                full_name=payload.full_name,
                department=payload.department,
                department_id=payload.department_id,
                role_id=payload.role_id,
                gender=payload.gender,
                phone=payload.phone,
                age_band=payload.age_band,
                email=payload.email,
                company_id=company.id,
                is_active=payload.is_active,
            )
        )

        auth_user = User(
            username=payload.emp_id,
            email=payload.email,
            hashed_password=payload.password,
            role=payload.role_name or "ADMIN",
            is_active=payload.is_active,
        )
        await self.auth_repo.create(auth_user)

        await self._send_admin_credentials_email(
            email=payload.email,
            username=payload.emp_id,
            password=payload.password,
        )

        resp = CompanyUserResponse.model_validate(admin_user)
        resp.username = auth_user.username
        resp.password = auth_user.hashed_password
        return resp

    async def _build_company_admin_map(self, company_ids: list) -> dict:
        if not company_ids:
            return {}
        company_users = await self.company_user_repo.list_by_company_ids(company_ids)
        email_map = {}
        for cu in company_users:
            if cu.email:
                email_map.setdefault(cu.company_id, []).append(cu)
        all_emails = [cu.email for cu in company_users if cu.email]
        auth_admins = await self.auth_repo.list_by_emails_and_role(all_emails, "ADMIN")
        admin_email_set = {u.email for u in auth_admins}
        auth_map = {u.email: u for u in auth_admins}

        result = {}
        for company_id, users in email_map.items():
            admins = [u for u in users if u.email in admin_email_set]
            if not admins:
                result[company_id] = None
                continue
            admins.sort(key=lambda u: u.created_at or u.updated_at, reverse=True)
            resp = CompanyUserResponse.model_validate(admins[0])
            auth_user = auth_map.get(resp.email)
            if auth_user:
                resp.username = auth_user.username
                resp.password = auth_user.hashed_password
            result[company_id] = resp
        return result

    async def _create_company_admin(
        self,
        company: Company,
        payload: CompanyAdminCreateRequest,
    ) -> CompanyUserResponse:
        if not payload.emp_id:
            raise BusinessException(message="emp_id is required for admin", status_code=422)

        existing_username = await self.auth_repo.get_by_username(payload.emp_id)
        if existing_username:
            raise BusinessException(message="Admin emp_id already exists", status_code=409)

        existing_user = await self.company_user_repo.get_by_email(payload.email)
        if existing_user:
            raise BusinessException(message="User email already exists", status_code=409)

        existing_auth_user = await self.auth_repo.get_by_email(payload.email)
        if existing_auth_user:
            raise BusinessException(message="User email already exists", status_code=409)

        admin_user = await self.company_user_repo.create(
            CompanyUser(
                emp_id=payload.emp_id,
                full_name=payload.full_name,
                department=payload.department,
                department_id=payload.department_id,
                role_id=payload.role_id,
                gender=payload.gender,
                phone=payload.phone,
                age_band=payload.age_band,
                email=payload.email,
                company_id=company.id,
                is_active=payload.is_active,
            )
        )

        auth_user = User(
            username=payload.emp_id,
            email=payload.email,
            hashed_password=payload.password,
            role=payload.role_name or "ADMIN",
            is_active=payload.is_active,
        )
        await self.auth_repo.create(auth_user)

        await self._send_admin_credentials_email(
            email=payload.email,
            username=payload.emp_id,
            password=payload.password,
        )

        resp = CompanyUserResponse.model_validate(admin_user)
        resp.username = auth_user.username
        resp.password = auth_user.hashed_password
        return resp

    async def _upsert_company_admin(
        self,
        company: Company,
        payload: CompanyAdminUpdateRequest,
    ) -> CompanyUserResponse:
        admin_map = await self._build_company_admin_map([company.id])
        existing_admin = admin_map.get(company.id)

        if existing_admin is None:
            if not (payload.email and payload.password and payload.emp_id):
                raise BusinessException(
                    message="admin email, emp_id, and password are required to create admin",
                    status_code=422,
                )
            return await self._create_company_admin(
                company,
                CompanyAdminCreateRequest(
                    username=payload.username,
                    email=payload.email,
                    password=payload.password,
                    emp_id=payload.emp_id,
                    full_name=payload.full_name,
                    department=payload.department,
                    department_id=payload.department_id,
                    role_id=payload.role_id,
                    role_name=payload.role_name,
                    gender=payload.gender,
                    phone=payload.phone,
                    age_band=payload.age_band,
                    is_active=payload.is_active if payload.is_active is not None else True,
                ),
            )

        company_user = await self.company_user_repo.get_by_email(existing_admin.email)
        if not company_user:
            raise BusinessException(message="Company admin not found", status_code=404)

        new_email = payload.email or company_user.email
        if payload.email and payload.email != company_user.email:
            existing_company_user = await self.company_user_repo.get_by_email(payload.email)
            if existing_company_user:
                raise BusinessException(message="User email already exists", status_code=409)

            existing_auth_user = await self.auth_repo.get_by_email(payload.email)
            if existing_auth_user:
                raise BusinessException(message="User email already exists", status_code=409)

            company_user.email = payload.email

        if payload.emp_id is not None:
            company_user.emp_id = payload.emp_id
        if payload.full_name is not None:
            company_user.full_name = payload.full_name
        if payload.department is not None:
            company_user.department = payload.department
        if payload.department_id is not None:
            company_user.department_id = payload.department_id
        if payload.role_id is not None:
            company_user.role_id = payload.role_id
        if payload.gender is not None:
            company_user.gender = payload.gender
        if payload.phone is not None:
            company_user.phone = payload.phone
        if payload.age_band is not None:
            company_user.age_band = payload.age_band
        if payload.is_active is not None:
            company_user.is_active = payload.is_active

        await self.company_user_repo.update(company_user)

        auth_user = await self.auth_repo.get_by_email(existing_admin.email)
        if not auth_user:
            raise BusinessException(message="Admin auth user not found", status_code=404)

        if payload.emp_id is not None:
            auth_user.username = payload.emp_id
        if payload.password is not None:
            auth_user.hashed_password = payload.password
        if payload.is_active is not None:
            auth_user.is_active = payload.is_active
        if payload.email and payload.email != existing_admin.email:
            auth_user.email = new_email
        if payload.role_name is not None:
            auth_user.role = payload.role_name

        await self.auth_repo.update(auth_user)

        return CompanyUserResponse.model_validate(company_user)

    async def _send_admin_credentials_email(self, *, email: str, username: str, password: str) -> None:
        if not settings.EMAIL_SERVICE_URL:
            return
        subject = "Your Admin Account Credentials"
        body = (
            "Hello,\n\n"
            "Your admin account has been created.\n"
            f"Username: {username}\n"
            f"Password: {password}\n"
            f"Email: {email}\n\n"
            "Please login and change your password after first login."
        )
        client = EmailClient()
        try:
            await client.send_email(to=[email], subject=subject, body=body, html=False)
        except BusinessException as exc:
            self.logger.warning(
                "EMAIL_FAILED | admin_credentials | email=%s | error=%s",
                email,
                str(exc),
            )

