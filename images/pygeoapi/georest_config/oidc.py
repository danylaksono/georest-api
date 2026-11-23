"""Attach the Level 4 authorization checks to the HTTPS routers."""

import os

from .manifest import ConfigError
from .secure import write_rule

REALM = "/auth/realms/georest"
PROTOCOL = f"{REALM}/protocol/openid-connect"
OIDC_PATHS = (
    f"{REALM}/.well-known/openid-configuration",
    *(f"{PROTOCOL}/{endpoint}" for endpoint in (
        "auth", "token", "certs", "userinfo", "logout", "login-status-iframe.html", "login-status-iframe.html/init",
    )),
)
OIDC_PREFIXES = (f"{REALM}/login-actions/", f"{PROTOCOL}/3p-cookies/", "/auth/resources/")
OGC_TILES = (
    "(PathRegexp(`^/api/collections/[^/]+/tiles(/|$)`) || "
    "Path(`/api/tileMatrixSets`) || PathPrefix(`/api/tileMatrixSets/`))"
)


def boolean(variable):
    value = os.environ.get(variable, "false")
    if value not in ("true", "false"):
        raise ConfigError(f"{variable} must be true or false")
    return value == "true"


def protected(middlewares):
    return [*(name for name in middlewares if name != "client-cache"), "oidc-private", "oidc-read"]


def configure_oidc(config, security, collection_ids, tile_ids):
    private_read = boolean("GEOREST_PRIVATE_READ")
    private_tiles = boolean("GEOREST_PRIVATE_TILES")
    if private_read and tile_ids and not private_tiles:
        raise ConfigError("private feature reads require GEOREST_PRIVATE_TILES=true for tiled collections")

    http = config["http"]
    routers = http["routers"]
    middleware = http["middlewares"]
    read = routers["api-read"]
    normal_middleware = read["middlewares"]
    https = {"entryPoints": read["entryPoints"], "tls": read["tls"]}
    hostname = f"Host(`{security.host}`)"

    for action in ("read", "write"):
        middleware[f"oidc-{action}"] = {"forwardAuth": {
            "address": f"http://authorizer:8080/{action}",
            "trustForwardHeader": False,
            "authRequestHeaders": ["Authorization"],
            "maxResponseBodySize": 4096,
        }}
    middleware["oidc-private"] = {"headers": {"customResponseHeaders": {"Cache-Control": "private, no-store"}}}
    if private_read:
        read["middlewares"] = protected(normal_middleware)
    if private_tiles:
        tiles = routers["tile-read"]
        tiles["middlewares"] = protected(tiles["middlewares"])
        if not private_read:
            routers["ogc-tile-read"] = {
                **read, "rule": f"({read['rule']}) && {OGC_TILES}",
                "priority": 110, "middlewares": protected(normal_middleware),
            }

    if collection_ids:
        writes = [*normal_middleware, "oidc-write"]
        if security.write_networks:
            middleware["write-ips"] = {"ipAllowList": {"sourceRange": security.write_networks}}
            writes.append("write-ips")
        routers["api-write"] = {
            **https, "rule": f"{hostname} && {write_rule(collection_ids)}",
            "middlewares": writes, "priority": 100, "service": "api",
        }

    endpoints = [*(f"Path(`{path}`)" for path in OIDC_PATHS),
                 *(f"PathPrefix(`{path}`)" for path in OIDC_PREFIXES)]
    routers["identity"] = {
        **https, "rule": f"{hostname} && ({' || '.join(endpoints)})",
        "middlewares": ["security-headers"], "service": "identity",
    }
    http["services"]["identity"] = {"loadBalancer": {"servers": [{"url": "http://keycloak:8080"}]}}
