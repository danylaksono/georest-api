"""Exercise Level 3 with locally trusted TLS and disposable credentials."""

import argparse
import base64
import hashlib
import http.client
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urljoin

from deployment import (
    command,
    fixture_port,
    layer,
    load_external_database,
    ports_are_private,
    project_env,
    start,
)
from smoke_test import json_response, request  # noqa: E402


def local_tls(directory):
    openssl = shutil.which("openssl")
    if not openssl and os.name == "nt":
        openssl = "C:/Program Files/Git/usr/bin/openssl.exe"
    command(
        openssl or "openssl", "req", "-new", "-x509", "-newkey", "rsa:2048",
        "-nodes", "-days", "1", "-subj", "/CN=localhost",
        "-addext", "subjectAltName=DNS:localhost",
        "-keyout", str(directory / "localhost-key.pem"),
        "-out", str(directory / "localhost.pem"),
        stderr=subprocess.DEVNULL,
    )


def private_auth(directory):
    password = secrets.token_urlsafe(20)
    digest = base64.b64encode(hashlib.sha1(password.encode()).digest()).decode()
    (directory / "fixture.htpasswd").write_text(f"fixture:{{SHA}}{digest}\n", encoding="utf-8")
    token = base64.b64encode(f"fixture:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def feature_request(url, method="POST", headers=None, name="Inserted", feature_id=None):
    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [1.15, 1.15]},
        "properties": {"name": name, "observed_at": "2025-03-01T00:00:00Z"},
    }
    if feature_id is not None:
        feature["id"] = feature_id
    return request(
        url, method=method,
        headers={"Content-Type": "application/geo+json", **(headers or {})},
        data=json.dumps(feature).encode(),
    )


def verify_redirect(env):
    connection = http.client.HTTPConnection("127.0.0.1", int(env["GEOREST_HTTP_PORT"]), timeout=10)
    try:
        connection.request("GET", "/api?f=json", headers={"Host": "localhost"})
        response = connection.getresponse()
        assert response.status in (301, 302, 307, 308)
        assert response.getheader("Location") == env["PUBLIC_URL"] + "/api?f=json"
    finally:
        connection.close()


def acl(compose, env, sql, *, external_name=None):
    database = ["docker", "exec", external_name] if external_name else [*compose, "exec", "-T", "postgis"]
    return command(
        *database, "psql", "-U", "postgres", "-d", "gis", "-v", "ON_ERROR_STOP=1", "-Atc", sql,
        env=env, stdout=subprocess.PIPE,
    ).stdout.strip()


def check_editable(compose, env, headers, *, external_name=None):
    origin = env["PUBLIC_URL"]
    items = f"{origin}/api/collections/points/items"
    table = "east.points" if external_name else "georest_demo.demo_points"
    patch_manifest = Path(env["GEOREST_COLLECTIONS_FILE"])

    def grants():
        command(
            *compose, "run", "--rm", "--no-deps", "-e", "GEOREST_ADMIN_DSN",
            "configure", "grants", env=env,
        )

    def refresh():
        command(sys.executable, "scripts/refresh.py", *compose[2:], env=env)

    env.update(GEOREST_ALLOW_EDITS="true", WRITE_BASIC_AUTH_FILE="fixture.htpasswd")
    grants()
    refresh()
    assert acl(compose, env, f"SELECT has_table_privilege('georest_editor','{table}','INSERT')",
               external_name=external_name) == "t"
    assert feature_request(items)[0] == 401
    assert feature_request(items, headers={"Authorization": "Basic aW52YWxpZDppbnZhbGlk"})[0] == 401
    status, response_headers, body = feature_request(items, headers=headers)
    assert status == 201, body
    location = urljoin(origin, response_headers["Location"])
    assert location.startswith(origin + "/api/collections/points/items/")
    feature_id = json_response(location + "?f=json")["id"]
    status, _, body = feature_request(location, "PUT", headers, "Updated", feature_id)
    assert status in (200, 204), body
    assert json_response(location + "?f=json")["properties"]["name"] == "Updated"
    assert request(location, method="DELETE", headers=headers)[0] in (200, 204)
    assert request(location)[0] == 404
    assert feature_request(f"{origin}/api/collections/readonly/items", headers=headers)[0] in (403, 404, 405)

    if not external_name:
        env.update(WRITE_ALLOWLIST="192.0.2.1/32")
        refresh()
        assert feature_request(items, headers=headers)[0] == 403
        env.update(WRITE_ALLOWLIST="0.0.0.0/0,::/0", WRITE_BASIC_AUTH_FILE="")
        refresh()
        assert feature_request(items, name="IP-only")[0] == 201
        env.update(WRITE_BASIC_AUTH_FILE="fixture.htpasswd", API_BASIC_AUTH_FILE="fixture.htpasswd")
        refresh()
        assert feature_request(items)[0] == 401
        assert feature_request(items, headers=headers, name="Both guards")[0] == 201

        for path in ("/api/collections/points/items", "/tiles/points/4/8/7",
                     "/api/collections/points/tiles/WebMercatorQuad/4/7/8?f=pbf"):
            assert request(origin + path)[0] == 401
            status, response_headers, _ = request(origin + path, headers=headers)
            assert status == 200 and response_headers["Cache-Control"] == "no-store"
        assert request(origin + "/tiles/points/4/8/7", headers=headers)[1]["X-Cache"] == "PASS"
        status, response_headers, _ = request(
            items, method="OPTIONS",
            headers={"Origin": "https://client.test", "Access-Control-Request-Method": "POST",
                     "Access-Control-Request-Headers": "Authorization,Content-Type"},
        )
        assert status == 200 and response_headers["Access-Control-Allow-Origin"] == "https://client.test"

    manifest = json.loads(patch_manifest.read_text(encoding="utf-8"))
    manifest["collections"]["points"]["editable"] = False
    patch_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    grants()
    refresh()
    assert feature_request(items, headers=headers)[0] in (403, 404, 405)
    assert acl(compose, env, f"SELECT has_table_privilege('georest_editor','{table}','INSERT,UPDATE,DELETE')",
               external_name=external_name) == "f"
    assert acl(compose, env, f"SELECT has_sequence_privilege('georest_editor', "
               f"pg_get_serial_sequence('{table}','id'), 'USAGE')",
               external_name=external_name) == "f"
    assert request(origin + "/api/admin", headers=headers)[0] in (403, 404)


