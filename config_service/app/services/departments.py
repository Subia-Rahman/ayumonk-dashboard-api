from typing import Optional
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.core.custom_loggers import get_file_logger
from config_service.app.models.department import Department
from config_service.app.repositories.companies import CompanyRepository
from config_service.app.repositories.departments import DepartmentRepository
from config_service.app.schemas.departments import (
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
)


class DepartmentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.logger = get_file_logger(
            name="departments_service", prefix="departments_service"
        )
        self.repo = DepartmentRepository(db)
        self.company_repo = CompanyRepository(db)

    @staticmethod
    def _clean_name(raw: str) -> str:
        cleaned = " ".join((raw or "").split())
        if not cleaned:
            raise BusinessException(message="name is required", status_code=422)
        return cleaned

    async def _ensure_company_exists(self, company_id: UUID) -> None:
        company = await self.company_repo.get_by_id(company_id)
        if not company:
            raise BusinessException(message="Company not found", status_code=404)

    async def list(
        self,
        company_id: UUID,
        *,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
        is_active: Optional[bool] = True,
    ) -> tuple[list[DepartmentResponse], int]:
        await self._ensure_company_exists(company_id)
        items, total = await self.repo.list_by_company_paginated(
            company_id,
            skip=skip,
            limit=limit,
            search=search,
            is_active=is_active,
        )
        return [DepartmentResponse.model_validate(d) for d in items], total

    async def get(self, dept_id: UUID, company_id: UUID) -> DepartmentResponse:
        dept = await self.repo.get_by_id(dept_id, company_id=company_id)
        if not dept:
            raise BusinessException(message="Department not found", status_code=404)
        return DepartmentResponse.model_validate(dept)

    async def create(self, payload: DepartmentCreate) -> DepartmentResponse:
        await self._ensure_company_exists(payload.company_id)
        name = self._clean_name(payload.name)

        existing = await self.repo.get_by_name(name, payload.company_id)
        if existing:
            raise BusinessException(
                message="Department name already exists for this company",
                status_code=409,
            )

        dept = Department(
            name=name,
            description=payload.description,
            company_id=payload.company_id,
        )
        try:
            dept = await self.repo.create(dept)
        except IntegrityError as exc:
            await self.db.rollback()
            self._raise_duplicate(exc)
        return DepartmentResponse.model_validate(dept)

    async def update(
        self,
        dept_id: UUID,
        payload: DepartmentUpdate,
        company_id: UUID,
    ) -> DepartmentResponse:
        dept = await self.repo.get_by_id(dept_id, company_id=company_id)
        if not dept:
            raise BusinessException(message="Department not found", status_code=404)

        if "name" in payload.model_fields_set and payload.name is not None:
            new_name = self._clean_name(payload.name)
            if new_name.lower() != dept.name.lower():
                conflict = await self.repo.get_by_name(new_name, company_id)
                if conflict and conflict.id != dept.id:
                    raise BusinessException(
                        message="Department name already exists for this company",
                        status_code=409,
                    )
            dept.name = new_name

        if "description" in payload.model_fields_set:
            dept.description = payload.description

        if "is_active" in payload.model_fields_set and payload.is_active is not None:
            dept.is_active = payload.is_active

        try:
            dept = await self.repo.update(dept)
        except IntegrityError as exc:
            await self.db.rollback()
            self._raise_duplicate(exc)
        return DepartmentResponse.model_validate(dept)

    async def delete(self, dept_id: UUID, company_id: UUID) -> DepartmentResponse:
        dept = await self.repo.get_by_id(dept_id, company_id=company_id)
        if not dept:
            raise BusinessException(message="Department not found", status_code=404)

        dept.is_active = False
        dept.is_deleted = True
        dept = await self.repo.update(dept)
        return DepartmentResponse.model_validate(dept)

    @staticmethod
    def _raise_duplicate(exc: IntegrityError) -> None:
        text = str(exc.orig) if exc.orig else str(exc)
        if "uq_departments_company_name_active" in text:
            raise BusinessException(
                message="Department name already exists for this company",
                status_code=409,
            ) from exc
        raise exc
