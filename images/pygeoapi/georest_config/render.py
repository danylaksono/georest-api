"""Render the backend and edge configuration for a validated deployment."""

import copy
import ipaddress
import json
import os
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import yaml

from .database import connect, inspect_manifest
from .manifest import SOURCE_ID, ConfigError, load_yaml, read_manifest
from .oidc import configure_oidc
from .secure import configure_https, security_settings

CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
READ_METHOD = "(Method(`GET`) || Method(`HEAD`) || Method(`OPTIONS`))"
API_PATH = "(Path(`/api`) || PathPrefix(`/api/`))"
ADMIN_PATH = "(Path(`/api/admin`) || PathPrefix(`/api/admin/`))"


def get_settings():
    mode = os.environ["GEOREST_CONFIG_MODE"]
    dataset = os.environ["GEOREST_DATASET"]
    if mode not in ("auto", "manual") or dataset not in ("demo", "external"):
        raise ConfigError("GEOREST_CONFIG_MODE must be auto or manual; GEOREST_DATASET must be demo or external")
    try:
        origin = urlsplit(os.environ["PUBLIC_URL"])
        origin.port
        bind = ipaddress.ip_address(os.environ["GEOREST_BIND_ADDRESS"])
        port = int(os.environ["PGPORT"])
    except ValueError:
        raise ConfigError("invalid PUBLIC_URL, GEOREST_BIND_ADDRESS, or PGPORT") from None
    if (
        origin.scheme not in ("http", "https") or not origin.hostname or origin.username is not None
        or origin.path not in ("", "/") or origin.query or origin.fragment
    ):
        raise ConfigError("PUBLIC_URL must be an HTTP(S) origin")
    if not 1 <= port <= 65535:
        raise ConfigError("PGPORT must be between 1 and 65535")

    host = os.environ["PGHOST"]
    password = os.environ["GEOREST_READER_PASSWORD"]
    if dataset == "demo" and host != "postgis":
        raise ConfigError("GEOREST_DATASET=demo requires the bundled postgis host")
    secure = os.environ.get("GEOREST_SECURE") == "true"
    if not password or (password == "demo-reader-password" and (secure or dataset == "external" or not bind.is_loopback)):
        raise ConfigError("HTTPS, external, and non-loopback deployments require a custom reader password")
    if dataset == "external" and mode == "auto" and not os.environ.get("GEOREST_COLLECTIONS_EXPLICIT"):
        raise ConfigError("external mode requires GEOREST_COLLECTIONS_FILE")

    database = {
        "host": host,
        "port": port,
        "dbname": os.environ["PGDATABASE"],
        "user": "georest_reader",
        "password": password,
        "sslmode": os.environ["PGSSLMODE"],
    }
    return origin, mode, database


def database_url(database):
    host = database["host"]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    user = quote(database["user"], safe="")
    password = quote(database["password"], safe="")
    dbname = quote(database["dbname"], safe="")
    query = urlencode({"sslmode": database["sslmode"]})
    return f"postgresql://{user}:{password}@{host}:{database['port']}/{dbname}?{query}"


def pygeoapi_config(origin, database, collections, tables, cache_enabled, editable_ids):
    api = load_yaml(Path("/inputs/pygeoapi.yml"))
    api_url = f"{origin.scheme}://{origin.netloc}/api"
    api["server"]["url"] = api_url
    metadata = api["metadata"]
    metadata["identification"].update(
        title=os.environ["GEOREST_TITLE"], description=os.environ["GEOREST_DESCRIPTION"]
    )
    for category in metadata.values():
        category["url"] = api_url

    for collection in collections:
        table = tables[collection.id]
        search_path = list(dict.fromkeys([collection.schema, table.postgis_schema]))
        extent = {"spatial": {"bbox": table.bounds, "crs": CRS84}}
        if table.interval:
            extent["temporal"] = {"interval": table.interval}
        connection = {key: value for key, value in database.items() if key != "sslmode"}
        connection.update(search_path=search_path, query={"sslmode": database["sslmode"]})
        feature = {
            "type": "feature",
            "name": "PostgreSQL",
            "data": connection,
            "table": collection.table,
            "id_field": table.primary_id,
            "geom_field": collection.geometry,
            "storage_crs": CRS84 if table.srid == 4326 else f"http://www.opengis.net/def/crs/EPSG/0/{table.srid}",
        }
        if collection.id in editable_ids:
            connection.update(user="georest_editor", password=os.environ["GEOREST_EDITOR_PASSWORD"])
            feature["editable"] = True
        if collection.time_field:
            feature["time_field"] = collection.time_field
        providers = [feature]
        if collection.tiles:
            tile_origin = "http://varnish" if cache_enabled else "http://martin:3000"
            provider_name = (
                "georest_config.tile_proxy.CacheAwareMVTProxy" if cache_enabled else "MVT-proxy"
            )
            providers.append({
                "type": "tile",
                "name": provider_name,
                "data": f"{tile_origin}/tiles/{collection.id}/{{z}}/{{x}}/{{y}}",
                "options": {"zoom": {"min": 0, "max": 22}, "schemes": ["WebMercatorQuad"]},
                "format": {"name": "pbf", "mimetype": "application/vnd.mapbox-vector-tile"},
            })
        api["resources"][collection.id] = {
            "type": "collection",
            "title": collection.title or table.description or collection.table,
            "description": collection.description or table.description or collection.table,
            "keywords": collection.keywords,
            "extents": extent,
            "links": [],
            "providers": providers,
        }
    return api


