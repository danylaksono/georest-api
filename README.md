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

For an existing deployment, see the [migration guide](docs/migration.md). The [verification notes](docs/VERIFIED.md) record dependency versions and runtime checks.

## License

[MIT](LICENSE)
