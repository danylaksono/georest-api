"""Exercise production Level 4 routing through Traefik with real Keycloak tokens."""

import base64
import hashlib
import http.cookiejar
import json
import os
import secrets
import ssl
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    HTTPSHandler,
    build_opener,
)

from deployment import command, fixture_port, layer, ports_are_private, project_env
from init_realm import BROWSER_CLIENT, SCRIPT_CLIENT, realm_config
from secure_deployment import acl, feature_request, local_tls, verify_redirect
from smoke_test import json_response, request, tile_bytes

REALM = "/auth/realms/georest"
LOGIN = REALM + "/protocol/openid-connect"
CALLBACK = "http://127.0.0.1:42566/callback"
ITEMS = "/api/collections/points/items"
READONLY = "/api/collections/readonly/items"
TILES = ("/tiles/points/4/8/7", "/api/collections/points/tiles/WebMercatorQuad/4/7/8?f=pbf")


class LoginForm(HTMLParser):
    action = None

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag == "form" and fields.get("id") == "kc-form-login":
            self.action = fields["action"]


def bearer(origin, client, secret=None, **grant):
    parameters = {"client_id": client, **grant}
    if secret:
        parameters["client_secret"] = secret
    status, _, body = request(origin + LOGIN + "/token", method="POST",
                              headers={"Content-Type": "application/x-www-form-urlencoded"},
                              data=urlencode(parameters).encode())
    assert status == 200, f"Keycloak token endpoint returned {status} for {client}"
    return {"Authorization": "Bearer " + json.loads(body)["access_token"]}


class CallbackRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl.startswith(CALLBACK + "?"):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def browser_token(origin, password):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe()
    parameters = {"client_id": BROWSER_CLIENT, "redirect_uri": CALLBACK, "response_type": "code",
                  "scope": "openid", "state": state}
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()), CallbackRedirect(),
                          HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(origin + LOGIN + "/auth?" + urlencode(parameters), timeout=10):
            raise AssertionError("Keycloak accepted a browser authorization request without PKCE")
    except HTTPError as error:
        assert error.code == 400 or "error=invalid_request" in error.headers.get("Location", "")
    parameters.update(code_challenge=challenge, code_challenge_method="S256")
    with opener.open(origin + LOGIN + "/auth?" + urlencode(parameters), timeout=10) as response:
        form = LoginForm()
        form.feed(response.read().decode())
    assert form.action and form.action.startswith(origin + REALM + "/login-actions/")
    try:
        with opener.open(form.action, data=urlencode({"username": "viewer", "password": password}).encode(), timeout=10):
            raise AssertionError("Keycloak login did not redirect to the configured callback")
    except HTTPError as redirect:
        assert redirect.code in (302, 303)
        callback = redirect.headers["Location"]
        assert callback.startswith(CALLBACK + "?")
        query = parse_qs(urlsplit(callback).query)
        assert query["state"] == [state]
    return bearer(origin, BROWSER_CLIENT, grant_type="authorization_code", code=query["code"][0],
                  redirect_uri=CALLBACK, code_verifier=verifier)


def verify_tokens(origin, editor, viewer, wrong_audience, script):
    items = origin + ITEMS
    status, headers, _ = feature_request(items)
    assert status == 401 and headers["WWW-Authenticate"].startswith("Bearer ")
    assert feature_request(items, headers=viewer)[0] == 403
    assert feature_request(items, headers=script)[0] == 403  # No service account role yet.
    assert feature_request(items, headers=wrong_audience)[0] == 401
    prefix, signature = editor["Authorization"].rsplit(".", 1)
    changed = "A" if signature[0] != "A" else "B"
    invalid = {"Authorization": f"{prefix}.{changed}{signature[1:]}"}
    assert feature_request(items, headers=invalid)[0] == 401
    assert feature_request(origin + READONLY, headers=editor)[0] == 403
    assert feature_request(items, method="PATCH", headers=editor)[0] in (404, 405)
    status, headers, _ = feature_request(items, headers=editor)
    assert status == 201, f"editor create returned {status}"
    location = urljoin(origin, headers["Location"])
    assert location.startswith(items + "/")
    feature_id = json_response(location + "?f=json")["id"]
    assert feature_request(location, "PUT", editor, "Updated through OIDC", feature_id)[0] in (200, 204)
    assert json_response(location + "?f=json")["properties"]["name"] == "Updated through OIDC"
    assert feature_request(location, "DELETE", editor)[0] in (200, 204)
    assert request(location)[0] == 404


