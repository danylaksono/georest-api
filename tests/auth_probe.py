"""Reproduce the stock fastgeoapi OIDC and OPA status behavior through Traefik."""

import http.client
import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode

from deployment import command, fixture_port

AUTH_PATH = "/auth/realms/georest"
ITEMS = "/api/collections/obs/items"
CLIENT = "georest-fixture"


def realm(secret, users):
    return {
        "realm": "georest", "enabled": True, "sslRequired": "none",
        "roles": {"realm": [{"name": role} for role in users]},
        "clients": [{
            "clientId": CLIENT, "secret": secret, "enabled": True,
            "publicClient": False, "directAccessGrantsEnabled": True,
            "protocol": "openid-connect",
            "protocolMappers": [{
                "name": "roles for probe", "protocol": "openid-connect",
                "protocolMapper": "oidc-usermodel-realm-role-mapper",
                "config": {"claim.name": "roles", "jsonType.label": "String",
                           "multivalued": "true", "userinfo.token.claim": "true"},
            }],
        }],
        "users": [
            {"username": role, "enabled": True, "emailVerified": True,
             "firstName": "Fixture", "lastName": role, "email": f"{role}@example.test",
             "realmRoles": [role],
             "credentials": [{"type": "password", "value": password, "temporary": False}]}
            for role, password in users.items()
        ],
    }


def request(port, path, method="GET", headers=None, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
    try:
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def wait_for(port, path, status):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            if request(port, path)[0] == status:
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(1)
    raise RuntimeError(f"probe did not receive HTTP {status} from {path}")


def token(port, role, password, secret):
    payload = urlencode({"grant_type": "password", "client_id": CLIENT, "client_secret": secret,
                         "username": role, "password": password, "scope": "openid"})
    status, body = request(
        port, AUTH_PATH + "/protocol/openid-connect/token", "POST",
        {"Content-Type": "application/x-www-form-urlencoded"}, payload,
    )
    assert status == 200, f"Keycloak token request for {role}: {status}"
    return json.loads(body)["access_token"]


def main():
    port = fixture_port()
    secret = secrets.token_urlsafe(24)
    users = {role: secrets.token_urlsafe(24) for role in ("viewer", "editor")}
    project = f"georest-auth-probe-{secrets.token_hex(4)}"
    compose = ["docker", "compose", "-p", project, "-f", "tests/compose.auth-probe.yaml"]
    command("docker", "buildx", "build", "--load", "--tag", "georest-fastgeo-probe:0.4.0",
            "https://github.com/geobeyond/fastgeoapi.git#f6d860a8c74c091fcc9b1f4feb5d33d7e4d3db24")
    with tempfile.TemporaryDirectory(prefix="georest-auth-") as directory:
        file = Path(directory) / "realm.json"
        file.write_text(json.dumps(realm(secret, users)), encoding="utf-8")
        env = dict(os.environ, GEOREST_PROBE_PORT=str(port), GEOREST_PROBE_REALM=file.as_posix(),
                   GEOREST_PROBE_CLIENT_SECRET=secret)
        def dc(*args):
            return command(*compose, *args, env=env)

        try:
            dc("up", "-d", "edge", "keycloak", "opa")
            discovery = AUTH_PATH + "/.well-known/openid-configuration"
            wait_for(port, discovery, 200)
            _, metadata = request(port, discovery)
            assert json.loads(metadata)["userinfo_endpoint"] == "http://edge" + AUTH_PATH + "/protocol/openid-connect/userinfo"
            dc("exec", "-T", "opa", "/opa", "test", "/policy")
            dc("up", "-d", "fastgeoapi")
            wait_for(port, "/api/collections?f=json", 303)
            viewer = {"Authorization": f"Bearer {token(port, 'viewer', users['viewer'], secret)}"}
            info, body = request(port, AUTH_PATH + "/protocol/openid-connect/userinfo", headers=viewer)
            assert info == 200, f"Keycloak UserInfo returned {info}: {body.decode(errors='replace')}"
            assert "viewer" in json.loads(body).get("roles", [])
            status = {
                "anonymous GET": request(port, "/api/collections?f=json")[0],
                "anonymous POST": request(port, ITEMS, "POST")[0],
                "viewer GET": request(port, "/api/collections?f=json", headers=viewer)[0],
                "viewer POST": request(port, ITEMS, "POST", headers=viewer)[0],
            }
            print(json.dumps(status, indent=2))
            assert status == {
                "anonymous GET": 303, "anonymous POST": 303, "viewer GET": 200, "viewer POST": 401,
            }, "stock auth behavior changed, reevaluate the Level 4 gate"
        except (AssertionError, RuntimeError, subprocess.CalledProcessError):
            output = command(*compose, "logs", "--tail", "25", env=env, capture_output=True).stdout
            for value in (secret, *users.values()):
                output = output.replace(value, "<redacted>")
            print(output)
            raise
        finally:
            dc("down", "--volumes")


if __name__ == "__main__":
    main()
