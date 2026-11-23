# GeoREST API revamp implementation brief

Build a small, Docker-based geospatial backend for WebGIS clients. The first milestone is a read-only OGC API Features and vector tile service that starts with one Compose command after copying `.env.example`. It must work with both a bundled demo and a separately managed PostGIS database. Later levels add a tile cache, HTTPS and guarded edits, then role-based access if the authentication integration passes its feasibility check.

Read the whole brief before implementing. Work in phase order and pass the applicable acceptance checks before advancing. Verify upstream behavior against candidate versions before coding each phase.

## 1. Stack and release scope

| Concern | Component | Scope |
|---|---|---|
| HTTP routing and TLS | Traefik v3 | The only service with published host ports. |
| OGC API Features | pygeoapi | PostgreSQL collections, read queries including supported CQL2 filters, and explicitly enabled feature transactions at Level 3+. |
| Vector tiles | Martin | PostGIS-backed MVT, TileJSON, a public tile catalog where permitted, and OGC API Tiles access through pygeoapi. |
| Tile caching | Varnish | Level 2+ cache with a freshness bound per published source. |
| Login and roles | fastgeoapi, Keycloak, and OPA | Candidate Level 4 stack. The Phase 4 feasibility check determines whether it can meet the access contract. |
| Database | PostGIS | Bundled demo or operator-managed external database. |

Retire pg_featureserv, pg_tileserv, the optional legacy Compose services, the commented PostgREST and fastgeospatial entries, and the experimental `/buffer` app. Archive sanitized Compose and config files and `functions/featureapi.sql` as historical references. The revamp does not publish the SQL extent and statistics functions. OGC API Processes, PMTiles, MBTiles, and the Traefik and Varnish dashboards are deferred.

### Migration and credential cleanup

- Document `/features` and the old optional `/geoapi` moving to `/api`. Note that the old README's PostgREST `/api` was a separate interface and the service was commented out in the main Compose file. Show how to update feature and tile URLs, including collection IDs, TileJSON URLs, and MapLibre source-layer names. Preserve legacy public IDs through explicit names when they fit the new format and are supported by the chosen component. List the breaking changes and a rollback procedure that preserves the existing database and volumes.
- Map the existing `DATABASE_URL` setup to `PGHOST`, `PGPORT`, `PGDATABASE`, TLS settings, and the credentials for restricted service roles. Include instructions for host-managed databases, such as Docker Desktop or Linux host-gateway addressing. Keep the existing stack recoverable during cutover and document which ports and project names can coexist.
- Remove the tracked `.env.backup`, ignore `.env*` except `.env.example`, and tell the maintainer to rotate credentials committed to the repo. Sanitize credentials from every archived file, including both legacy TOML configs, the old Martin Compose file, and the Varnish dashboard config. Mark the archive as reference material and remove insecure dashboard and backend port publishing from runnable examples. Leave any history rewrite to the maintainer.

## 2. Public routes and configuration

| Route | Backend | Contract |
|---|---|---|
| `/api` | pygeoapi, or the approved Level 4 integration | OGC API Features and OGC tile discovery and delivery for enabled collections. Levels 1–2 accept `GET`, `HEAD`, and `OPTIONS` only. |
| `/tiles` | Martin, via Varnish at Level 2+ | Tile catalog, TileJSON, and `{z}/{x}/{y}` for enabled sources. Restrict the public router to the supported read endpoints and methods. |
| `/auth` | Keycloak at Level 4 | OIDC endpoints required by clients. Keep management endpoints private. |

`PUBLIC_URL` is the browser-facing origin, for example `http://localhost` or `https://gis.example.org`. Use it for public API links and verify that TileJSON URLs use the same public scheme and host. The server-side OGC tile provider uses a separate Docker DNS upstream. Point it at Martin at Level 1 and Varnish at Level 2+. When Martin's pinned version supports `route_prefix: /tiles`, use the same path on both upstreams. Otherwise, set the public TileJSON `base_path`, strip `/tiles` at the edge as needed, and configure the provider and probes to use the actual internal paths. Test both public and internal routing under the chosen configuration.

