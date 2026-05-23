# CXO Metrics — Configuration & Dashboard

This document explains the data model, seeding strategy, and signal
vocabulary behind the CXO metric endpoints. For the wire format see the
generated OpenAPI under `/config/openapi.json` (or the local Swagger UI at
`/config/docs`).

## Service placement

Per the placement decision in the design doc, both the configuration
endpoints and the dashboard endpoint live in `config_service`. Routes are
mounted under the existing `/api/v1` prefix; the gateway adds the `/config`
prefix at the edge.

| Endpoint | Method | Caller URL (via gateway) |
| --- | --- | --- |
| List metrics | GET  | `/config/api/v1/admin/cxo-metrics` |
| Options (KPIs + signals) | GET | `/config/api/v1/admin/cxo-metrics/options` |
| Get mapping | GET  | `/config/api/v1/admin/cxo-metrics/{metric_code}/mapping` |
| Replace mapping | PUT  | `/config/api/v1/admin/cxo-metrics/{metric_code}/mapping` |
| Reset to defaults | POST | `/config/api/v1/admin/cxo-metrics/{metric_code}/reset` |
| Dashboard slice | GET  | `/config/api/v1/dashboard/cxo-by-dimension` |

## Data model

```
cxo_metric_master           — platform-wide metric catalog
  └── cxo_metric_kpi_mapping       (per-company KPI weights; WEIGHTED_AVG/DEFICIT_SUM)
  └── cxo_metric_signal_mapping    (per-company signal weights; COMPOSITE)

v_user_kpi_score        — per-user per-KPI averaged answers
v_user_wellness_index   — per-user Wellness Index (0–100)
v_user_cxo              — per-user pivoted Productivity / Absenteeism (Engagement is NULL here)

compute_user_engagement(uuid) — invoked per-row from the dashboard query
```

`cxo_metric_master` is seeded once by `cxo_metrics_up.sql`. The three
platform rows are:

| metric_code   | display_name | unit            | formula_type  |
| ---           | ---          | ---             | ---           |
| PRODUCTIVITY  | Productivity | percent         | WEIGHTED_AVG  |
| ENGAGEMENT    | Engagement   | percent         | COMPOSITE     |
| ABSENTEEISM   | Absenteeism  | days_per_month  | DEFICIT_SUM   |

`formula_type` drives validation:

| formula_type | Valid request shape | Weight sum rule |
| --- | --- | --- |
| WEIGHTED_AVG | `kpi_mappings` only, `threshold` NULL on every row | sum to 1.000 ±0.001 |
| DEFICIT_SUM  | `kpi_mappings` only, `threshold` required | no sum constraint |
| COMPOSITE    | `signal_mappings` only | sum to 1.000 ±0.001 |

## Seeder

`config_service.app.services.cxo_seeder.seed_default_cxo_mappings` is
idempotent: re-running upserts on
`(company_id, metric_id, kpi_key)` and
`(company_id, metric_id, signal_code)`. Default figures come from the
methodology document — see the `_KpiDefault` / `_SignalDefault` constants in
the seeder for exact values.

KPI lookup is by **case-insensitive trimmed `kpis.display_name`** scoped to
`company_id`. If a required KPI is missing the seeder logs a warning and
lists it in `SeedResult.skipped_kpis` rather than raising. The
methodology-tracked schema follow-up is to introduce a `kpis.kpi_code` column
with a CHECK constraint on a controlled vocabulary (`STRESS`, `SLEEP`, …) so
this lookup becomes brittle-name-proof. See "Schema issues" below.

## Engagement signal vocabulary

`compute_user_engagement(uuid)` returns a value in `[0, 100]` (or NULL when
no signal mappings exist for the company). The signal vocabulary is enforced
both at the table level (`ck_signal_code`) and in the function body:

| signal_code | Definition | Fallback (no data) |
| --- | --- | --- |
| `WELLNESS_INDEX`     | `v_user_wellness_index.wellness_index / 100` | 0.5 |
| `CHALLENGE_RATE_30D` | `count(last 30d completions) / 30`, capped at 1.0 | 0.0 |
| `FORM_RATE_90D`      | `count(last 90d responses) / 12`, capped at 1.0 | 0.0 |
| `MOOD_AVG`           | Placeholder 0.6 until mood-tracking ships | — |

