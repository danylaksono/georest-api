# GeoREST API

Serve PostGIS data to QGIS and WebGIS clients through OGC API Features, OGC API Tiles, and MapLibre-compatible vector tiles.

## Quickstart

Clone the repository and copy `.env.example` to `.env`. Use `Copy-Item .env.example .env` in PowerShell or `cp .env.example .env` in a POSIX shell. With Docker running, start the demo.

```sh
docker compose up -d --build --wait
```

- [OGC API landing page](http://localhost/api)
- [Feature collections](http://localhost/api/collections)
- [Martin catalog](http://localhost/tiles/catalog)
- [Demo TileJSON](http://localhost/tiles/demo_points)

The demo publishes read-only data on loopback. Stop it with `docker compose down`. To use your own data, [configure external PostGIS](docs/configuration.md#external-postgis) and name the datasets in a collection manifest.

## Architecture

![GeoREST architecture. GIS clients connect through Traefik. pygeoapi serves features from PostGIS and proxies OGC tile requests to Martin. Direct and OGC tile requests share the optional Varnish cache.](docs/architecture.png)

At Level 1, Traefik and pygeoapi send tile requests directly to Martin. At Levels 2–4, Varnish caches eligible tile responses. Requests with credentials or cookies bypass the shared cache.

Level 4 keeps these data paths and adds Keycloak for sign-in and an OPA policy check at Traefik for protected requests.

[Editable draw.io diagram](docs/architecture.drawio)

## Deployment levels

| Level | Start with | Adds |
|---|---|---|
| 1 · Quickstart | `make up LEVEL=1` | Read-only features and tiles |
| 2 · Cache | `make up LEVEL=2` | Shared vector tile cache with per-collection TTLs |
| 3 · Secure | `make up LEVEL=3` | HTTPS, guarded feature writes, and optional private reads |
| 4 · Roles | `make up LEVEL=4` | OIDC bearer tokens, viewer/editor roles, and per-collection write policy |

See [deployment levels](docs/levels.md) for Compose-only commands, [configuration](docs/configuration.md) for manifests and write setup, and [Level 4 authentication](docs/oidc.md) for Keycloak setup. The [client examples](docs/webgis-clients.md) cover MapLibre, OpenLayers, and QGIS. For an existing deployment, see the [migration guide](docs/migration.md). The [verification notes](docs/VERIFIED.md) record dependency versions and runtime checks.

## License

[MIT](LICENSE)