Keep the database on a private network. Give Traefik egress for ACME and give database clients a route to an external PostGIS host when selected. Attach the app services to the networks they need. Only Traefik publishes ports. Prefer Traefik's file provider with Docker DNS service addresses for these fixed routes, avoiding a Docker socket mount.

### Deployment levels

| Level | Compose files | Behavior |
|---|---|---|
| 1 · Quickstart | `compose.yaml` | Bundled PostGIS demo or external PostGIS, pygeoapi, Martin, and Traefik. Read-only with a loopback bind by default. |
| 2 · Cache | + `compose.cache.yaml` | Varnish serves both direct Martin routes and the OGC API tile provider. Per-source cache policy applies on both paths. |
| 3 · Secure | + `compose.secure.yaml` | HTTPS and guarded feature transactions on named editable collections. |
| 4 · Auth | + `compose.auth.yaml` | Keycloak identities, viewer/editor roles, and per-collection OPA policy, subject to the feasibility check. |

- `make up LEVEL=2` selects the ordered Compose files for the invocation using repeated `-f` flags. Provide the same flags in the Compose-only examples. If using `.env` to set `COMPOSE_FILE` with colon-delimited lists, include `COMPOSE_PATH_SEPARATOR=:` so the list also works in native Windows Compose. Document how explicit flags override `.env` selection.
- Use the same file selection for `make config`, `make smoke`, `make logs`, `make down`, `make refresh`, and `make grants` where applicable. `make reset` asks for confirmation before deleting volumes. Document a Compose-only path for users without Make or Bash on the host.
- `GEOREST_CONFIG_MODE=auto` uses the generator. The bundled demo uses its checked-in collection manifest by default. An external database requires its own manifest and publishes the named collections. The generated service configs are the supported path for Levels 3–4.
- `GEOREST_CONFIG_MODE=manual` mounts operator-supplied pygeoapi and Martin configs verbatim and skips config generation. Support manual mode at Levels 1–2 as a read-only deployment with restricted database roles and explicit Martin sources. Operators manage the consistency of the two catalogs. Level 2 uses the default tile TTL in manual mode. Reject manual mode at Levels 3–4 until there is a defined contract for grants and authorization.

### Publication contract

- Use one validated collection manifest to produce both public catalogs and all per-collection settings. Key `collections` by the stable public collection ID. Each entry names `schema`, `table`, and `geometry`. Publish each schema-qualified table under one collection ID and one selected geometry column. Use the collection ID as the explicit Martin source ID. Accept lowercase letters, digits, hyphens, and underscores, beginning with a letter. Reject reserved Martin IDs, ambiguous definitions, and collisions. Keep table and geometry names separate from public IDs.
- `collections` is the publication allowlist. A table-wide `exclude` matches schema and table and takes precedence. `tiles: false` retains the OGC feature collection and removes both its Martin source and its OGC tile routes. Use `postgres.tables` with named sources and turn off Martin's automatic table and function discovery. A collection that fails validation fails the render with the collection name and cause.
- Match an explicit single-column primary key, or validate an `id_field` override as stable, unique, and non-null. Confirm the selected geometry column and SRID. Derive the storage CRS and a CRS84 bounding box from the data. Use an estimated extent, then a bounded exact fallback, then a world extent with a warning. Provide temporal extent only when a time field is configured. Use SQL identifier quoting for database names and redact connection credentials in diagnostic output.
- Render pygeoapi and Martin configs from the same snapshot. Level 2 consumes the same snapshot for Varnish TTL classes. Levels 3–4 use it for requested grants, and Level 4 uses it for OPA's editable collection IDs. Published collections are read-only by default. A collection outside the publication allowlist is inaccessible.
- Publish additions and changes through a documented refresh command. Creating a table alone leaves both catalogs unchanged. Validate the new snapshot before replacing an existing one. Recreate the affected services together and clear relevant cached objects so a removed collection stops serving through both tile paths. Verify the refresh succeeds before reporting the new snapshot active. Document how to restore the previous config and grant state on failure without restoring database contents.

## 3. Target repository layout

