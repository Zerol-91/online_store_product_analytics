-- Bootstrap two databases and separate loading, reporting, and application roles.
\getenv loader_password ANALYTICS_LOADER_PASSWORD
\getenv reader_password ANALYTICS_READER_PASSWORD
\getenv metabase_password METABASE_DB_PASSWORD

CREATE ROLE analytics_loader LOGIN PASSWORD :'loader_password';
CREATE ROLE analytics_reader LOGIN PASSWORD :'reader_password';
CREATE ROLE metabase_app LOGIN PASSWORD :'metabase_password';

CREATE DATABASE analytics OWNER analytics_loader;
CREATE DATABASE metabase_app OWNER metabase_app;
REVOKE ALL ON DATABASE analytics FROM PUBLIC;
GRANT CONNECT ON DATABASE analytics TO analytics_loader, analytics_reader;
REVOKE ALL ON DATABASE metabase_app FROM PUBLIC;
GRANT CONNECT ON DATABASE metabase_app TO metabase_app;

\connect analytics
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA reporting AUTHORIZATION analytics_loader;
GRANT USAGE ON SCHEMA reporting TO analytics_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE analytics_loader IN SCHEMA reporting
    GRANT SELECT ON TABLES TO analytics_reader;

\connect metabase_app
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO metabase_app;