The dashboard endpoint invokes the function once per user inside a single
SQL CTE — see `_engagement_query` in `services/cxo_dashboard.py` — so a
typical company-sized cohort is handled in one roundtrip. The Python
wrapper `compute_engagement_batch(db, user_ids)` is available for callers
outside the dashboard's SQL pipeline.

## K-anonymity

`K_ANONYMITY_FLOOR` (5) defined in `services/cxo_dashboard.py` is the
minimum cohort size for a bucket to appear in the dashboard response.
Buckets below the floor are dropped silently and counted in
`meta.suppressedBuckets`.

## Age-band ordering

Canonical order: `20-25, 26-30, 31-35, 36-40, 41-50, 50+`. Buckets outside
this set sort last, alphabetically. Implemented in
`CANONICAL_AGE_BANDS` in `services/cxo_dashboard.py`.

## RBAC summary

| Endpoint | Allowed roles |
| --- | --- |
| GET  /cxo-metrics            | super_admin, ayumonk_admin, admin |
| GET  /cxo-metrics/options    | super_admin, ayumonk_admin, admin |
| GET  /cxo-metrics/.../mapping | super_admin, ayumonk_admin, admin (own company) |
| PUT  /cxo-metrics/.../mapping | super_admin, ayumonk_admin                       |
| POST /cxo-metrics/.../reset   | super_admin, ayumonk_admin                       |
| GET  /dashboard/cxo-by-dimension | super_admin, ayumonk_admin, admin, hr, cxo  |

Company-tier callers always see their own `company_id` regardless of the
query parameter — the dashboard endpoint overrides the param, and
`require_cxo_metrics_read` raises 403 on mismatch.

## Schema issues (open follow-ups)

These were surfaced during implementation and are flagged with `TODO`
comments at the relevant call sites. They are intentionally not fixed in
this feature so the change set stays focused.

1. **`employee_form_response.company_id` is VARCHAR, not UUID.**
   `v_user_kpi_score` casts via `::uuid`. Follow-up: change the column type
   to UUID and drop the cast.
2. **`kpis.display_name` has no controlled vocabulary.** The default seeder
   matches `'Sleep'`, `'Stress'`, etc. via case-insensitive trim. A tenant
   renaming a KPI will silently break the seeder. Follow-up: add
   `kpis.kpi_code VARCHAR(20)` with a CHECK constraint, then re-key the
   seed defaults off that column.
3. **`company_users` has no `location_id` column.** Only
   `companies.location_id` exists. The dashboard endpoint therefore does
   **not** accept `location_id` (filtering after `company_id` is already a
   no-op). Follow-up: add `company_users.location_id`, then re-introduce
   the param.
4. **`user_challenge_completions.user_id` is INTEGER (FK to `users.id`),
   not UUID.** `compute_user_engagement` bridges via `users.email`
   ↔ `company_users.email`. Follow-up: migrate
   `user_challenge_completions.user_id` to UUID + `company_users.id` so
   the engagement signal can drop the email join.

## Running the migrations

The repo uses plain SQL migration files (no Alembic) — same pattern as
[departments.sql](../app/scripts/migrations/departments.sql). To apply, run
them against the target database in this order:

```bash
psql "$DATABASE_URL" -f config_service/app/scripts/migrations/cxo_metrics_up.sql
psql "$DATABASE_URL" -f config_service/app/scripts/migrations/cxo_metrics_engagement.sql
```

To roll back:

```bash
psql "$DATABASE_URL" -f config_service/app/scripts/migrations/cxo_metrics_down.sql
```

## Tests

See [../../tests/](../../tests/README.md). Unit tests run anywhere; tests
marked `@requires_db` need `TEST_DATABASE_URL` to point at a Postgres
instance with the rest of the schema already applied.

## Reference

Methodology document — separate doc owned by the product team. Section
references on `cxo_metric_master.methodology_ref` point into it (e.g.
"Methodology §4.1" for Productivity).