```text
georest-api/
├── compose.yaml
├── compose.cache.yaml
├── compose.secure.yaml
├── compose.auth.yaml             # Phase 4, after the feasibility check
├── .env.example
├── Makefile
├── config/
│   ├── collections.demo.yml
│   ├── collections.example.yml
│   ├── pygeoapi.base.yml
│   ├── martin.base.yml
│   └── traefik/
├── db/
│   └── init/
│       ├── 01-roles.sh
│       └── 02-sample-data.sql
├── images/
│   ├── pygeoapi/                 # Pinned upstream image, entrypoint, georest_config
│   ├── varnish/                  # Pinned upstream image and VCL template
│   └── fastgeoapi/               # Phase 4, if selected
├── auth/                         # Phase 4, if selected
│   ├── keycloak/
│   └── opa/
├── scripts/
│   ├── smoke-test.sh
│   └── htpasswd.sh
├── tests/                        # PostGIS fixtures and local HTTPS/identity fixtures
├── .github/workflows/
│   ├── ci.yml
│   └── publish.yml
├── legacy/
├── docs/
│   ├── VERIFIED.md
│   ├── levels.md
│   ├── configuration.md
│   ├── migration.md
│   ├── security.md
│   └── webgis-clients.md
├── README.md
└── LICENSE
```

## 4. Upstream verification

Record each check in `docs/VERIFIED.md` with the pinned version or commit, source URL, date, result, and any consequence for the implementation. Pin stable, compatible image tags and verify the image platforms used in CI and publishing. Record a digest where it is needed for reproducibility. Use the phase acceptance checks to confirm runtime behavior.

