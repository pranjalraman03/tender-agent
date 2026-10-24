-- The API, worker and scheduler must connect as a NON-superuser role, otherwise
-- Postgres row-level security is bypassed. Migrations run as the owner role.
-- Run once per environment as the owner, after `alembic upgrade head`:
--   psql "$OWNER_DATABASE_URL" -v app_password="'...'" -f scripts/create_app_role.sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tender_app') THEN
    CREATE ROLE tender_app LOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;
ALTER ROLE tender_app PASSWORD :app_password;
GRANT USAGE ON SCHEMA public TO tender_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tender_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tender_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tender_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO tender_app;