def martin_config(database, collections, tables, cache_enabled):
    config = load_yaml(Path("/inputs/martin.yml"))
    if cache_enabled:
        config["cache"] = "disable"
    postgres = config["postgres"]
    postgres["connection_string"] = database_url(database)
    sources = {}
    for collection in collections:
        if collection.tiles:
            table = tables[collection.id]
            source = {
                "schema": collection.schema,
                "table": collection.table,
                "geometry_column": collection.geometry,
                "srid": table.srid,
                "layer_id": collection.id,
                "properties": table.tile_properties,
            }
            if table.integer_id:
                source["id_column"] = table.primary_id
            sources[collection.id] = source
    postgres["tables"] = sources
    return config


def edge_config(origin, source_ids, cache_enabled):
    tile_path = "Path(`/tiles/catalog`)"
    if source_ids:
        ids = "|".join(sorted(source_ids))
        tile_path = f"({tile_path} || PathRegexp(`^/tiles/({ids})(/[0-9]+/[0-9]+/[0-9]+)?$`))"

    middlewares = {
        "tile-origin": {
            "headers": {
                "customRequestHeaders": {
                    "X-Forwarded-Host": origin.netloc,
                    "X-Forwarded-Proto": origin.scheme,
                }
            }
        }
    }
    cors = [item.strip() for item in os.environ["CORS_ORIGINS"].split(",") if item.strip()]
    common = []
    if cors:
        middlewares["cors"] = {
            "headers": {
                "accessControlAllowOriginList": cors,
                "accessControlAllowMethods": ["GET", "HEAD", "OPTIONS"],
                "accessControlAllowHeaders": ["Accept", "Authorization", "Content-Type"],
                "accessControlExposeHeaders": ["Content-Type", "ETag", "X-Cache"],
                "addVaryHeader": True,
            }
        }
        common.append("cors")
    if cache_enabled:
        middlewares["client-cache"] = {"headers": {"customResponseHeaders": {"Cache-Control": "no-store"}}}
        common.append("client-cache")
    tile_backend = "http://varnish" if cache_enabled else "http://martin:3000"
    return {
        "http": {
            "routers": {
                "api-read": {
                    "entryPoints": ["web"],
                    "rule": f"{API_PATH} && !{ADMIN_PATH} && {READ_METHOD}",
                    "service": "api",
                    "middlewares": common,
                    "priority": 100,
                },
                "tile-read": {
                    "entryPoints": ["web"],
                    "rule": f"{tile_path} && {READ_METHOD}",
                    "service": "tiles",
                    "middlewares": [*common, "tile-origin"],
                    "priority": 100,
                },
            },
            "services": {
                "api": {"loadBalancer": {"servers": [{"url": "http://pygeoapi:80"}]}},
                "tiles": {"loadBalancer": {"servers": [{"url": tile_backend}]}},
            },
            "middlewares": middlewares,
        }
    }


def redact(api, martin):
    api = copy.deepcopy(api)
    martin = copy.deepcopy(martin)
    for resource in api["resources"].values():
        for provider in resource["providers"]:
            if provider["type"] == "feature":
                provider["data"]["password"] = "<redacted>"
    if "postgres" in martin:
        martin["postgres"]["connection_string"] = "<redacted>"
    return api, martin


