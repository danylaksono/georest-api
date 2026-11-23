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
