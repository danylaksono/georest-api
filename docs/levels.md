# Deployment levels

Use the same `-f` flags and project name for startup, refresh, grants, logs, and shutdown.

| Level | Compose-only startup |
|---|---|
| 1 · Quickstart | `docker compose -f compose.yaml up -d --build --wait` |
| 2 · Cache | `docker compose -f compose.yaml -f compose.cache.yaml up -d --build --wait` |
| 3 · Secure | `docker compose -f compose.yaml -f compose.cache.yaml -f compose.secure.yaml up -d --build --wait` |

Level 1 starts the bundled read-only demo on loopback. An external deployment publishes only collections named in its manifest. Level 2 adds Varnish to both public tile paths. Level 3 requires an HTTPS origin and deployment credentials. Writes are disabled until you mark a collection editable, set a write guard, reconcile the database grants, and refresh. [Configuration](configuration.md)

Level 4 is deferred. The feasibility probe reproduced login redirects for anonymous requests and `401` for a denied viewer write. Run `python tests/auth_probe.py` to reproduce the matrix with a disposable Keycloak realm. [Verification notes](VERIFIED.md)

Run the local checks from the repository root with Docker and Python available.

```sh
python tests/deployment.py demo
python tests/deployment.py external
python tests/deployment.py demo --level 2
python tests/deployment.py external --level 2
python tests/secure_deployment.py
python tests/secure_deployment.py --external
```

The HTTPS fixtures use OpenSSL to generate a locally trusted certificate. They create disposable Compose projects and use loopback ports. The secure fixture exercises writes, so use it in place of the demo smoke script for HTTPS and permission checks.

For exact version tags and build checks, see the [image release guide](releases.md).