def manual_config(cache_enabled):
    api_path = Path("/manual/pygeoapi.config.yml")
    martin_path = Path("/manual/martin.yaml")
    api = load_yaml(api_path)
    martin = load_yaml(martin_path)
    if not isinstance(api, dict) or not isinstance(martin, dict):
        raise ConfigError("manual configs must be YAML mappings")
    if api.get("server", {}).get("admin"):
        raise ConfigError("manual pygeoapi config must disable the admin API")
    if martin.get("route_prefix") != "/tiles":
        raise ConfigError("manual Martin config must set route_prefix: /tiles")
    if cache_enabled and martin.get("cache") != "disable":
        raise ConfigError("Level 2 requires cache: disable in a manual Martin config")
    pg_configs = martin.get("postgres", [])
    if isinstance(pg_configs, dict):
        pg_configs = [pg_configs]
    source_ids = set()
    for config in pg_configs:
        if config.get("auto_publish") is not False or config.get("functions"):
            raise ConfigError("manual Martin configs require explicit tables and auto_publish: false")
        source_ids.update(config.get("tables", {}))
    if any(not SOURCE_ID.fullmatch(source_id) for source_id in source_ids):
        raise ConfigError("manual Martin source IDs must use the documented public ID format")
    return api_path.read_text(encoding="utf-8"), martin_path.read_text(encoding="utf-8"), source_ids


def cache_policy(volatile_ids):
    try:
        default_ttl = int(os.environ["TILE_TTL_DEFAULT"])
        short_ttl = int(os.environ["TILE_TTL_VOLATILE"])
    except ValueError:
        raise ConfigError("tile TTLs must be integer seconds") from None
    if not 0 < short_ttl <= default_ttl <= 2_147_483_647:
        raise ConfigError("tile TTLs must be positive and volatile must be at most the default")
    lines = [
        "sub georest_cache_ttl {",
        f"    set beresp.ttl = {default_ttl}s;",
    ]
    if volatile_ids:
        ids = "|".join(sorted(volatile_ids))
        lines.extend([
            f'    if (bereq.url ~ "^/tiles/({ids})/") {{',
            f"        set beresp.ttl = {short_ttl}s;",
            "    }",
        ])
    return "\n".join([*lines, "}", ""])


def build_configs(dry_run=False):
    origin, mode, database = get_settings()
    cache_enabled = os.environ.get("GEOREST_TILE_CACHE") == "true"
    security = security_settings(origin, mode)
    volatile_ids = []
    editable_ids = set()
    if mode == "manual":
        if dry_run:
            raise ConfigError("dry-run output is unavailable for operator-managed configs")
        api, martin, source_ids = manual_config(cache_enabled)
        connect(database).close()
    else:
        collections = read_manifest(Path("/inputs/collections.yml"))
        tables = inspect_manifest(collections, database)
        if security and security.allow_edits:
            editable_ids = {collection.id for collection in collections if collection.editable}
        api = pygeoapi_config(origin, database, collections, tables, cache_enabled, editable_ids)
        martin = martin_config(database, collections, tables, cache_enabled)
        volatile_ids = [
            collection.id for collection in collections
            if collection.tiles and (collection.cache == "volatile" or collection.id in editable_ids)
        ]
        source_ids = martin.get("postgres", {}).get("tables", {})
        if dry_run:
            api, martin = redact(api, martin)
        api, martin = (yaml.safe_dump(config, sort_keys=False) for config in (api, martin))
    edge = edge_config(origin, source_ids, cache_enabled)
    oidc = security and security.oidc
    if security:
        configure_https(edge, security, set() if oidc else editable_ids)
    if oidc:
        configure_oidc(edge, security, {collection.id for collection in collections}, source_ids)
    configs = {
        "api": {"pygeoapi.yml": api},
        "martin": {"martin.yml": martin},
        "edge": {"traefik.yml": yaml.safe_dump(edge, sort_keys=False)},
    }
    if cache_enabled:
        configs["cache"] = {"cache-policy.vcl": cache_policy(volatile_ids)}
    if oidc:
        acl = {"georest": {"issuer": f"{origin.geturl()}/auth/realms/georest", "editable": sorted(editable_ids)}}
        configs["auth"] = {"acl.json": json.dumps(acl)}
    return configs
