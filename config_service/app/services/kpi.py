from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.kpi import KPI
from config_service.app.schemas.kpi import (
    KPICreateRequest,
    KPIListResponse,
    KPIResponse,
    KPIUpdateRequest,
)


class KPIService:
    def __init__(self, repo):
        self.repo = repo

    async def create(self, payload: KPICreateRequest) -> KPIResponse:
        existing = await self.repo.get_by_name(payload.display_name)
        if existing:
            raise BusinessException(message="KPI name already exists", status_code=409)

        kpi = await self.repo.create(
            KPI(
                display_name=payload.display_name,
                theme_key=payload.theme_key,
                start_date=payload.start_date,
                end_date=payload.end_date,
                domain_category=payload.domain_category,
                wi_weight=payload.wi_weight,
            )
        )
        return self._to_response(kpi)

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        theme_key=None,
        search: str | None = None,
        is_active: bool | None = True,
    ) -> KPIListResponse:
        items, total = await self.repo.list(
            skip=skip,
            limit=limit,
            theme_key=theme_key,
            search=search,
            is_active=is_active,
        )
        return KPIListResponse(
            items=[self._to_response(item) for item in items],
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get(self, kpi_key) -> KPIResponse:
        kpi = await self.repo.get_by_id(kpi_key)
        if not kpi:
            raise BusinessException(message="KPI not found", status_code=404)
        return self._to_response(kpi)

    async def update(self, kpi_key, payload: KPIUpdateRequest) -> KPIResponse:
        kpi = await self.repo.get_by_id(kpi_key)
        if not kpi:
            raise BusinessException(message="KPI not found", status_code=404)

        if payload.display_name and payload.display_name != kpi.display_name:
            existing = await self.repo.get_by_name(payload.display_name)
            if existing and existing.kpi_key != kpi.kpi_key:
                raise BusinessException(message="KPI name already exists", status_code=409)
            kpi.display_name = payload.display_name

        if payload.theme_key:
            kpi.theme_key = payload.theme_key

        if payload.start_date is not None:
            kpi.start_date = payload.start_date
        if payload.end_date is not None:
            kpi.end_date = payload.end_date
        if payload.domain_category is not None:
            kpi.domain_category = payload.domain_category
        if payload.wi_weight is not None:
            kpi.wi_weight = payload.wi_weight

        if payload.is_active is not None:
            kpi.is_active = payload.is_active

        if kpi.start_date and kpi.end_date and kpi.start_date > kpi.end_date:
            raise BusinessException(message="start_date cannot be greater than end_date", status_code=400)

        kpi = await self.repo.update(kpi)
        return self._to_response(kpi)

    async def delete(self, kpi_key) -> KPIResponse:
        kpi = await self.repo.get_by_id(kpi_key)
        if not kpi:
            raise BusinessException(message="KPI not found", status_code=404)

        kpi.is_active = False
        kpi = await self.repo.update(kpi)
        return self._to_response(kpi)

    @staticmethod
    def _to_response(kpi: KPI) -> KPIResponse:
        return KPIResponse(
            kpi_key=kpi.kpi_key,
            display_name=kpi.display_name,
            theme_key=kpi.theme_key,
            start_date=kpi.start_date,
            end_date=kpi.end_date,
            domain_category=kpi.domain_category,
            wi_weight=float(kpi.wi_weight) if kpi.wi_weight is not None else None,
            is_active=bool(kpi.is_active),
            created_at=kpi.created_at,
            updated_at=kpi.updated_at,
        )
