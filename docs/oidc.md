# Level 4 authentication

Level 4 keeps pygeoapi and Martin behind Traefik. Keycloak issues access tokens from `PUBLIC_URL/auth/realms/georest`. Traefik calls a private authorization service for protected requests. OPA verifies the signature, issuer, audience, expiration, and roles, then uses the active manifest to decide which collections can be edited.

## First start

1. Configure [HTTPS and PostGIS](configuration.md#https-and-editable-collections). Use an HTTPS `PUBLIC_URL` without a trailing slash. Clear `WRITE_BASIC_AUTH_FILE` and `API_BASIC_AUTH_FILE`. Keep `GEOREST_ALLOW_EDITS=false` for initial startup.
2. Set distinct `KEYCLOAK_DB_ADMIN_PASSWORD` and `KEYCLOAK_DB_PASSWORD` values in `.env`. Provide `KC_BOOTSTRAP_ADMIN_USERNAME` and `KC_BOOTSTRAP_ADMIN_PASSWORD` for the initial Keycloak administrator. Keycloak stores identities in the separate `identity-data` volume.
3. Enter a confidential client secret of at least 24 characters when prompted by the realm generator. Use your application's exact callback URL. Repeat `--redirect-uri` for additional callbacks. The generator accepts `KEYCLOAK_CLIENT_SECRET` from its environment for non-interactive use.

   ```sh
   python scripts/init_realm.py --redirect-uri https://maps.example.org/callback
   ```

   The file contains the confidential client secret. The default destination is ignored by Git. With a custom `--output`, set `KEYCLOAK_REALM_FILE` to the same path and protect the parent directory. Keycloak imports the realm on first start. Change a realm already stored in the database through Keycloak administration.

4. Start the stack. The initial Keycloak startup can take longer while it initializes the database and imports the realm.

   ```sh
   docker compose -f compose.yaml -f compose.cache.yaml -f compose.secure.yaml -f compose.auth.yaml up -d --build --wait --wait-timeout 300
   ```

5. Provision users and assign the realm roles `viewer` or `editor`. Use `georest-browser` for authorization code with PKCE S256 and `georest-script` for client credentials. Assign a realm role to `service-account-georest-script` before using its token for protected operations. For more than one automation, create separate confidential clients with the `georest-api` audience and assign roles independently.

## Administration and grants

Run `docker compose` with the four Level 4 `-f` flags followed by `exec keycloak sh`. Inside the container, the bootstrap account can use the bundled administration CLI. The login command prompts for the administrator password.

```sh
kcadm=/opt/keycloak/bin/kcadm.sh
"$kcadm" config credentials --server http://localhost:8080/auth --realm master --user "$KC_BOOTSTRAP_ADMIN_USERNAME"
"$kcadm" create users -r georest -s username=alice -s enabled=true
"$kcadm" add-roles -r georest --uusername alice --rolename editor
"$kcadm" add-roles -r georest --uusername service-account-georest-script --rolename viewer
rm -f "$HOME/.keycloak/kcadm.config"
```

Set an initial password or connect an identity provider for browser users through Keycloak. Create permanent administration, remove the temporary account, and remove its bootstrap variables from `.env` after provisioning. The public proxy exposes the configured realm's login and OIDC endpoints and the resources they use. [Keycloak administration CLI](https://www.keycloak.org/docs/latest/server_admin/#admin-cli), [Keycloak reverse proxy](https://www.keycloak.org/server/reverseproxy)

Keycloak resolves its trusted `traefik` proxy address on startup. Restart Keycloak if the Traefik container is replaced and its address changes.

To enable writes, mark selected entries `editable: true`, set `GEOREST_ALLOW_EDITS=true`, and reconcile the database grants before refreshing. Export `GEOREST_ADMIN_DSN` as described in the grant setup. [Grant setup](configuration.md#https-and-editable-collections)

```sh
make grants LEVEL=4
make refresh LEVEL=4
```

Use the same sequence to remove write access. For Compose commands without Make, use all four `-f` flags in the grant command and pass those flags to `python scripts/refresh.py`. A configured `WRITE_ALLOWLIST` is enforced in addition to the editor role.

## Access policy

| Request | Required access |
|---|---|
| Feature or tile read, default settings | Public |
| Feature read with `GEOREST_PRIVATE_READ=true` | `viewer` or `editor` |
| Direct or OGC tile request with `GEOREST_PRIVATE_TILES=true` | `viewer` or `editor` |
| Feature POST, PUT, or DELETE | `editor`, an editable collection, and the corresponding database grant |

When any published collection has tiles, private feature reads also require `GEOREST_PRIVATE_TILES=true`. Private tiles bypass Varnish caching on both paths. Put your browser app's origin in `CORS_ORIGINS` so Traefik can answer preflights before requiring a token.

Protected routes return `401` for missing or invalid tokens, `403` for an authenticated caller without permission, and a server error if the policy service cannot be reached. Public reads remain available during an auth outage. Signed access tokens remain valid until expiry. OPA caches the realm's public signing keys for 30 seconds, so allow for that interval during key rotation.

Run `python tests/oidc_deployment.py` to check this configuration with local HTTPS, an isolated database and realm, and real Keycloak tokens. [Client examples](webgis-clients.md#openid-connect)