def verify_private(origin, viewer, *, private_features):
    features = origin + ITEMS
    assert request(features)[0] == (401 if private_features else 200)
    assert request(features, headers=viewer)[0] == 200
    for path in TILES:
        assert request(origin + path)[0] == 401
        status, headers, body = request(origin + path, headers=viewer)
        assert status == 200 and body and headers.get_content_type() in {
            "application/x-protobuf", "application/vnd.mapbox-vector-tile",
        }
        assert headers["Cache-Control"] == "private, no-store"
        assert headers["X-Cache"] == ("PASS" if path.startswith("/tiles/") else None)
    status, headers, body = request(
        features, method="OPTIONS", headers={"Origin": "https://client.test",
        "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Authorization,Content-Type"},
    )
    assert status == 200 and headers["Access-Control-Allow-Origin"] == "https://client.test" and not body


def main():
    name = f"georest-oidc-{secrets.token_hex(4)}"
    env = project_env()
    https_port = str(fixture_port())
    origin = f"https://localhost:{https_port}"
    env.update(PUBLIC_URL=origin, GEOREST_HTTPS_PORT=https_port, DOMAIN="localhost",
               POSTGRES_PASSWORD=secrets.token_urlsafe(), KEYCLOAK_DB_PASSWORD=secrets.token_urlsafe(),
               KEYCLOAK_DB_ADMIN_PASSWORD=secrets.token_urlsafe(), GEOREST_READER_PASSWORD=secrets.token_urlsafe(),
               GEOREST_EDITOR_PASSWORD=secrets.token_urlsafe(), CORS_ORIGINS="https://client.test",
               GEOREST_ALLOW_EDITS="false", COMPOSE_PROFILES="db", KC_BOOTSTRAP_ADMIN_USERNAME="temp-admin",
               KC_BOOTSTRAP_ADMIN_PASSWORD=secrets.token_urlsafe())
    env["GEOREST_ADMIN_DSN"] = f"postgresql://postgres:{env['POSTGRES_PASSWORD']}@postgis:5432/gis"
    compose = ["docker", "compose", "--env-file", ".env.example", "-p", name, "-f", "compose.yaml",
               "-f", "compose.cache.yaml", "-f", "compose.secure.yaml", "-f", "compose.auth.yaml",
               "-f", "tests/compose.local-tls.yaml"]
    secrets_by_user = {role: secrets.token_urlsafe() for role in ("viewer", "editor")}
    client_secret = secrets.token_urlsafe()

    def dc(*args, **kwargs):
        return command(*compose, *args, env=env, **kwargs)

    def grants():
        dc("run", "--rm", "--no-deps", "-e", "GEOREST_ADMIN_DSN", "configure", "grants")

    def refresh():
        command(sys.executable, "scripts/refresh.py", *compose[2:], env=env)

    with tempfile.TemporaryDirectory(prefix="georest-oidc-") as temp:
        directory = Path(temp)
        local_tls(directory)
        manifest = directory / "collections.yml"
        collections = {"points": layer("georest_demo", "demo_points", editable=True),
                       "readonly": layer("georest_demo", "demo_lines")}
        manifest.write_text(json.dumps({"collections": collections}), encoding="utf-8")
        realm = realm_config([CALLBACK], client_secret)
        realm["clients"] += [
            {"clientId": client, "protocol": "openid-connect", "publicClient": False, "secret": client_secret,
             "directAccessGrantsEnabled": True, "standardFlowEnabled": False, "protocolMappers": mappers}
            for client, mappers in (("fixture-password", realm["clients"][0]["protocolMappers"]), ("fixture-other", []))
        ]
        realm["users"] = [
            {"username": role, "enabled": True, "firstName": "Fixture", "lastName": role, "emailVerified": True,
             "email": f"{role}@example.test", "realmRoles": [role],
             "credentials": [{"type": "password", "value": value, "temporary": False}]}
            for role, value in secrets_by_user.items()
        ]
        realm_file = directory / "realm.json"
        realm_file.write_text(json.dumps(realm), encoding="utf-8")
        env.update(KEYCLOAK_REALM_FILE=realm_file.as_posix(), GEOREST_TEST_TLS_DIR=directory.as_posix(),
                   GEOREST_AUTH_DIR=directory.as_posix(), GEOREST_COLLECTIONS_FILE=manifest.as_posix())
        prior_ca = os.environ.get("SSL_CERT_FILE")
        os.environ["SSL_CERT_FILE"] = str(directory / "localhost.pem")
        try:
            dc("up", "-d", "--build", "--wait", "--wait-timeout", "300")
            env["GEOREST_ALLOW_EDITS"] = "true"
            grants()
            refresh()
            dc("exec", "-T", "opa", "/opa", "test", "/policy")
            ports_are_private(compose, env, env["GEOREST_HTTP_PORT"], https_port)
            verify_redirect(env)
            assert dc("exec", "-T", "identity-db", "psql", "-U", "postgres", "-d", "keycloak", "-Atc",
                      "SELECT rolsuper FROM pg_roles WHERE rolname = 'keycloak'", capture_output=True).stdout.strip() == "f"
            metadata = json_response(origin + REALM + "/.well-known/openid-configuration")
            assert metadata["issuer"] == origin + REALM and metadata["token_endpoint"] == origin + LOGIN + "/token"
            for path in ("/auth/admin/", "/auth/realms/master/.well-known/openid-configuration", "/api/admin"):
                assert request(origin + path)[0] == 404
            assert request(origin + ITEMS)[0] == 200
            for tile in TILES:
                assert tile_bytes(origin + tile)
            viewer = browser_token(origin, secrets_by_user["viewer"])
            editor_credentials = {"grant_type": "password", "username": "editor", "password": secrets_by_user["editor"]}
            editor = bearer(origin, "fixture-password", client_secret, **editor_credentials)
            wrong_audience = bearer(origin, "fixture-other", client_secret, **editor_credentials)
            script = bearer(origin, SCRIPT_CLIENT, client_secret, grant_type="client_credentials")
            verify_tokens(origin, editor, viewer, wrong_audience, script)

            dc("exec", "-T", "keycloak", "sh", "-ec", """
                kcadm=/opt/keycloak/bin/kcadm.sh
                "$kcadm" config credentials --server http://localhost:8080/auth --realm master \
                  --user "$KC_BOOTSTRAP_ADMIN_USERNAME" --password "$KC_BOOTSTRAP_ADMIN_PASSWORD"
                "$kcadm" add-roles -r georest --uusername service-account-georest-script --rolename viewer
                rm -f "$HOME/.keycloak/kcadm.config"
                """)
            script = bearer(origin, SCRIPT_CLIENT, client_secret, grant_type="client_credentials")

            before = json_response(origin + ITEMS)["numberMatched"]
            dc("stop", "opa")
            assert feature_request(origin + ITEMS, headers=editor)[0] == 503
            assert json_response(origin + ITEMS)["numberMatched"] == before
            dc("up", "-d", "--no-deps", "--wait", "opa")
            dc("stop", "authorizer")
            assert feature_request(origin + ITEMS, headers=editor)[0] >= 500
            assert json_response(origin + ITEMS)["numberMatched"] == before
            dc("up", "-d", "--no-deps", "--wait", "authorizer")

            env.update(GEOREST_PRIVATE_TILES="true", WRITE_ALLOWLIST="192.0.2.1/32")
            refresh()
            verify_private(origin, viewer, private_features=False)
            assert feature_request(origin + ITEMS, headers=editor)[0] == 403
            env.update(GEOREST_PRIVATE_READ="true", GEOREST_PRIVATE_TILES="false")
            rejected = dc("run", "--rm", "--no-deps", "configure", "render", "--check",
                          capture_output=True, check=False)
            assert rejected.returncode and "require GEOREST_PRIVATE_TILES" in rejected.stderr
            env.update(GEOREST_PRIVATE_TILES="true", WRITE_ALLOWLIST="")
            collections["points"]["editable"] = False
            manifest.write_text(json.dumps({"collections": collections}), encoding="utf-8")
            grants()
            refresh()
            verify_private(origin, viewer, private_features=True)
            assert request(origin + ITEMS, headers=script)[0] == 200
            assert feature_request(origin + ITEMS, headers=editor)[0] == 403
            assert acl(compose, env, "SELECT has_table_privilege('georest_editor','georest_demo.demo_points','INSERT')") == "f"
        except (AssertionError, OSError, subprocess.CalledProcessError):
            log = dc("logs", "--tail", "30", capture_output=True).stdout
            for value in (client_secret, *secrets_by_user.values(), *(env[key] for key in (
                    "POSTGRES_PASSWORD", "KEYCLOAK_DB_PASSWORD", "KEYCLOAK_DB_ADMIN_PASSWORD",
                    "GEOREST_READER_PASSWORD", "GEOREST_EDITOR_PASSWORD", "KC_BOOTSTRAP_ADMIN_PASSWORD"))):
                log = log.replace(value, "<redacted>")
            print(log)
            raise
        finally:
            if prior_ca is None:
                os.environ.pop("SSL_CERT_FILE", None)
            else:
                os.environ["SSL_CERT_FILE"] = prior_ca
            dc("down", "--volumes")
    print("Level 4 HTTPS, Keycloak PKCE and bearer tokens, OPA, private reads, and writes passed")


if __name__ == "__main__":
    main()
