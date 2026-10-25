-- Creates the two database users and the test database. Safe to run on every start.
-- Run by the `db-init` service as the Postgres superuser (SECURITY_AND_ACCESS.md § 5.6):
--   migrator  owns the schema; used only by Alembic (the `migrate` service)
--   app       reads and writes rows; used by api and app-worker; cannot create or drop tables
--
-- psql variables: :migrator_password  :app_password  :main_db  :test_db

\set ON_ERROR_STOP on

SELECT format('CREATE ROLE migrator LOGIN PASSWORD %L', :'migrator_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'migrator') \gexec
SELECT format('CREATE ROLE app LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app') \gexec

-- Keep passwords in sync with .env if they were changed.
ALTER ROLE migrator PASSWORD :'migrator_password';
ALTER ROLE app PASSWORD :'app_password';

SELECT format('CREATE DATABASE %I', :'test_db')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'test_db') \gexec

\set db :main_db
\connect :db
\ir db-grants.sql

\set db :test_db
\connect :db
\ir db-grants.sql
