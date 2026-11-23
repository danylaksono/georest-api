# Upstream verification

## Phase 1 · November 23, 2026

| Dependency | Pin | Result |
|---|---|---|
| Traefik | `traefik:v3.7.19` | The file provider routes over Docker DNS. v3 method matchers take one method each. [Routing rules](https://doc.traefik.io/traefik/reference/routing-configuration/http/routing/rules-and-priority/) |
| pygeoapi | `ghcr.io/geopython/pygeoapi:0.24.0` | Includes PyYAML and psycopg2. The entrypoint generates OpenAPI. `SCRIPT_NAME=/api` works with the unstripped path. CQL2 returned the expected feature. [Entrypoint](https://github.com/geopython/pygeoapi/blob/0.24.0/docker/entrypoint.sh) · [Feature providers](https://docs.pygeoapi.io/en/stable/publishing/ogcapi-features.html#postgresql) |
| Martin | `ghcr.io/maplibre/martin:1.16.1` | `route_prefix: /tiles` mounts routes and `base_path` affects TileJSON. Explicit `postgres.tables` with `auto_publish: false` works. TileJSON advertised the public origin. The internal MVT proxy fetched the same non-empty tile. Its provider needs a dot-free upstream path on pygeoapi 0.24.0. [Pinned schema](https://github.com/maplibre/martin/blob/martin-v1.16.1/schemas/config.json) · [MVT proxy source](https://github.com/geopython/pygeoapi/blob/0.24.0/pygeoapi/provider/mvt_proxy.py) |
| PostGIS | `postgis/postgis:17-3.6-alpine` | The amd64 image initializes PostGIS before the demo bootstrap. [Image project](https://github.com/postgis/docker-postgis) |
| Docker Compose | v5.6.0 on Windows | `-f` flags and `COMPOSE_PATH_SEPARATOR=:` worked natively. `up --build --wait` accepted the successful config job and waited for health checks. [Compose environment variables](https://docs.docker.com/compose/how-tos/environment-variables/envvars/) |

## Phase 2 · November 23, 2026

- `varnish:9.1.0-2` supplies `curl` and runs as the `varnish` user. The rendered policy is readable by that user, and VCL compilation runs before the daemon starts. The VCL uses standard pass and backend-response hooks and keeps Varnish's encoding negotiation. [Official image](https://hub.docker.com/_/varnish) · [VCL hooks](https://docs.varnish-software.com/book/vcl/hooks-subroutines-and-built-in-vcl/)
- Martin's explicit table `properties` map determines which fields are encoded. Set `cache: disable` when Varnish owns the freshness lifetime. [Pinned config schema](https://github.com/maplibre/martin/blob/martin-v1.16.1/schemas/config.json)

## Phase 3 · November 23, 2026

- Traefik v3.7.19 accepts `usersFile` for Basic authentication. The IP allowlist uses the connecting peer by default. Production uses HTTP-01 on port 80 and a persistent ACME volume. Local HTTPS uses the test overlay and generated certificates. [Basic auth](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/basicauth/) · [IP allowlist](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/ipallowlist/) · [ACME](https://doc.traefik.io/traefik/reference/install-configuration/tls/certificate-resolvers/acme/)
- PostgreSQL default privileges are scoped to each creating role. GeoREST applies object grants deliberately and checks effective write privileges after revocation. [PostgreSQL default privileges](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html)
- Bundled and external database fixtures passed local HTTPS, create/replace/delete, and editor privilege revocation without resetting the database. The pinned feature routes support POST, PUT, and DELETE. The bundled fixture also exercised Basic auth, CIDR guards, both guards together, authenticated tile reads, and CORS preflights. [Pinned Flask routes](https://github.com/geopython/pygeoapi/blob/0.24.0/pygeoapi/flask_app.py)

## Phase 4 feasibility · November 23, 2026

`python tests/auth_probe.py` builds fastgeoapi v0.4.0 at `f6d860a8c74c091fcc9b1f4feb5d33d7e4d3db24` with its upstream lockfile. The version tags tried on GHCR were unavailable. The fixture uses `fastapi-opa==2.0.3`, Keycloak `26.8.2`, OPA `1.22.4`, Traefik `v3.7.19`, and disposable realm credentials. It checks real Keycloak UserInfo claims and runs two Rego role tests. [fastgeoapi source](https://github.com/geobeyond/fastgeoapi/tree/f6d860a8c74c091fcc9b1f4feb5d33d7e4d3db24) · [OIDC wiring](https://github.com/geobeyond/fastgeoapi/blob/v0.4.0/app/config/auth.py) · [fastapi-opa release](https://pypi.org/project/fastapi-opa/2.0.3/)

| Through Traefik | Agreed public-read behavior | Observed stock behavior |
|---|---:|---:|
| Anonymous `GET` | `200` | `303` |
| Anonymous `POST` | `401` | `303` |
| Viewer `GET` | `200` | `200` |
| Viewer `POST` | `403` | `401` |

The stock OIDC middleware redirects before policy evaluation. OPA can distinguish viewer and editor in the policy, but the pinned middleware maps a policy denial to `401`. The API key, JWKS, and OPA modes are mutually exclusive. Keep Level 4 deferred pending a decision on an adapter or a revised HTTP contract. Review distribution notices for `fastapi-opa` if a future release incorporates it. [Middleware selection](https://github.com/geobeyond/fastgeoapi/blob/v0.4.0/app/main.py#L151-L211)
