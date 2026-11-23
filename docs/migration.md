# Migrate an existing GeoREST deployment

Keep the existing database and volumes. Run the new Compose project with a different project name and host port during validation. For example, set `GEOREST_HTTP_PORT=8088`, set `PUBLIC_URL=http://localhost:8088`, and pass `-p georest-next` to Docker Compose.

1. Create a new `.env` and follow the [external PostGIS setup](configuration.md#external-postgis). Map the old `DATABASE_URL` host, port, database name, and TLS policy to the new settings. Provision restricted reader credentials and make an explicit collection manifest.
2. Change feature clients from `/features` or `/geoapi` to `/api`. The old default Compose had PostgREST commented out. Clients using separately deployed PostgREST at `/api` must migrate their requests to OGC API Features.
3. Retrieve collection IDs from `/api/collections` and tile IDs from `/tiles/catalog`. TileJSON is at `/tiles/<id>` and tile data at `/tiles/<id>/{z}/{x}/{y}`. MapLibre's `source-layer` comes from `vector_layers[].id` in TileJSON. Reuse a legacy public ID if it fits the new syntax.
4. Check a known feature and tile through the new edge and verify unlisted tables are inaccessible. Switch clients or upstream routing after those checks pass.
5. To roll back, restore the old client base URL or upstream target. Stop the new Compose project with `down`, preserving volumes. Use your prior deployment config with rotated credentials if the old service needs restarting.

Rotate credentials used from the old committed environment or service configs. Removing a file from the working tree leaves historical commits intact.