def secure_fixture(external):
    name = f"georest-secure-{secrets.token_hex(4)}"
    env = project_env()
    https_port = str(fixture_port())
    env.update(
        PUBLIC_URL=f"https://localhost:{https_port}", GEOREST_HTTPS_PORT=https_port, DOMAIN="localhost",
        POSTGRES_PASSWORD=secrets.token_urlsafe(24), POSTGRES_DB="gis",
        GEOREST_READER_PASSWORD=secrets.token_urlsafe(24), GEOREST_EDITOR_PASSWORD=secrets.token_urlsafe(24),
        GEOREST_ALLOW_EDITS="false", CORS_ORIGINS="https://client.test",
    )
    compose = [
        "docker", "compose", "--env-file", ".env.example", "-p", name, "-f", "compose.yaml",
        "-f", "compose.cache.yaml", "-f", "compose.secure.yaml", "-f", "tests/compose.local-tls.yaml",
    ]
    origin = env["PUBLIC_URL"]
    if external:
        compose += ["-f", "tests/compose.external.yaml"]
        env.update(COMPOSE_PROFILES="", GEOREST_DATASET="external", GEOREST_TEST_NETWORK=name,
                   PGHOST="external-db", PGDATABASE="gis", PGSSLMODE="disable")
        collections = {
            "points": layer("east", "points", editable=True),
            "readonly": layer("west", "points"),
        }
    else:
        collections = {
            "points": layer("georest_demo", "demo_points", editable=True),
            "readonly": layer("georest_demo", "demo_lines"),
        }
    pg_host = "external-db" if external else "postgis"
    env["GEOREST_ADMIN_DSN"] = f"postgresql://postgres:{env['POSTGRES_PASSWORD']}@{pg_host}:5432/gis"

    with tempfile.TemporaryDirectory(prefix="georest-tls-") as temp:
        directory = Path(temp)
        local_tls(directory)
        headers = private_auth(directory)
        manifest = directory / "collections.yml"
        manifest.write_text(json.dumps({"collections": collections}), encoding="utf-8")
        env.update(GEOREST_TEST_TLS_DIR=directory.as_posix(), GEOREST_AUTH_DIR=directory.as_posix(),
                   GEOREST_COLLECTIONS_FILE=manifest.as_posix())
        prior_ca = os.environ.get("SSL_CERT_FILE")
        os.environ["SSL_CERT_FILE"] = str(directory / "localhost.pem")
        try:
            if external:
                command("docker", "network", "create", name)
                load_external_database(f"{name}-db", env)
            start(compose, env)
            ports_are_private(compose, env, env["GEOREST_HTTP_PORT"], https_port)
            verify_redirect(env)
            service = json_response(origin + "/api?f=json")
            assert any(link["href"].startswith(origin + "/api") for link in service["links"])
            check_editable(compose, env, headers, external_name=f"{name}-db" if external else None)
        finally:
            if prior_ca is None:
                os.environ.pop("SSL_CERT_FILE", None)
            else:
                os.environ["SSL_CERT_FILE"] = prior_ca
            command(*compose, "down", "--volumes", env=env)
            if external:
                subprocess.run(["docker", "stop", f"{name}-db"], check=False)
                command("docker", "network", "rm", name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external", action="store_true")
    args = parser.parse_args()
    secure_fixture(args.external)
    print("Level 3 HTTPS, CRUD, and grant reconciliation passed")
