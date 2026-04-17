from datetime import date
import pandas as pd
import math

from config_service.app.models.kpi_questions import KPIQuestion
from config_service.app.models.kpi_scoring import KPIScoring
from config_service.app.schemas.kpi import KPICreateRequest, KPIUpdateRequest
from config_service.app.schemas.kpi_hierarchy import (
    KPIOptionResponse,
    KPIQuestionResponse,
    KPIResponse,
    ThemeHierarchyResponse,
)
from config_service.app.schemas.theme import ThemeCreateRequest, ThemeUpdateRequest
from config_service.app.services.kpi import KPIService as KPIAdminService
from config_service.app.services.theme import ThemeService


class KPIService:

    def __init__(
        self,
        theme_repo,
        kpi_repo,
        question_repo,
        scoring_repo
    ):
        self.theme_repo = theme_repo
        self.kpi_repo = kpi_repo
        self.question_repo = question_repo
        self.scoring_repo = scoring_repo
        self.theme_service = ThemeService(theme_repo)
        self.kpi_service = KPIAdminService(kpi_repo)

    # ---------- helpers ----------
    def _clean_str(self, val):
        if val is None:
            return None
        # handle float NaN
        if isinstance(val, float) and math.isnan(val):
            return None
        return str(val).strip()  # keep literal "None" as-is


    def _clean_int(self, val):
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        try:
            return int(val)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid integer value") from exc

    def _normalize_columns(self, row) -> dict:
        return {
            str(column).strip().lower(): row.get(column)
            for column in row.index
        }

    def _get_value(self, values: dict, key: str):
        return values.get(key.strip().lower())

    def _parse_optional_date(self, val, column_name: str) -> date | None:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        if isinstance(val, date) and not hasattr(val, "hour"):
            return val

        parsed = pd.to_datetime(val, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"Invalid date format for {column_name}")
        return parsed.date()

    def _parse_optional_float(self, val, column_name: str) -> float | None:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        try:
            return float(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid numeric value for {column_name}") from exc

    def _parse_optional_int(self, val, column_name: str) -> int | None:
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return None
        try:
            return int(val)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid integer value for {column_name}") from exc

    def _parse_bool_yes_no(self, val) -> bool:
        cleaned = self._clean_str(val)
        return cleaned is not None and cleaned.lower() == "yes"

    def _validate_required_fields(
        self,
        *,
        theme_name: str | None,
        kpi_name: str | None,
        code: str | None,
        question_text: str | None,
    ) -> None:
        if not theme_name:
            raise ValueError("Theme missing")
        if not kpi_name:
            raise ValueError("KPI missing")
        if not code:
            raise ValueError("Question_Code missing")
        if not question_text:
            raise ValueError("Question text missing")

    def _parse_theme_payload(self, values: dict) -> dict:
        return {
            "theme_display_name": self._clean_str(self._get_value(values, "Theme")),
            "description": self._clean_str(self._get_value(values, "description")),
            "duration_days": self._parse_optional_int(self._get_value(values, "duration_days"), "duration_days"),
            "target_audience": self._clean_str(self._get_value(values, "target_audience")),
            "description_present": "description" in values,
            "duration_days_present": "duration_days" in values,
            "target_audience_present": "target_audience" in values,
        }

    def _parse_kpi_payload(self, values: dict) -> dict:
        start_date = self._parse_optional_date(self._get_value(values, "start_date"), "start_date")
        end_date = self._parse_optional_date(self._get_value(values, "end_date"), "end_date")
        if start_date and end_date and start_date > end_date:
            raise ValueError("start_date cannot be greater than end_date")

        return {
            "display_name": self._clean_str(self._get_value(values, "KPI")),
            "domain_category": self._clean_str(self._get_value(values, "domain_category")),
            "wi_weight": self._parse_optional_float(self._get_value(values, "wi_weight"), "wi_weight"),
            "start_date": start_date,
            "end_date": end_date,
            "domain_category_present": "domain_category" in values,
            "wi_weight_present": "wi_weight" in values,
            "start_date_present": "start_date" in values,
            "end_date_present": "end_date" in values,
        }

    async def _upsert_theme(self, theme_data: dict):
        theme = await self.theme_repo.get_by_name(theme_data["theme_display_name"])
        if not theme:
            payload = ThemeCreateRequest(
                theme_display_name=theme_data["theme_display_name"],
                description=theme_data["description"],
                duration_days=theme_data["duration_days"],
                target_audience=theme_data["target_audience"],
            )
            created_theme = await self.theme_service.create(payload)
            return await self.theme_repo.get_by_id(created_theme.theme_key)

        update_payload = {}
        if theme_data["description_present"]:
            update_payload["description"] = theme_data["description"]
        if theme_data["duration_days_present"]:
            update_payload["duration_days"] = theme_data["duration_days"]
        if theme_data["target_audience_present"]:
            update_payload["target_audience"] = theme_data["target_audience"]

        if update_payload:
            updated_theme = await self.theme_service.update(
                theme.theme_key,
                ThemeUpdateRequest(**update_payload),
            )
            return await self.theme_repo.get_by_id(updated_theme.theme_key)

        return theme

    async def _upsert_kpi(self, theme, kpi_data: dict):
        kpi = await self.kpi_repo.get_by_name_and_theme(
            kpi_data["display_name"],
            theme.theme_key,
        )
        if not kpi:
            payload = KPICreateRequest(
                display_name=kpi_data["display_name"],
                theme_key=theme.theme_key,
                start_date=kpi_data["start_date"],
                end_date=kpi_data["end_date"],
                domain_category=kpi_data["domain_category"],
                wi_weight=kpi_data["wi_weight"] if kpi_data["wi_weight"] is not None else 0.10,
            )
            created_kpi = await self.kpi_service.create(payload)
            return await self.kpi_repo.get_by_id(created_kpi.kpi_key)

        update_payload = {}
        if kpi_data["start_date_present"]:
            update_payload["start_date"] = kpi_data["start_date"]
        if kpi_data["end_date_present"]:
            update_payload["end_date"] = kpi_data["end_date"]
        if kpi_data["domain_category_present"]:
            update_payload["domain_category"] = kpi_data["domain_category"]
        if kpi_data["wi_weight_present"]:
            update_payload["wi_weight"] = kpi_data["wi_weight"]

        if update_payload:
            updated_kpi = await self.kpi_service.update(
                kpi.kpi_key,
                KPIUpdateRequest(**update_payload),
            )
            return await self.kpi_repo.get_by_id(updated_kpi.kpi_key)

        return kpi

    # ---------- main ----------
    async def upload_kpi_from_excel(self, file):
        df = pd.read_excel(file, dtype=object)

        created = 0
        updated = 0
        errors = []

        required_headers = {"theme", "kpi", "question_code", "question"}
        normalized_headers = {str(column).strip().lower() for column in df.columns}
        missing_headers = sorted(required_headers - normalized_headers)
        if missing_headers:
            return {
                "created": created,
                "updated": updated,
                "errors": [{
                    "row": 0,
                    "question_code": None,
                    "error": f"Missing required columns: {', '.join(missing_headers)}",
                }],
            }

        for idx, row in df.iterrows():
            try:
                values = self._normalize_columns(row)
                theme_data = self._parse_theme_payload(values)
                kpi_data = self._parse_kpi_payload(values)
                theme_name = theme_data["theme_display_name"]
                kpi_name = kpi_data["display_name"]
                code = self._clean_str(self._get_value(values, "Question_Code"))
                question_text = self._clean_str(self._get_value(values, "Question"))
                reverse_raw = self._get_value(values, "Reverse_Coded")

                self._validate_required_fields(
                    theme_name=theme_name,
                    kpi_name=kpi_name,
                    code=code,
                    question_text=question_text,
                )

                # ---------- THEME ----------
                theme = await self._upsert_theme(theme_data)

                # ---------- KPI ----------
                kpi = await self._upsert_kpi(theme, kpi_data)

                # ---------- QUESTION ----------
                question = await self.question_repo.get_by_code(code)

                if question:
                    updated += 1
                else:
                    question = KPIQuestion(
                        theme = theme.theme_key,
                        question_code=code,
                        kpi=kpi.kpi_key
                    )
                    created += 1

                question.question_text = question_text
                question.reverse_code = self._parse_bool_yes_no(reverse_raw)
                question = await self.question_repo.save(question)

                # ---------- SCORING ----------
                await self.scoring_repo.delete_by_question(question.id)

                for i in range(1, 6):
                    option_text = row.get(str(i))

                    # convert NaN to None, but keep literal "None" string
                    if isinstance(option_text, float) and math.isnan(option_text):
                        option_text = None
                    elif option_text is not None:
                        option_text = str(option_text).strip()

                    # score is the column number itself
                    score = i

                    # save in DB
                    await self.scoring_repo.create(
                        KPIScoring(
                            question_id=question.id,
                            option_number=i,
                            option_text=option_text,
                            score=score
                        )
                    )


            except Exception as e:
                errors.append({
                    "row": idx + 1,
                    "question_code": self._clean_str(row.get("Question_Code")),
                    "error": str(e)
                })

        return {
            "created": created,
            "updated": updated,
            "errors": errors
        }

    async def get_hierarchy(self) -> list[ThemeHierarchyResponse]:
        rows = await self.question_repo.get_hierarchy_rows()
        themes: dict = {}

        for row in rows:
            theme_key = row.theme_key
            kpi_key = row.kpi_key
            question_id = row.id

            theme_bucket = themes.get(theme_key)
            if theme_bucket is None:
                theme_bucket = {
                    "theme_key": theme_key,
                    "theme_display_name": row.theme_display_name,
                    "kpis": {},
                }
                themes[theme_key] = theme_bucket

            if kpi_key is not None:
                kpi_bucket = theme_bucket["kpis"].get(kpi_key)
                if kpi_bucket is None:
                    kpi_bucket = {
                        "kpi_key": kpi_key,
                        "display_name": row.display_name,
                        "questions": {},
                    }
                    theme_bucket["kpis"][kpi_key] = kpi_bucket

            if kpi_key is None or question_id is None:
                continue

            question_bucket = kpi_bucket["questions"].get(question_id)
            if question_bucket is None:
                question_bucket = {
                    "id": question_id,
                    "question_code": row.question_code,
                    "question_text": row.question_text,
                    "reverse_code": bool(row.reverse_code),
                    "options": [],
                }
                kpi_bucket["questions"][question_id] = question_bucket

            if row.option_number is not None or row.option_text is not None or row.score is not None:
                question_bucket["options"].append(
                    KPIOptionResponse(
                        option_number=row.option_number,
                        option_text=row.option_text,
                        score=row.score,
                    )
                )

        response: list[ThemeHierarchyResponse] = []
        for theme_data in themes.values():
            kpis: list[KPIResponse] = []
            for kpi_data in theme_data["kpis"].values():
                questions = [
                    KPIQuestionResponse(**question_data)
                    for question_data in kpi_data["questions"].values()
                ]
                kpis.append(
                    KPIResponse(
                        kpi_key=kpi_data["kpi_key"],
                        display_name=kpi_data["display_name"],
                        questions=questions,
                    )
                )

            response.append(
                ThemeHierarchyResponse(
                    theme_key=theme_data["theme_key"],
                    theme_display_name=theme_data["theme_display_name"],
                    kpis=kpis,
                )
            )

        return response
