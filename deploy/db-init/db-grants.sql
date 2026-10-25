-- Permissions for one database (the current one). Included by db-init.sql.

REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT, CREATE ON DATABASE :"db" TO migrator;  -- CREATE lets it add trusted extensions
GRANT CONNECT ON DATABASE :"db" TO app;

ALTER SCHEMA public OWNER TO migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO app;

-- Every table and sequence the migrator creates is automatically usable by app (rows only).
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app;
ALTER DEFAULT PRIVILEGES FOR ROLE migrator IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO app;
