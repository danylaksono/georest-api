"""Run the Compose acceptance fixtures in disposable projects."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from smoke_test import (  # noqa: E402
    collection_ids,
    json_response,
    request,
    smoke,
    tile_bytes,
    tile_ids,
)


def command(*args, **options):
    return subprocess.run(args, cwd=ROOT, text=True, check=True, **options)


def start(compose, env):
    try:
        command(*compose, "up", "-d", "--build", "--wait", "--wait-timeout", "60", env=env)
    except subprocess.CalledProcessError:
        command(*compose, "logs", "--tail", "30", env=env)
        raise


def fixture_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def project_env():
    env = {key: value for key, value in os.environ.items() if not key.startswith(("COMPOSE_", "GEOREST_"))}
    port = fixture_port()
    env.update(GEOREST_HTTP_PORT=str(port), PUBLIC_URL=f"http://localhost:{port}")
    return env


def ports_are_private(compose, env, port):
    service_ids = command(*compose, "ps", "-q", env=env, stdout=subprocess.PIPE).stdout.split()
    published = []
    for container in service_ids:
        raw = command(
            "docker", "inspect", "--format",
            '{{index .Config.Labels "com.docker.compose.service"}} {{json .HostConfig.PortBindings}}',
            container, stdout=subprocess.PIPE,
        ).stdout.strip()
        service, bindings = raw.split(" ", 1)
        if json.loads(bindings):
            published.append(service)
            assert json.loads(bindings) == {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": port}]}
    assert published == ["traefik"]


def demo(level):
    env = project_env()
    compose = ["docker", "compose", "--env-file", ".env.example", "-p", f"georest-demo-{secrets.token_hex(4)}",
               "-f", "compose.yaml"]
    if level >= 2:
        compose += ["-f", "compose.cache.yaml"]
    try:
        start(compose, env)
        smoke(env["PUBLIC_URL"], level)
        ports_are_private(compose, env, env["GEOREST_HTTP_PORT"])
    finally:
        command(*compose, "down", "--volumes", env=env)


def load_external_database(name, env):
    command(
        "docker", "run", "-d", "--rm", "--name", name, "--network", env["GEOREST_TEST_NETWORK"],
        "--network-alias", "external-db", "-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_DB",
        "postgis/postgis:17-3.6-alpine", env=env,
    )
    for _ in range(45):
        result = subprocess.run(
            ["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"],
            stdout=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("external PostGIS fixture was not ready")
    command(
        "docker", "exec", "-i", "-e", "GEOREST_READER_PASSWORD", name,
        "psql", "-U", "postgres", "-d", "gis", "-v", "ON_ERROR_STOP=1",
        env=env, input=(ROOT / "tests/fixtures/external.sql").read_text(encoding="utf-8"),
    )


def layer(schema, table, **settings):
    return {"schema": schema, "table": table, "geometry": "geom", **settings}


def external():
    name = f"georest-external-{secrets.token_hex(4)}"
    env = project_env()
    env.update(
        COMPOSE_PROFILES="", GEOREST_DATASET="external", PGHOST="external-db", PGPORT="5432",
        PGDATABASE="gis", PGSSLMODE="disable", POSTGRES_DB="gis",
        GEOREST_READER_PASSWORD=secrets.token_urlsafe(24), POSTGRES_PASSWORD=secrets.token_urlsafe(24),
        GEOREST_TEST_NETWORK=name,
    )
    compose = ["docker", "compose", "--env-file", ".env.example", "-p", name, "-f", "compose.yaml",
               "-f", "tests/compose.external.yaml"]
    origin = env["PUBLIC_URL"]
    manifest = {
        "exclude": [{"schema": "east", "table": "hidden"}],
        "collections": {
            "east-points": layer("east", "points"),
            "west-points": layer("west", "points"),
            "features-only": layer("east", "boundaries", tiles=False),
            "hidden": layer("east", "hidden"),
        },
    }
    with tempfile.TemporaryDirectory(prefix="georest-collections-") as directory:
        path = Path(directory) / "collections.yml"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        env["GEOREST_COLLECTIONS_FILE"] = path.as_posix()
        command("docker", "network", "create", name)
        try:
            load_external_database(f"{name}-db", env)
            start(compose, env)
            assert collection_ids(origin) == {"east-points", "west-points", "features-only"}
            assert tile_ids(origin) == {"east-points", "west-points"}
            for side in ("east", "west"):
                features = json_response(f"{origin}/api/collections/{side}-points/items?f=json")["features"]
                assert [feature["properties"]["name"] for feature in features] == [side]
                tile_bytes(f"{origin}/tiles/{side}-points/4/8/7")
            for source in ("hidden", "unlisted", "features-only"):
                assert request(f"{origin}/tiles/{source}/4/8/7")[0] == 404
                assert request(f"{origin}/api/collections/{source}/tiles/WebMercatorQuad/4/7/8?f=pbf")[0] >= 400
            assert "postgis" not in command(*compose, "ps", "--services", env=env, stdout=subprocess.PIPE).stdout
            ports_are_private(compose, env, env["GEOREST_HTTP_PORT"])

            manifest["collections"]["invalid-id"] = layer("east", "invalid")
            path.write_text(json.dumps(manifest), encoding="utf-8")
            validation = subprocess.run(
                [*compose, "run", "--rm", "--no-deps", "configure", "render", "--check"],
                cwd=ROOT, env=env, text=True, capture_output=True,
            )
            assert validation.returncode != 0 and "invalid-id" in validation.stderr
            assert "single-column primary key" in validation.stderr

            del manifest["collections"]["invalid-id"]
            del manifest["collections"]["west-points"]
            manifest["collections"]["replacement"] = layer("east", "replace_with")
            path.write_text(json.dumps(manifest), encoding="utf-8")
            command(sys.executable, "scripts/refresh.py", *compose[2:], env=env)
            assert collection_ids(origin) == {"east-points", "replacement", "features-only"}
            assert tile_ids(origin) == {"east-points", "replacement"}
            assert request(f"{origin}/tiles/west-points/4/8/7")[0] == 404
            tile_bytes(f"{origin}/tiles/replacement/4/8/7")
        finally:
            command(*compose, "down", "--volumes", env=env)
            subprocess.run(["docker", "stop", f"{name}-db"], check=False)
            command("docker", "network", "rm", name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", choices=("demo", "external"))
    parser.add_argument("--level", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    demo(args.level) if args.fixture == "demo" else external()
    print(f"{args.fixture} deployment fixture passed")
