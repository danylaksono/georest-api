# Deployment levels

Use the same `-f` flags and project name for startup, refresh, grants, logs, and shutdown.

| Level | Compose-only startup |
|---|---|
| 1 · Quickstart | `docker compose -f compose.yaml up -d --build --wait` |
| 2 · Cache | `docker compose -f compose.yaml -f compose.cache.yaml up -d --build --wait` |
| 3 · Secure | `docker compose -f compose.yaml -f compose.cache.yaml -f compose.secure.yaml up -d --build --wait` |
| 4 · Roles | `docker compose -f compose.yaml -f compose.cache.yaml -f compose.secure.yaml -f compose.auth.yaml up -d --build --wait` |

Level 1 starts the bundled read-only demo on loopback. An external deployment publishes only collections named in its manifest. Level 2 adds Varnish to both public tile paths. Level 3 requires an HTTPS origin and deployment credentials. Writes are disabled until you mark a collection editable, set a write guard, reconcile the database grants, and refresh. [Configuration](configuration.md)

Level 4 keeps public feature and tile reads by default. It uses Keycloak access tokens and OPA for edits and optional private reads. Configure the realm and identity database before starting. [Level 4 setup](oidc.md)

Run the local checks from the repository root with Docker and Python available.

```sh
python tests/deployment.py demo
python tests/deployment.py external
python tests/deployment.py demo --level 2
python tests/deployment.py external --level 2
python tests/secure_deployment.py
python tests/secure_deployment.py --external
python tests/oidc_deployment.py
```

The HTTPS fixtures use OpenSSL to generate a locally trusted certificate. They create disposable Compose projects and use loopback ports. Use these fixtures for HTTPS and write permissions. `make smoke LEVEL=4` runs the disposable identity fixture, including browser PKCE, OPA policy tests, and protected feature and tile requests.

For exact version tags and build checks, see the [image release guide](releases.md).
