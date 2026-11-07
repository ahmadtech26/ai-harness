-- O-34: legal-search's own Postgres role, legal_app, which owns the legal database and its public schema and is no
-- superuser. Run as the superuser by the one-shot postgres-roles service (compose.yaml) before every ingest, so it is
-- idempotent: on empty volumes it creates the role before the ingest creates the tables, and on a volume an earlier
-- release wrote as postgres it hands the existing tables to legal_app in place. The password is the one secrets-init
-- writes to /secrets/pg_app_password and puts in /secrets/database_url.
\set app_password `cat /secrets/pg_app_password`

-- legal_app cannot create an extension (pgvector's control file is not trusted), and CREATE EXTENSION IF NOT EXISTS
-- passes for it only when the extension already exists: the semantic search plan runs that at every start.
CREATE EXTENSION IF NOT EXISTS vector;

SELECT 'CREATE ROLE legal_app LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'legal_app') \gexec
ALTER ROLE legal_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_password';

ALTER DATABASE legal OWNER TO legal_app;
ALTER SCHEMA public OWNER TO legal_app;
-- A table's indexes and its serial and identity sequences go with it.
SELECT format('ALTER TABLE public.%I OWNER TO legal_app', tablename)
  FROM pg_tables WHERE schemaname = 'public' AND tableowner <> 'legal_app' \gexec
