-- Run this after checking there are no active duplicates in company_users.
-- Active rows are defined here as is_deleted = false, matching the service logic.

-- Optional pre-checks:
-- SELECT company_id, email, COUNT(*)
-- FROM company_users
-- WHERE is_deleted = false
-- GROUP BY company_id, email
-- HAVING COUNT(*) > 1;
--
-- SELECT company_id, emp_id, COUNT(*)
-- FROM company_users
-- WHERE is_deleted = false AND emp_id IS NOT NULL
-- GROUP BY company_id, emp_id
-- HAVING COUNT(*) > 1;

ALTER TABLE company_users
DROP CONSTRAINT IF EXISTS company_users_email_key;

DROP INDEX IF EXISTS company_users_email_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_company_users_company_email_active
ON company_users (company_id, email)
WHERE is_deleted = false;

CREATE UNIQUE INDEX IF NOT EXISTS uq_company_users_company_emp_id_active
ON company_users (company_id, emp_id)
WHERE is_deleted = false AND emp_id IS NOT NULL;
