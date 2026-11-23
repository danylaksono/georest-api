#!/bin/sh
set -eu

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv keycloak_password KEYCLOAK_DB_PASSWORD
CREATE ROLE keycloak LOGIN PASSWORD :'keycloak_password';
ALTER DATABASE keycloak OWNER TO keycloak;
SQL
