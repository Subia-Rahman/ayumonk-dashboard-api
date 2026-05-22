# Tests for the CXO metrics feature

These tests cover Parts 1, 4, 5, 6 of the CXO metrics feature in
[../config_service/app](../config_service/app).

## Running

The full suite requires a Postgres test database with the same extensions
the app uses (`pgcrypto` for `gen_random_uuid()`), and an environment
variable `TEST_DATABASE_URL` pointing at it, e.g.:

```powershell
$env:TEST_DATABASE_URL = "postgresql+asyncpg://test:test@localhost:5432/ayumonk_test"
pytest tests/ -v
```

Tests that require a live database are decorated with
`@pytest.mark.requires_db`. Without a database they `pytest.skip` and the
remaining unit tests still run.

## Layout

* `conftest.py` — pytest fixtures, DB bootstrap, k-anonymity helpers.
* `test_alembic_migrations.py` — runs the SQL up/down migrations on a fresh
  test schema.
* `test_seeder.py` — default seeder happy path, missing-KPI handling.
* `test_validation.py` — request payload validation rules.
* `test_admin_routes.py` — PUT mapping transactional rollback + audit log.
* `test_k_anonymity.py` — bucket suppression in the dashboard endpoint.
* `test_rbac.py` — 403s for cross-tenant and read-only roles.
* `test_engagement.py` — numerical correctness for the engagement function.
* `test_productivity_math.py` — numerical correctness for v_user_cxo.
