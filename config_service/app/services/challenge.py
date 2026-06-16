from __future__ import annotations
from datetime import date
from uuid import UUID

from config_service.app.core.business_exceptions import BusinessException
from config_service.app.models.challenge import Challenge
from config_service.app.models.kpi_challenge import KPIChallenge
from config_service.app.repositories.kpi import KPIRepository
from config_service.app.repositories.kpi_challenge import KPIChallengeRepository
from config_service.app.schemas.challenge import (
    ChallengeCreateRequest,
    ChallengeDetailResponse,
    ChallengeKPIMappingRequest,
    ChallengeKPIMappingResponse,
    ChallengeListResponse,
    ChallengeResponse,
    ChallengeUpdateRequest,
    KPIChallengeActiveResponse,
    KPIChallengeUpdateRequest,
)


class ChallengeService:
    def __init__(self, challenge_repo, kpi_repo, kpi_challenge_repo):
        self.challenge_repo = challenge_repo
        self.kpi_repo = kpi_repo
        self.kpi_challenge_repo = kpi_challenge_repo

    async def create(self, payload: ChallengeCreateRequest) -> ChallengeDetailResponse:
        existing = await self.challenge_repo.get_by_name_ci(payload.name, payload.company_id)
        if existing:
            raise BusinessException(message="Challenge name already exists", status_code=409)

        challenge = await self.challenge_repo.create(
            Challenge(
                company_id=payload.company_id,
                name=payload.name,
                description=payload.description,
                challenge_type=payload.challenge_type,
                target_value=payload.target_value,
                xp_reward=payload.xp_reward,
                icon=payload.icon,
                is_daily=payload.is_daily,
                options=payload.options,
            )
        )

        mappings = []
        if payload.kpi_mappings:
            mappings = await self._create_mappings(
                challenge.challenge_key,
                payload.kpi_mappings,
                company_id=challenge.company_id,
            )

        start_date, end_date = self._compute_date_range(mappings)
        kpi_keys = self._compute_kpi_keys(mappings)
        return ChallengeDetailResponse(
            challenge=self._to_response(
                challenge,
                start_date=start_date,
                end_date=end_date,
                kpi_keys=kpi_keys,
            ),
            kpi_mappings=[self._to_mapping_response(m) for m in mappings],
        )

    async def list(
        self,
        *,
        skip: int,
        limit: int,
        company_id: UUID | None = None,
        search: str | None,
        is_active: bool | None,
        kpi_key=None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> ChallengeListResponse:
        items, total = await self.challenge_repo.list(
            skip=skip,
            limit=limit,
            company_id=company_id,
            search=search,
            is_active=is_active,
            kpi_key=kpi_key,
            start_date=start_date,
            end_date=end_date,
        )
        responses = []
        for item in items:
            mappings = await self.kpi_challenge_repo.list_by_challenge(item.challenge_key)
            sd, ed = self._compute_date_range(mappings)
            kpi_keys = self._compute_kpi_keys(mappings)
            responses.append(self._to_response(item, start_date=sd, end_date=ed, kpi_keys=kpi_keys))
        return ChallengeListResponse(
            items=responses,
            total=total,
            skip=skip,
            limit=limit,
        )

    async def get(self, challenge_key, company_id: UUID | None = None) -> ChallengeDetailResponse:
        challenge = await self.challenge_repo.get_by_id(challenge_key, company_id)
        if not challenge:
            raise BusinessException(message="Challenge not found", status_code=404)

        mappings = await self.kpi_challenge_repo.list_by_challenge(challenge_key)
        start_date, end_date = self._compute_date_range(mappings)
        kpi_keys = self._compute_kpi_keys(mappings)
        return ChallengeDetailResponse(
            challenge=self._to_response(
                challenge,
                start_date=start_date,
                end_date=end_date,
                kpi_keys=kpi_keys,
            ),
            kpi_mappings=[self._to_mapping_response(m) for m in mappings],
        )

    async def update(self, challenge_key, payload: ChallengeUpdateRequest, company_id: UUID | None = None) -> ChallengeResponse:
        challenge = await self.challenge_repo.get_by_id(challenge_key, company_id)
        if not challenge:
            raise BusinessException(message="Challenge not found", status_code=404)

        if payload.name and payload.name != challenge.name:
            existing = await self.challenge_repo.get_by_name_ci(payload.name, challenge.company_id)
            if existing and existing.challenge_key != challenge.challenge_key:
                raise BusinessException(message="Challenge name already exists", status_code=409)
            challenge.name = payload.name

        if payload.description is not None:
            challenge.description = payload.description
        if payload.challenge_type is not None:
            challenge.challenge_type = payload.challenge_type
        if payload.target_value is not None:
            challenge.target_value = payload.target_value
        if payload.xp_reward is not None:
            challenge.xp_reward = payload.xp_reward
        if payload.icon is not None:
            challenge.icon = payload.icon
        if payload.is_daily is not None:
            challenge.is_daily = payload.is_daily
        if payload.is_active is not None:
            challenge.is_active = payload.is_active
        if payload.options is not None:
            challenge.options = payload.options

        # Final type/field consistency pass. The resolved type may be from the
        # payload or the unchanged DB value; either way we keep target_value
        # NULL for toggle/rating and require options for multi/choice.
        effective_type = (challenge.challenge_type or "").lower()
        if effective_type in {"toggle", "rating"}:
            challenge.target_value = None
            challenge.options = None
        elif effective_type in {"multi", "choice"}:
            if not challenge.options:
                raise BusinessException(
                    message=f"options is required for '{effective_type}' challenges",
                    status_code=422,
                )
        else:
            # Counter/timer never carry options.
            challenge.options = None

        challenge = await self.challenge_repo.update(challenge)
        mappings = await self.kpi_challenge_repo.list_by_challenge(challenge_key)
        start_date, end_date = self._compute_date_range(mappings)
        kpi_keys = self._compute_kpi_keys(mappings)
        return self._to_response(challenge, start_date=start_date, end_date=end_date, kpi_keys=kpi_keys)

    async def delete(self, challenge_key, company_id: UUID | None = None) -> ChallengeResponse:
        challenge = await self.challenge_repo.get_by_id(challenge_key, company_id)
        if not challenge:
            raise BusinessException(message="Challenge not found", status_code=404)

        mappings = await self.kpi_challenge_repo.list_by_challenge(challenge_key)
        start_date, end_date = self._compute_date_range(mappings)
        kpi_keys = self._compute_kpi_keys(mappings)

        for mapping in mappings:
            await self.kpi_challenge_repo.soft_delete(mapping)

        challenge.is_active = False
        challenge.is_deleted = True
        challenge = await self.challenge_repo.update(challenge)
        return self._to_response(challenge, start_date=start_date, end_date=end_date, kpi_keys=kpi_keys)

    async def add_kpi_mapping(
        self,
        *,
        challenge_key,
        mapping: ChallengeKPIMappingRequest,
        company_id: UUID | None = None,
    ) -> ChallengeKPIMappingResponse:
        challenge = await self.challenge_repo.get_by_id(challenge_key, company_id)
        if not challenge:
            raise BusinessException(message="Challenge not found", status_code=404)

        mapping_rows = await self._create_mappings(
            challenge_key,
            [mapping],
            company_id=challenge.company_id,
        )
        return self._to_mapping_response(mapping_rows[0])

    async def update_kpi_mapping(
        self,
        *,
        mapping_id: UUID,
        payload: KPIChallengeUpdateRequest,
        company_id: UUID | None = None,
    ) -> tuple[ChallengeKPIMappingResponse, dict]:
        """Patch start_date / end_date / is_active on a single kpi_challenges
        row. Returns ``(response, old_snapshot)`` so the route handler can
        feed the snapshot into an audit log.

        Re-validates the merged date range — request that would invert
        start/end is rejected with 422 even if only one date is patched
        (the new date is compared against the existing other date)."""
        mapping = await self.kpi_challenge_repo.get_by_id(mapping_id, company_id)
        if not mapping:
            raise BusinessException(message="KPI mapping not found", status_code=404)

        old_snapshot = {
            "start_date": mapping.start_date,
            "end_date": mapping.end_date,
            "is_active": bool(mapping.is_active),
        }

        if payload.start_date is not None:
            mapping.start_date = payload.start_date
        if payload.end_date is not None:
            mapping.end_date = payload.end_date
        if payload.is_active is not None:
            mapping.is_active = payload.is_active

        # Merged-range validation. ``end_date IS NULL`` means open-ended,
        # which is always valid against any start_date.
        if (
            mapping.end_date is not None
            and mapping.start_date is not None
            and mapping.start_date > mapping.end_date
        ):
            raise BusinessException(
                message="start_date cannot be greater than end_date",
                status_code=422,
            )

        await self.kpi_challenge_repo.update(mapping)
        return self._to_mapping_response(mapping), old_snapshot

    async def delete_kpi_mapping(
        self,
        *,
        mapping_id: UUID,
        company_id: UUID | None = None,
    ) -> tuple[ChallengeKPIMappingResponse, dict]:
        """Soft-delete a kpi_challenges row (is_deleted=TRUE, is_active=FALSE).

        Returns ``(response, old_snapshot)`` mirroring update_kpi_mapping —
        old_snapshot captures the pre-delete state for the audit log."""
        mapping = await self.kpi_challenge_repo.get_by_id(mapping_id, company_id)
        if not mapping:
            raise BusinessException(message="KPI mapping not found", status_code=404)

        old_snapshot = {
            "kpi_key": mapping.kpi_key,
            "challenge_key": mapping.challenge_key,
            "start_date": mapping.start_date,
            "end_date": mapping.end_date,
            "is_active": bool(mapping.is_active),
        }
        await self.kpi_challenge_repo.soft_delete(mapping)
        return self._to_mapping_response(mapping), old_snapshot

    async def list_active_for_kpi(
        self,
        *,
        kpi_key,
        start_date: date | None,
        end_date: date | None,
        company_id: UUID | None = None,
    ) -> list[KPIChallengeActiveResponse]:
        kpi = await self.kpi_repo.get_by_id(kpi_key, company_id)
        if not kpi:
            raise BusinessException(message="KPI not found", status_code=404)

        rows = await self.kpi_challenge_repo.list_by_kpi_and_range(
            kpi_key=kpi_key,
            start_date=start_date,
            end_date=end_date,
        )
        output: list[KPIChallengeActiveResponse] = []
        for mapping, challenge in rows:
            output.append(
                KPIChallengeActiveResponse(
                    challenge_key=challenge.challenge_key,
                    name=challenge.name,
                    description=challenge.description,
                    challenge_type=challenge.challenge_type,
                    target_value=challenge.target_value,
                    xp_reward=challenge.xp_reward,
                    icon=challenge.icon,
                    is_daily=challenge.is_daily,
                    options=challenge.options,
                    start_date=mapping.start_date,
                    end_date=mapping.end_date,
                )
            )
        return output

    async def _create_mappings(
        self,
        challenge_key,
        mappings: list[ChallengeKPIMappingRequest],
        *,
        company_id,
    ) -> list[KPIChallenge]:
        kpi_ids = {m.kpi_key for m in mappings}
        for kpi_id in kpi_ids:
            kpi = await self.kpi_repo.get_by_id(kpi_id, company_id)
            if not kpi:
                raise BusinessException(
                    message="KPI not found",
                    status_code=404,
                    errors={"kpi_key": str(kpi_id)},
                )

        entities = [
            KPIChallenge(
                company_id=company_id,
                challenge_key=challenge_key,
                kpi_key=mapping.kpi_key,
                start_date=mapping.start_date,
                end_date=mapping.end_date,
            )
            for mapping in mappings
        ]
        return await self.kpi_challenge_repo.create_many(entities)

    @staticmethod
    def _to_response(
        challenge: Challenge,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        kpi_keys: list = None,
    ) -> ChallengeResponse:
        return ChallengeResponse(
            challenge_key=challenge.challenge_key,
            company_id=challenge.company_id,
            name=challenge.name,
            description=challenge.description,
            challenge_type=challenge.challenge_type,
            target_value=challenge.target_value,
            xp_reward=challenge.xp_reward,
            icon=challenge.icon,
            is_daily=challenge.is_daily,
            is_active=bool(challenge.is_active),
            options=challenge.options,
            start_date=start_date,
            end_date=end_date,
            kpi_keys=kpi_keys or [],
            created_at=challenge.created_at,
            updated_at=challenge.updated_at,
        )

    @staticmethod
    def _compute_date_range(mappings: list[KPIChallenge]) -> tuple[date | None, date | None]:
        if not mappings:
            return None, None
        start_dates = [m.start_date for m in mappings if m.start_date]
        end_dates = [m.end_date for m in mappings if m.end_date]
        start_date = min(start_dates) if start_dates else None
        end_date = None if any(m.end_date is None for m in mappings) else (max(end_dates) if end_dates else None)
        return start_date, end_date

    @staticmethod
    def _compute_kpi_keys(mappings: list[KPIChallenge]) -> list:
        if not mappings:
            return []
        return list({m.kpi_key for m in mappings if m.kpi_key})

    @staticmethod
    def _to_mapping_response(mapping: KPIChallenge) -> ChallengeKPIMappingResponse:
        return ChallengeKPIMappingResponse(
            id=mapping.id,
            kpi_key=mapping.kpi_key,
            start_date=mapping.start_date,
            end_date=mapping.end_date,
            created_at=mapping.created_at,
            updated_at=mapping.updated_at,
        )
