import secrets
import string

from authentication_service.app.core.security import hash_password
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import pandas as pd

from authentication_service.app.models.user import User
from authentication_service.app.repositories.user_repo import AuthUserRepository
from config_service.app.core.config import settings
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.repositories.company_users import UserRepository
from config_service.app.repositories.companies import CompanyRepository
from config_service.app.models.company_users import CompanyUser
from config_service.app.schemas.company_users import (
    ALLOWED_AGE_BANDS,
    CompanyUserCreateRequest,
    CompanyUserListResponse,
    CompanyUserResponse,
    CompanyUserUpdateRequest,
)
from config_service.app.core.business_exceptions import BusinessException
from config_service.app.services.email_client import EmailClient

class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_file_logger(name="company_users_service", prefix="company_users_service")
        self.repo = UserRepository(db)
        self.company_repo = CompanyRepository(db)
        self.auth_repo = AuthUserRepository(db)  # for users table

    async def upload_users_from_excel(self, file) -> dict:
        df = pd.read_excel(file)

        created = 0
        errors = []
        warnings = []

        def clean_str(v):
            if pd.isna(v):
                return None
            value = str(v).strip()
            return value or None

        def clean_age_band(v):
            value = clean_str(v)
            if value is None:
                return None
            if value not in ALLOWED_AGE_BANDS:
                raise ValueError(f"age_band must be one of {sorted(ALLOWED_AGE_BANDS)}")
            return value

        for idx, row in df.iterrows():
            company_name = clean_str(row.get("company_name"))
            email = clean_str(row.get("email"))

            if not company_name or not email:
                errors.append({
                    "row": idx,
                    "error": "Missing company_name or email"
                })
                continue

            try:
                age_band = clean_age_band(row.get("age_band"))
            except ValueError as exc:
                errors.append({
                    "row": idx,
                    "error": str(exc),
                })
                continue

            company = await self.company_repo.get_by_name(company_name)
            if not company:
                errors.append({
                    "row": idx,
                    "error": "Company not found",
                    "company": company_name
                })
                continue

            existing_email = await self.repo.get_by_email_and_company(company.id, email)
            if existing_email:
                errors.append({
                    "row": idx,
                    "error": "Email ID already exists.",
                    "company": company_name,
                    "email": email,
                })
                continue

            emp_id = clean_str(row.get("employee_id"))
            if emp_id:
                existing_emp_id = await self.repo.get_by_emp_id_and_company(company.id, emp_id)
                if existing_emp_id:
                    errors.append({
                        "row": idx,
                        "error": "Employee ID already exists.",
                        "company": company_name,
                        "emp_id": emp_id,
                    })
                    continue

            desired_username = emp_id or email
            existing_auth_user = await self.auth_repo.get_by_username(desired_username)
            if existing_auth_user:
                errors.append({
                    "row": idx,
                    "error": "Username already exists",
                    "username": desired_username,
                })
                continue

            user = CompanyUser(
                emp_id=emp_id,
                full_name=clean_str(row.get("full_name")),
                department=clean_str(row.get("department")),
                location=clean_str(row.get("location")),
                gender=clean_str(row.get("gender")),
                phone=clean_str(row.get("phone")),
                age_band=age_band,
                email=email,
                company_id=company.id
            )

            await self.repo.create(user)

            warning_message = await self._provision_auth_user_and_send_email(
                user_name=user.full_name or desired_username,
                username=desired_username,
                email=email,
                company_id=company.id,
                company_name=getattr(company, "company_name", None),
            )
            if warning_message:
                warnings.append({
                    "row": idx,
                    "email": email,
                    "warning": warning_message,
                })
            created += 1

        return {
            "created": created,
            "errors": errors,
            "warnings": warnings,
        }

    async def create_user(self, payload: CompanyUserCreateRequest) -> tuple[CompanyUserResponse, str | None]:
        company = await self.company_repo.get_by_id(payload.company_id)
        if not company:
            raise BusinessException(message="Company not found", status_code=404)

        await self._validate_company_user_uniqueness(
            company_id=payload.company_id,
            email=payload.email,
            emp_id=payload.emp_id,
        )

        try:
            user = await self.repo.create(
                CompanyUser(
                    emp_id=payload.emp_id,
                    full_name=payload.full_name,
                    department=payload.department,
                    location=payload.location,
                    gender=payload.gender,
                    phone=payload.phone,
                    age_band=payload.age_band,
                    email=payload.email,
                    company_id=payload.company_id,
                )
            )
        except IntegrityError as e:
            await self.db.rollback()
            self._raise_duplicate_business_exception(e)

        warning_message = await self._provision_auth_user_and_send_email(
            user_name=payload.full_name or (payload.emp_id or payload.email),
            username=payload.emp_id or payload.email,
            email=payload.email,
            company_id=payload.company_id,
            company_name=getattr(company, "company_name", None),
        )
        if warning_message:
            warning_message = "User created successfully, but failed to send email."

        return CompanyUserResponse.model_validate(user), warning_message

    async def list_users(
        self,
        *,
        skip: int,
        limit: int,
        company_id=None,
        search: str | None = None,
        is_active: bool | None = True,
    ) -> CompanyUserListResponse:
        items, total = await self.repo.list(
            skip=skip,
            limit=limit,
            company_id=company_id,
            search=search,
            is_active=is_active,
        )
        return CompanyUserListResponse(
            items=[CompanyUserResponse.model_validate(item) for item in items],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get_user(self, user_id) -> CompanyUserResponse:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise BusinessException(message="Company user not found", status_code=404)
        return CompanyUserResponse.model_validate(user)

    async def update_user(self, user_id, payload: CompanyUserUpdateRequest) -> CompanyUserResponse:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise BusinessException(message="Company user not found", status_code=404)

        target_company_id = payload.company_id if payload.company_id is not None else user.company_id
        if payload.company_id is not None:
            company = await self.company_repo.get_by_id(target_company_id)
            if not company:
                raise BusinessException(message="Company not found", status_code=404)

        target_email = payload.email if payload.email is not None else user.email
        target_emp_id = payload.emp_id if payload.emp_id is not None else user.emp_id

        await self._validate_company_user_uniqueness(
            company_id=target_company_id,
            email=target_email,
            emp_id=target_emp_id,
            exclude_user_id=user.id,
        )

        if payload.email is not None:
            user.email = payload.email

        if payload.company_id is not None:
            user.company_id = payload.company_id

        if payload.emp_id is not None:
            user.emp_id = payload.emp_id
        if payload.full_name is not None:
            user.full_name = payload.full_name
        if payload.department is not None:
            user.department = payload.department
        if payload.location is not None:
            user.location = payload.location
        if payload.gender is not None:
            user.gender = payload.gender
        if payload.phone is not None:
            user.phone = payload.phone
        if payload.age_band is not None:
            user.age_band = payload.age_band
        if payload.is_active is not None:
            user.is_active = payload.is_active

        try:
            user = await self.repo.update(user)
        except IntegrityError as e:
            await self.db.rollback()
            self._raise_duplicate_business_exception(e)

        return CompanyUserResponse.model_validate(user)

    async def delete_user(self, user_id) -> CompanyUserResponse:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise BusinessException(message="Company user not found", status_code=404)

        user.is_active = False
        user.is_deleted = True
        user = await self.repo.update(user)
        return CompanyUserResponse.model_validate(user)

    async def _validate_company_user_uniqueness(
        self,
        *,
        company_id,
        email: str,
        emp_id: str | None,
        exclude_user_id=None,
    ) -> None:
        existing_email = await self.repo.get_by_email_and_company(company_id, email)
        if existing_email and existing_email.id != exclude_user_id:
            raise BusinessException(message="Email ID already exists.", status_code=409)

        if emp_id:
            existing_emp_id = await self.repo.get_by_emp_id_and_company(company_id, emp_id)
            if existing_emp_id and existing_emp_id.id != exclude_user_id:
                raise BusinessException(message="Employee ID already exists.", status_code=409)

    def _raise_duplicate_business_exception(self, exc: IntegrityError) -> None:
        error_text = str(exc.orig) if exc.orig else str(exc)
        if "uq_company_users_company_emp_id_active" in error_text:
            raise BusinessException(message="Employee ID already exists.", status_code=409) from exc
        if (
            "uq_company_users_company_email_active" in error_text
            or "company_users_email_key" in error_text
        ):
            raise BusinessException(message="Email ID already exists.", status_code=409) from exc
        raise exc

    def _generate_secure_password(self, length: int = 12) -> str:
        if length < 8:
            length = 8
        if length > 12:
            length = 12

        rng = secrets.SystemRandom()
        uppercase = string.ascii_uppercase
        lowercase = string.ascii_lowercase
        digits = string.digits
        special = "!@#$%^&*()-_=+[]{}"

        password_chars = [
            rng.choice(uppercase),
            rng.choice(lowercase),
            rng.choice(digits),
            rng.choice(special),
        ]
        all_chars = uppercase + lowercase + digits + special
        password_chars.extend(rng.choice(all_chars) for _ in range(length - len(password_chars)))
        rng.shuffle(password_chars)
        return "".join(password_chars)

    async def _provision_auth_user_and_send_email(
        self,
        *,
        user_name: str,
        username: str,
        email: str,
        company_id,
        company_name: str | None = None,
    ) -> str | None:
        existing_auth_user = await self.auth_repo.get_by_email(email)
        if existing_auth_user:
            return None

        existing_username = await self.auth_repo.get_by_username(username)
        if existing_username:
            raise BusinessException(message="Username already exists", status_code=409)

        plain_password = self._generate_secure_password()
        auth_user = User(
            username=username,
            email=email,
            hashed_password=hash_password(plain_password),
            role="USER",
            is_active=True,
        )
        await self.auth_repo.create(auth_user)

        try:
            await self._send_user_credentials_email(
                user_name=user_name,
                username=username,
                email=email,
                password=plain_password,
                company_name=company_name,
            )
            return None
        except BusinessException as exc:
            self.logger.warning(
                "EMAIL_FAILED | user_credentials | email=%s | company_id=%s | error=%s",
                email,
                str(company_id),
                exc.message,
            )
            return "User created successfully, but failed to send email."

    async def _send_user_credentials_email(
        self,
        *,
        user_name: str,
        username: str,
        email: str,
        password: str,
        company_name: str | None = None,
    ) -> None:
        login_url = self._build_login_url()
        subject = "Your Account Credentials"
        body_lines = [
            f"Hello {user_name},",
            "",
            "Your user account has been created successfully.",
        ]
        if company_name:
            body_lines.append(f"Company: {company_name}")
        body_lines.extend(
            [
                f"Login Email: {email}",
                f"Login Username: {username}",
                f"Generated Password: {password}",
            ]
        )
        if login_url:
            body_lines.extend(["", f"Login URL: {login_url}"])
        body_lines.extend(["", "Please login and change your password after first login."])

        client = EmailClient()
        await client.send_email(
            to=[email],
            subject=subject,
            body="\n".join(body_lines),
            html=False,
        )

    def _build_login_url(self) -> str | None:
        base_url = (settings.FRONTEND_BASE_URL or "").strip()
        if not base_url:
            return None
        return base_url.rstrip("/")