| When | Check |
|---|---|
| Phase 1 | Confirm Martin's explicit table config, route prefix, public TileJSON construction, reserved IDs, and the switch that disables its PostgreSQL tile response cache. Distinguish `base_path` in TileJSON from `route_prefix` on the HTTP server. [Martin configuration](https://maplibre.org/martin/config-file/) · [Martin endpoints](https://maplibre.org/martin/using/) |
| Phase 1 | Confirm the pygeoapi image entrypoint and OpenAPI generation command, proxy prefix behavior, provider connection fields, edit flag, time field, and storage CRS. Confirm `MVT-proxy` tile schemes, format, and origin mapping. pygeoapi 0.24.0 fetches bytes server-side. A dot in its upstream URL path triggers an extension on the tile request, so keep the configured path and source IDs dot-free with that release. [pygeoapi Docker image](https://docs.pygeoapi.io/en/stable/docker.html) · [PostgreSQL provider](https://docs.pygeoapi.io/en/stable/publishing/ogcapi-features.html#postgresql) · [MVT-proxy source](https://github.com/geopython/pygeoapi/blob/0.24.0/pygeoapi/provider/mvt_proxy.py#L134-L177) |
| Phase 1 | Verify Compose merge behavior, the optional database profile, readiness checks, and native Windows overlay selection. Colon-delimited `COMPOSE_FILE` failed with the Windows default. Explicit `-f` flags and `COMPOSE_PATH_SEPARATOR=:` succeeded in a local Compose config check. [Compose environment variables](https://docs.docker.com/compose/how-tos/environment-variables/envvars/#compose_path_separator) |
| Phase 2 | Verify Varnish VCL templating, health probe paths, handling of `Set-Cookie`, `Vary`, authentication, and cache-control directives. [Varnish built-in VCL](https://docs.varnish-software.com/book/vcl/hooks-subroutines-and-built-in-vcl/) |
| Phase 3 | Verify Traefik method rules, priority, trusted forwarded IP behavior, Basic auth `usersFile`, and certificate setup. Verify PostgreSQL role privileges against existing tables, sequences, and table-owner-specific defaults. [Traefik rules and priority](https://doc.traefik.io/traefik/reference/routing-configuration/http/routing/rules-and-priority/) · [Traefik Basic auth](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/basicauth/) · [Traefik ACME](https://doc.traefik.io/traefik/reference/install-configuration/tls/certificate-resolvers/acme/) · [PostgreSQL default privileges](https://www.postgresql.org/docs/current/sql-alterdefaultprivileges.html) |
| Phase 4 | Inspect the candidate fastgeoapi release and locked dependencies. Confirm image or build path, compatible pygeoapi version, settings prefixes and environment variables, context path, config and OpenAPI loading, and extra endpoints. Verify the OPA decision URL, result shape, method, path, and role claims with real Keycloak tokens. Check how anonymous requests, denials, and service outages surface at the edge. [fastgeoapi v0.4.0 auth wiring](https://github.com/geobeyond/fastgeoapi/blob/v0.4.0/app/main.py#L151-L211) · [Dependency lock](https://github.com/geobeyond/fastgeoapi/blob/v0.4.0/uv.lock) · [fastapi-opa 2.0.3](https://pypi.org/project/fastapi-opa/2.0.3/) · [Keycloak reverse proxy](https://www.keycloak.org/server/reverseproxy) |

When upstream differs from the plan, record the difference and verify the intended contract with the pinned version. Change the stated contract only after the maintainer decides on the tradeoff.

## 5. Implementation phases

### Phase 1 · Read-only quickstart

1. Add `compose.yaml` with Traefik, pygeoapi, Martin, a one-shot configuration service, and `postgis` on the `db` profile. Enable `db` in `.env.example`. Bind `127.0.0.1:80` for the default demo and leave the dashboard disabled. Require replacement credentials if the demo uses a non-loopback bind. Use health checks and have the config service wait for database initialization with a timeout. External mode must work with the `db` profile disabled.
2. Add a small demo in a `georest_demo` schema with points, lines, and polygons. Include primary keys, a timestamp field, and a known non-empty tile. Create the `georest_reader` and `georest_editor` logins from environment-supplied passwords. Bootstrap reader access to the demo tables after creating them. Give the editor no write grants at this level. For external databases, supply SQL or a documented provisioning command scoped to selected objects. Application and introspection services use the restricted logins.
3. Build `images/pygeoapi` from the pinned image and use it for the configuration job. Generate the two configs into a shared runtime volume and mount them read-only in consumers. Store passwords in runtime inputs or references supported by the components. `render --check` validates without publishing and `render --dry-run` shows redacted output. Keep the official OpenAPI generation and startup flow in the runtime entrypoint and use the verified `/api` prefix handling.
4. Wire direct tiles and OGC API tiles to Martin and verify their links. Keep Martin UI and function discovery off. Configure CORS and API limits. Include source-backed collection defaults, a time field option, and table comment fallback for titles or descriptions.
5. Implement the credential cleanup and archive changes in section 1. Provide the Level 1 README and smoke tests in this phase.

**Acceptance**

- On a fresh clone, copy `.env.example` to `.env` and run `docker compose up -d --build --wait`. The end-to-end quickstart target is under five minutes on a clean Docker installation. With images available, the services reach readiness within 60 seconds on the test machine.
- `/api/collections` lists the demo collections. A known feature query returns a GeoJSON `FeatureCollection` with a real geometry, and a CQL2 filter returns the expected subset. Following TileJSON and OGC tileset links yields a non-empty MVT for the same known location. Assert the response status, content type, and a non-empty tile at both endpoints.
- A restricted external PostGIS fixture runs with the bundled database disabled. Use two schemas with overlapping table names, an unlisted spatial table, a published collection with `tiles: false`, and an invalid ID fixture. Verify the manifest selects the intended data, invalid input fails validation, and denied sources are unreachable by direct tile URLs. Show an added and a removed collection taking effect through refresh.
- Only Traefik publishes a port, with a loopback bind by default. Anonymous writes fail and leave the database unchanged. Dashboard, admin, and backend operational paths are inaccessible.

### Phase 2 · Tile cache

1. Build the Varnish image from a pinned upstream image and validate the rendered VCL before startup. Point the direct tile router and OGC tile provider at Varnish. Probe Martin on its configured internal path.
2. Cache successful public tile `GET` and `HEAD` requests. Bypass authorization and cookie requests, private tile traffic, and responses marked private or uncacheable. Keep catalog and TileJSON metadata uncached in this phase. Preserve origin and encoding variants where responses differ. Use `X-Cache: HIT`, `MISS`, or `PASS` to make behavior testable. Reject public cache management methods.
3. Derive default and volatile TTL rules from the shared snapshot. Disable Martin's PostgreSQL tile response cache whenever Varnish governs tile freshness. Use the volatile TTL for every source that can be edited and disable grace and stale delivery for those tiles. Set client-facing tile responses to `Cache-Control: no-store` for volatile sources unless both paths can preserve the remaining freshness lifetime. Apply this header downstream of the shared cache. Avoid caching empty or failed tile responses.

**Acceptance**

- With a cold cache, the same non-empty tile goes from `MISS` to `HIT`. Authenticated or cookie-bearing requests show `PASS`, and private responses are uncacheable. Public `PURGE` is refused.
- Warm the cache, update a feature directly in the disposable database, and verify that both public tile paths serve the updated tile by the configured volatile TTL. Use a short fixture TTL and assert the actual tile contents. Refreshing a removed collection makes its previously cached tile inaccessible.

### Phase 3 · HTTPS and guarded feature transactions

1. Add HTTPS on `443` with an HTTP redirect and a Let's Encrypt HTTP-01 resolver for production. Require a public HTTPS `PUBLIC_URL` consistent with `DOMAIN` and an `ACME_EMAIL`. Document the publicly reachable bind address, public DNS, and inbound port `80` as deployment prerequisites. Provide a separate test overlay with a locally trusted certificate and no ACME dependency for development and CI. Apply HSTS on the production HTTPS route.
2. Match `/api` and `/api/` with boundary-aware rules. Use explicit priorities. Route `GET`, `HEAD`, and `OPTIONS` to the read handler. Only documented transaction methods supported by the pinned pygeoapi can reach feature item writes. Deny admin and unsupported methods at the edge. When edits are enabled, require an IP allowlist, Basic auth, or both. If both are configured, enforce both. Use mounted htpasswd files and document the trusted proxy configuration for IP checks. An optional `API_BASIC_AUTH_FILE` protects feature reads and both tile paths. Bypass the shared cache for those private tile routes and allow valid CORS preflights without serving data.
3. Require `GEOREST_ALLOW_EDITS=true` and `editable: true` for each writable collection. Disable writes by default. Reconcile grants on existing volumes and external databases using a separate administrator-run `make grants LEVEL=3` command. Grant the reader the required schema and `SELECT` access. Give the editor the `SELECT`, `INSERT`, `UPDATE`, and `DELETE` privileges needed on the writable tables and `USAGE` on necessary sequences. Revoke stale grants, including when a previously published object is removed. Apply the grants and revocations in one transaction and audit effective privileges, including inherited privileges. If documenting automatic reader grants for new objects in a dedicated schema, specify the creating role.
4. Document the workflow for enabling, changing, and disabling edits on a running deployment. Use the same manifest for database grants and generated providers. Keep DB superuser credentials out of Traefik, Martin, and API services.

**Acceptance**

- CI verifies trusted local TLS and link origins. Test configured IP and Basic auth guards independently, and both together. A disallowed source or invalid credentials cannot mutate data. A permitted caller can create, read back, update, and delete a feature using the supported methods. A published read-only collection rejects mutation.
- With read authentication enabled, verify that feature data and tiles through both routes require valid credentials and that private tiles bypass the shared cache.
- Change a collection from editable to read-only, apply grants and refresh on the same database, and verify both HTTP denial and loss of effective editor write privileges. Repeat on the external fixture. Admin remains inaccessible and only Traefik publishes ports.

### Phase 4 · Role-based access, gated on feasibility

**Feasibility check.** Before adding the production auth overlay, build a disposable integration test using the candidate fastgeoapi, Keycloak, and OPA. fastgeoapi v0.4.0 exposes mutually exclusive API key, JWKS, and OPA modes. Its locked fastapi-opa 2.0.3 OIDC middleware redirects anonymous requests before policy evaluation and returns `401` for policy denials. A Rego rule alone cannot produce the proposed anonymous `GET` and `401`/`403` distinction. Check the released version and demonstrate the full HTTP behavior through Traefik before settling the integration. If the candidate needs an adapter or a behavior change, record the evidence and get a maintainer decision before implementing Level 4. Continue the independent documentation and publishing work for Levels 1–3 if this gate is unresolved.

After the gate passes:

1. Use the proven OIDC and OPA integration for roles. If fastgeoapi replaces pygeoapi, reuse the config generator and validate the pinned versions' config compatibility. Disable the old pygeoapi public route and verify that no alternative route serves writes. Replace Level 3 Basic auth on public routes with Level 4's access policy so protected routes can accept bearer tokens. Keep any explicitly configured Level 4 IP allowlist as an additional write guard.
2. Configure Keycloak with its public HTTPS issuer under `/auth`, a dedicated persistent database and restricted DB role, proxy-header trust restricted to Traefik, and backend HTTP if Traefik terminates TLS. Bootstrap the admin and confidential-client secrets from deployment inputs. Supply a public browser client with exact redirect origins and PKCE and a confidential client for scripts. Provision disposable viewer and editor identities in the test fixture. Publish the OIDC endpoints needed by clients while keeping administration private.
3. Apply default-deny OPA policy to guarded operations. Writes require a valid token with the editor role, a supported method on the collection's feature item route, an effectively editable collection in the active snapshot, and the matching database grant. Test real token issuer, audience, and role claims. Writes fail closed when auth or OPA is unavailable.
4. Public reads and tiles are the default where allowed by the feasibility check. If enabling `GEOREST_PRIVATE_TILES`, enforce authorization at the direct tile edge and protect or disable the OGC tile path. Bypass the shared cache for private traffic. When `GEOREST_PRIVATE_READ=true` and features have tiles, require private tiles as well so geometry and attributes stay protected across both paths.

**Acceptance**

- With public reads, anonymous `GET` works and an anonymous API write returns `401`. A viewer write and an editor write to a read-only collection return `403`. An editor write to an editable collection returns `201` and persists. Invalid tokens and an unavailable policy service cannot cause a write. With private reads, anonymous clients cannot fetch feature data or tile data through either public path.
- Run `opa test` and the complete matrix through Traefik using the local HTTPS fixture, including a browser-like CORS preflight. Verify admin remains private and that the Keycloak issuer and public links use the configured public origin.

### Phase 5 · Documentation and CI

- Put the shortest demo setup in the README. Include the levels table, endpoint URLs, setup for external databases, and a link to the migration guide. Document the manifest, modes, refresh and grants, and per-level settings. Describe how to run the local HTTPS and identity fixtures.
- Provide MapLibre TileJSON, OpenLayers feature and tile, and QGIS OGC API Features and tile examples. For supported auth scenarios, show the required token and how private tiles are handled.
- Add PR checks as phases land. Run lint, generator tests, Compose config checks for every implemented level, and full smoke tests through Traefik. Cover bundled and external DB modes, denied routes, config refresh, cache freshness, and write or role checks for their respective levels. CI fixtures supply credentials, a local CA, and test identities without real public DNS or Let's Encrypt.

### Phase 6 · GHCR publishing preparation

- Prepare a tag-triggered Buildx publish workflow for the custom images that exist, targeting `linux/amd64` and `linux/arm64` after verifying each image's build and platform support. Publish versioned tags to `ghcr.io/${{ github.repository_owner }}/georest-<name>`. Use scoped `GITHUB_TOKEN` permissions and OCI source, version, and accurate license metadata. Check dependency licenses and required notices for distributed images, including the fastapi-opa dependency if the auth image is shipped. Verify the workflow with a build that does not push. The maintainer controls tags and publishing.
- Define explicit local-build and released-image paths. The documented quickstart builds unpublished custom images locally. The released path pulls exact versioned tags. Keep `latest` out of Compose. Ensure that a deferred Level 4 does not block building or publishing completed images.

## 6. Environment example

Use placeholders in the tracked template. Demo credentials are restricted to the loopback demo. Require deployment-specific credentials for the services used in higher levels. Keep local secret files and generated runtime configs out of Git. At implementation, document every supported setting, including optional metadata, paths, test-only switches, and image versions.

```dotenv
# Bundled demo. In external mode, clear COMPOSE_PROFILES and set the PostGIS inputs.
COMPOSE_PROFILES=db
# Optional .env file selection. The separator also works on Windows.
# COMPOSE_PATH_SEPARATOR=:
# COMPOSE_FILE=compose.yaml:compose.cache.yaml

GEOREST_DATASET=demo
GEOREST_CONFIG_MODE=auto
# Set a manifest path for an external database or a custom demo manifest.
GEOREST_COLLECTIONS_FILE=

PUBLIC_URL=http://localhost
GEOREST_BIND_ADDRESS=127.0.0.1
CORS_ORIGINS=*
GEOREST_TITLE=GeoREST API
GEOREST_DESCRIPTION=OGC API Features and vector tiles
DOMAIN=
ACME_EMAIL=

PGHOST=postgis
PGPORT=5432
PGDATABASE=gis
PGSSLMODE=prefer
POSTGRES_PASSWORD=demo-db-password
GEOREST_READER_PASSWORD=demo-reader-password
GEOREST_EDITOR_PASSWORD=demo-editor-password

VARNISH_SIZE=1G
TILE_TTL_DEFAULT=3600
TILE_TTL_VOLATILE=60

GEOREST_ALLOW_EDITS=false
WRITE_ALLOWLIST=
WRITE_BASIC_AUTH_FILE=
API_BASIC_AUTH_FILE=

# Level 4 settings. Document the remaining upstream values after the gate.
GEOREST_PRIVATE_READ=false
GEOREST_PRIVATE_TILES=false
KEYCLOAK_BOOTSTRAP_ADMIN_USERNAME=
KEYCLOAK_BOOTSTRAP_ADMIN_PASSWORD=
```

## 7. Collection manifest example

The explicit IDs below select the objects that are published. An `exclude` entry takes precedence if the same table also appears under `collections`. Use `cache: volatile` for editable sources when edits are enabled. The generator enforces this TTL for writable layers.

```yaml
defaults:
  tiles: true
  cache: static
exclude:
  - schema: survey
    table: internal_observations
collections:
  survey-points:
    schema: survey
    table: observations
    geometry: geom
    title: Survey observations
    description: Public field observations
    keywords: [survey]
    id_field: observation_id
    time_field: observed_at
    editable: true
    cache: volatile
  survey-boundaries:
    schema: survey
    table: boundaries
    geometry: geom
    tiles: false
```

## 8. Working rules

- Keep Level 1 working throughout the restructure. Use small commits and run the affected smoke checks before each commit. Leave pushes and tags to the maintainer.
- Pin upstream dependencies and record the reason for any change of behavior in `docs/VERIFIED.md`. Track unresolved choices there with their impact on acceptance.
- Keep credentials out of the repository, build context, rendered examples, and test output. Use disposable fixtures for write and auth tests.
- Archive work is limited to the migration and security cleanup in section 1. Keep the core release focused on read-only features and tiles, then advance the optional levels in order.

## 9. Definition of done

- [ ] A clean clone starts the bundled demo with the documented one-command Compose quickstart after env setup. The external fixture passes with the bundled database profile disabled.
- [ ] The feature catalog, tile catalog, direct URLs, and refresh behavior match the manifest. Tests fetch a real tile through Martin and OGC API Tiles and verify excluded data stays inaccessible.
- [ ] Only Traefik publishes host ports. The demo defaults to loopback. Legacy credentials are removed from the current tree and the maintainer has a rotation note.
- [ ] Level 2 proves freshness after a data change. Level 3 proves guarded writes and removal of stale grants against an existing database. Each implemented level has a local CI smoke test.
- [ ] Level 4 ships only if the feasibility check and full role matrix pass. If the gate is unresolved, document the blocker and keep Level 4 marked deferred in release materials.
- [ ] Migration, configuration, security, and client documentation matches the deployed routes and modes. `docs/VERIFIED.md` records the upstream facts for every implemented phase.
- [ ] The GHCR workflow builds the completed images for supported platforms in a dry run. No release tag was pushed as part of implementation.
