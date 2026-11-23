#!/bin/sh
set -eu

case "$GEOREST_BIND_ADDRESS" in
    127.*|::1) ;;
    *)
        if [ "$POSTGRES_PASSWORD" = demo-db-password ] ||
           [ "$GEOREST_READER_PASSWORD" = demo-reader-password ] ||
           [ "$GEOREST_EDITOR_PASSWORD" = demo-editor-password ]; then
            echo 'Replace demo database passwords before using a non-loopback bind.' >&2
            exit 1
        fi
        ;;
esac

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
\getenv reader_password GEOREST_READER_PASSWORD
\getenv editor_password GEOREST_EDITOR_PASSWORD
SELECT 'CREATE ROLE georest_reader LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'georest_reader')
\gexec
SELECT 'CREATE ROLE georest_editor LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'georest_editor')
\gexec
ALTER ROLE georest_reader PASSWORD :'reader_password';
ALTER ROLE georest_editor PASSWORD :'editor_password';
SQL
