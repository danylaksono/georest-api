"""Validate the secure overlay and apply its edge policy."""

import ipaddress
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .manifest import ConfigError


@dataclass(frozen=True)
class Security:
    host: str
    local_tls: bool
    allow_edits: bool
    write_networks: list[str]
    write_users_file: str | None
    read_users_file: str | None
    oidc: bool


def users_file(variable):
    name = os.environ.get(variable, "")
    if not name:
        return None
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ConfigError(f"{variable} must name a file inside GEOREST_AUTH_DIR")
    path = Path("/auth") / name
    if not path.is_file() or path.stat().st_size == 0:
        raise ConfigError(f"{variable} must refer to a nonempty htpasswd file")
    return str(path)


def security_settings(origin, mode):
    oidc = os.environ.get("GEOREST_OIDC") == "true"
    if os.environ.get("GEOREST_SECURE") != "true":
        if oidc:
            raise ConfigError("Level 4 requires the HTTPS overlay")
        return None
    if mode != "auto":
        raise ConfigError("HTTPS deployments require GEOREST_CONFIG_MODE=auto")
    host = os.environ.get("DOMAIN", "").lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", host) or origin.hostname != host or origin.scheme != "https":
        raise ConfigError("Level 3 requires an HTTPS PUBLIC_URL matching DOMAIN")
    local_tls = os.environ.get("GEOREST_TLS_MODE") == "local"
    if not local_tls and not os.environ.get("ACME_EMAIL"):
        raise ConfigError("ACME_EMAIL is required for production HTTPS")
    if oidc and origin.path:
        raise ConfigError("Level 4 PUBLIC_URL must omit the trailing slash")
    try:
        networks = [
            str(ipaddress.ip_network(item.strip()))
            for item in os.environ.get("WRITE_ALLOWLIST", "").split(",") if item.strip()
        ]
    except ValueError:
        raise ConfigError("WRITE_ALLOWLIST must be a comma-separated list of CIDRs") from None
    if oidc and any(os.environ.get(key) for key in ("WRITE_BASIC_AUTH_FILE", "API_BASIC_AUTH_FILE")):
        raise ConfigError("clear the Basic auth settings when enabling Level 4")
    write_file = users_file("WRITE_BASIC_AUTH_FILE")
    read_file = users_file("API_BASIC_AUTH_FILE")
    allow_edits = os.environ.get("GEOREST_ALLOW_EDITS", "false")
    if allow_edits not in ("true", "false"):
        raise ConfigError("GEOREST_ALLOW_EDITS must be true or false")
    if allow_edits == "true":
        if not oidc and not networks and not write_file:
            raise ConfigError("enable a write allowlist or Basic auth before enabling edits")
        editor_password = os.environ.get("GEOREST_EDITOR_PASSWORD")
        if not editor_password or editor_password == "demo-editor-password":
            raise ConfigError("editing requires a deployment-specific GEOREST_EDITOR_PASSWORD")
    return Security(host, local_tls, allow_edits == "true", networks, write_file, read_file, oidc)


def write_rule(editable_ids):
    ids = "|".join(sorted(editable_ids))
    prefix = f"^/api/collections/({ids})/items"
    create = f"(PathRegexp(`{prefix}$`) && Method(`POST`))"
    update = f"(PathRegexp(`{prefix}/[^/]+$`) && (Method(`PUT`) || Method(`DELETE`)))"
    return f"({create} || {update})"


def configure_https(config, security, editable_ids):
    http = config["http"]
    routers = http["routers"]
    middleware = http["middlewares"]
    tls = {} if security.local_tls else {"certResolver": "georest"}
    hostname_rule = f"Host(`{security.host}`)"
    headers = {"contentTypeNosniff": True}
    if not security.local_tls:
        headers["stsSeconds"] = 31536000
    middleware["security-headers"] = {"headers": headers}
    for router in routers.values():
        router["entryPoints"] = ["websecure"]
        router["tls"] = tls.copy()
        router["rule"] = f"{hostname_rule} && ({router['rule']})"
        router["middlewares"] = [*router["middlewares"], "security-headers"]
    if security.local_tls:
        config["tls"] = {
            "certificates": [{"certFile": "/tls/localhost.pem", "keyFile": "/tls/localhost-key.pem"}]
        }

    writes = list(routers["api-read"]["middlewares"])
    if "cors" in middleware:
        middleware["cors"]["headers"]["accessControlAllowMethods"] = [
            "GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE",
        ]
    if security.read_users_file:
        middleware["read-auth"] = {"basicAuth": {"usersFile": security.read_users_file}}
        for router in routers.values():
            router["middlewares"].append("read-auth")

    if editable_ids:
        if security.write_networks:
            middleware["write-ips"] = {"ipAllowList": {"sourceRange": security.write_networks}}
            writes.append("write-ips")
        if security.write_users_file:
            middleware["write-auth"] = {"basicAuth": {"usersFile": security.write_users_file}}
            writes.append("write-auth")
        routers["api-write"] = {
            "rule": f"{hostname_rule} && {write_rule(editable_ids)}",
            "entryPoints": ["websecure"],
            "tls": tls.copy(),
            "middlewares": writes,
            "priority": 100,
            "service": "api",
        }
