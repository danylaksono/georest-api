# Configure GeoREST

Copy `.env.example` to `.env`. Pass each Compose `-f` in order when using overlays. For colon-delimited `COMPOSE_FILE` lists on native Windows, include `COMPOSE_PATH_SEPARATOR=:` in `.env`.

| Setting | Default and purpose |
|---|---|
| `COMPOSE_PROFILES` | `db` enables the bundled database. |
| `GEOREST_DATASET` | `demo` uses the bundled fixture. `external` uses an existing database with an explicit manifest. |
| `GEOREST_CONFIG_MODE` | `auto` generates configs. `manual` uses operator-managed configs. |
| `GEOREST_COLLECTIONS_FILE` | Manifest path. Defaults to the demo manifest and is required in external auto mode. |
| `GEOREST_MANUAL_DIR` | Directory holding `pygeoapi.config.yml` and `martin.yaml` in manual mode. Defaults to `./config`. |
| `PUBLIC_URL` | `http://localhost`. Browser-facing origin, including the port if nonstandard. |
| `GEOREST_BIND_ADDRESS`, `GEOREST_HTTP_PORT` | `127.0.0.1` and `80`. Published HTTP socket. |
| `CORS_ORIGINS` | `*` for the demo. Enter comma-separated allowed browser origins or an empty value to disable CORS headers. |
| `GEOREST_TITLE`, `GEOREST_DESCRIPTION` | OGC landing page metadata. |
| `GEOREST_API_WORKERS` | `2` Gunicorn workers. |
| `PGHOST`, `PGPORT`, `PGDATABASE`, `PGSSLMODE` | `postgis`, `5432`, `gis`, and `prefer` for the bundled database. |
| `POSTGRES_PASSWORD` | Initial superuser password for the bundled database. |
| `GEOREST_READER_PASSWORD`, `GEOREST_EDITOR_PASSWORD` | Restricted role passwords. Rotate or provision explicitly when using an existing database volume. |
| `GEOREST_REGISTRY`, `GEOREST_VERSION` | `ghcr.io/danylaksono` and `dev` for custom images. |
| `VARNISH_SIZE` | `1G` of cache storage in Level 2. |
| `TILE_TTL_DEFAULT`, `TILE_TTL_VOLATILE` | `3600` and `60` seconds for static and volatile sources. |
| `DOMAIN`, `ACME_EMAIL` | Public hostname matching the HTTPS `PUBLIC_URL` and ACME account email at Level 3. |
| `GEOREST_HTTPS_PORT` | `443`. Host HTTPS port. |
| `GEOREST_ALLOW_EDITS` | `false`. Enable transactions on manifest entries marked `editable: true`. |
| `WRITE_ALLOWLIST` | Comma-separated CIDRs for write access. Traefik checks the connection's peer address. |
| `GEOREST_AUTH_DIR` | Directory of htpasswd files at Level 3. Defaults to `./config/local/auth`. |
| `WRITE_BASIC_AUTH_FILE`, `API_BASIC_AUTH_FILE` | Filenames in the auth directory for write and read access, respectively. |
| `GEOREST_ADMIN_DSN` | Administrator connection string passed only to the grant reconciliation job. |
| `GEOREST_PRIVATE_READ`, `GEOREST_PRIVATE_TILES` | `false`. Require an OIDC token for feature reads or both tile paths at Level 4. |
| `KEYCLOAK_REALM_FILE` | `./config/local/keycloak/realm.json`. Initial realm import file. |
| `KEYCLOAK_DB_ADMIN_PASSWORD`, `KEYCLOAK_DB_PASSWORD` | Separate passwords for the identity database administrator and restricted Keycloak login. |
| `KC_BOOTSTRAP_ADMIN_USERNAME`, `KC_BOOTSTRAP_ADMIN_PASSWORD` | Temporary Keycloak administrator credentials for the first start. |

## External PostGIS

Set `GEOREST_DATASET=external` and clear `COMPOSE_PROFILES`. Set `PGHOST`, `PGPORT`, `PGDATABASE`, `PGSSLMODE`, and `GEOREST_READER_PASSWORD` for the target database. Set `GEOREST_COLLECTIONS_FILE` to a copy of [collections.example.yml](../config/collections.example.yml). A database on the Docker host can use `host.docker.internal` when PostgreSQL listens on an interface reachable from containers.

As a database administrator, enable PostGIS and create the reader. Use `\password georest_reader` in `psql` to set the password interactively. Grant access to named objects.

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE ROLE georest_reader LOGIN;
GRANT CONNECT ON DATABASE gis TO georest_reader;
GRANT USAGE ON SCHEMA survey TO georest_reader;
GRANT SELECT ON TABLE survey.observations, survey.boundaries TO georest_reader;
```

## Manifest and refresh

Each `collections` key is the public collection ID and, when enabled, Martin source ID. Use a letter followed by lowercase letters, digits, underscores, or hyphens. Name the schema, table, and geometry column explicitly. `exclude` takes precedence. `tiles: false` publishes features only. If there is no single-column primary key, set `id_field` to a column with a non-null unique constraint or index. `time_field` accepts a date or timestamp. Titles, descriptions, and keywords are optional.

Run `make refresh LEVEL=1` or `python scripts/refresh.py -f compose.yaml` with the same Compose arguments used for startup. The command validates the new snapshot, briefly stops the edge, and starts the services with the new configs. Run one refresh at a time.

Run `docker compose run --rm --no-deps configure render --check` to validate without applying. Use `--dry-run` to print generated configuration with database credentials redacted.

Read-only manual mode uses `pygeoapi.config.yml` and `martin.yaml` under `GEOREST_MANUAL_DIR`. Set the same `/api` and `/tiles` prefixes, use restricted DB logins and explicit Martin table sources, and maintain matching source IDs and provider URLs. The configuration job uses the `PG*` settings and reader login to wait for PostGIS before the services start.

## Tile cache

Run `docker compose -f compose.yaml -f compose.cache.yaml up -d --build --wait` or `make up LEVEL=2`. Mark a changing collection with `cache: volatile`. Varnish ages tiles against the configured TTL without stale delivery. Martin's tile cache is disabled at this level. The edge sends `Cache-Control: no-store` to keep client caches from extending the server TTL.

Successful public tile requests can hit the shared cache. Cookie and authorization requests bypass it. Catalog and TileJSON requests also bypass it. The direct tile path exposes `X-Cache` to distinguish `HIT`, `MISS`, and `PASS`. Generated Martin sources include scalar text, numeric, and boolean columns as vector tile attributes.

With manual configs, set `cache: disable` in Martin. Point the manual OGC tile provider to `http://varnish/tiles/<id>/{z}/{x}/{y}` if it should share the default TTL.

## HTTPS and editable collections

Set `PUBLIC_URL=https://your-domain`, `DOMAIN`, and `ACME_EMAIL`. Use deployment-specific database passwords and a publicly reachable `GEOREST_BIND_ADDRESS`. Point public DNS to the edge and allow traffic to port 80 for the ACME HTTP-01 challenge and 443 for HTTPS.

Start Level 3 with `GEOREST_ALLOW_EDITS=false` while provisioning the database. To enable writes, set `editable: true` only on the required manifest entries and set `GEOREST_ALLOW_EDITS=true`. Configure `WRITE_ALLOWLIST`, a Basic auth file, or both. Both must pass when combined. An upstream load balancer changes the socket peer seen by Traefik. Use a directly reachable edge or configure trusted proxy handling before using an IP guard behind a load balancer.

To create a password file, make `config/local/auth`, then run `sh scripts/htpasswd.sh editor > config/local/auth/write.htpasswd` with Apache `htpasswd` available. Set `WRITE_BASIC_AUTH_FILE=write.htpasswd`. An `API_BASIC_AUTH_FILE` also protects reads, including direct and OGC tile URLs. Private tile requests bypass the shared cache.

Export `GEOREST_ADMIN_DSN` for the grant job. Supply an account allowed to manage grants on the target database and to create the dedicated service logins if they are missing. Reconciliation owns the logins' direct table, schema, and sequence grants in that database. Keep them dedicated to GeoREST. The administrator connection is used by the short-lived command.

```sh
make grants LEVEL=3
make refresh LEVEL=3
```

Without Make, pass `-f compose.yaml -f compose.cache.yaml -f compose.secure.yaml` to `docker compose run --rm --no-deps -e GEOREST_ADMIN_DSN configure grants`, then pass the same file flags to `python scripts/refresh.py`. Reconcile first when taking edit access away. The refresh command can restore a previous service snapshot on startup failure. To restore previous database grants as part of a deliberate rollback, use the previous manifest and rerun the grants command. Grants apply transactionally against existing volumes and external databases.

For a disposable HTTPS fixture independent of public DNS and Let's Encrypt, run `python tests/secure_deployment.py` or add `--external` to exercise an external PostGIS container. The fixture creates and trusts its own certificate and selects loopback ports.

Level 4 uses the same HTTPS and grant commands with `LEVEL=4` and adds the OIDC overlay. [Configure Level 4](oidc.md)
