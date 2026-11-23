"""Load and validate the user-facing publication manifest."""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

SOURCE_ID = re.compile(r"[a-z][a-z0-9_-]*\Z")
RESERVED_IDS = {
    "catalog", "config", "font", "health", "help", "index", "manifest",
    "metrics", "ogc", "refresh", "reload", "sprite", "status",
}
DEFAULT_FIELDS = {"tiles", "cache", "editable"}
COLLECTION_FIELDS = DEFAULT_FIELDS | {
    "schema", "table", "geometry", "id_field", "time_field",
    "title", "description", "keywords",
}


class ConfigError(ValueError):
    """An error whose details are safe to show to the operator."""


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ConfigError("YAML mapping keys must be strings")
            if key in mapping:
                raise ConfigError(f"repeated YAML key {key!r}")
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_yaml(path: Path):
    try:
        with path.open(encoding="utf-8") as source:
            return yaml.load(source, Loader=UniqueKeyLoader)
    except OSError as exc:
        raise ConfigError(f"cannot read {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}") from exc


@dataclass(frozen=True)
class Collection:
    id: str
    schema: str
    table: str
    geometry: str
    id_field: str | None
    time_field: str | None
    title: str | None
    description: str | None
    keywords: list[str]
    tiles: bool
    cache: str
    editable: bool


def mapping(value, allowed, label):
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a mapping")
    if allowed is not None and (unknown := value.keys() - allowed):
        raise ConfigError(f"{label} has unknown fields: {', '.join(sorted(unknown))}")
    return value


def optional_text(settings, field):
    if field not in settings:
        return None
    value = settings[field]
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise ConfigError(f"{field} must be a nonempty string")
    return value


def names(settings, *fields):
    result = tuple(optional_text(settings, field) for field in fields)
    if any(value is None for value in result):
        raise ConfigError(f"{', '.join(fields)} are required")
    if any(len(value.encode("utf-8")) > 63 for value in result):
        raise ConfigError("PostgreSQL identifiers must be at most 63 UTF-8 bytes")
    return result


def publication_settings(settings):
    if type(settings.get("tiles", True)) is not bool:
        raise ConfigError("tiles must be true or false")
    if type(settings.get("editable", False)) is not bool:
        raise ConfigError("editable must be true or false")
    if settings.get("cache", "static") not in ("static", "volatile"):
        raise ConfigError("cache must be static or volatile")


def read_manifest(path: Path) -> list[Collection]:
    manifest = mapping(load_yaml(path), {"defaults", "exclude", "collections"}, str(path))
    defaults = mapping(manifest.get("defaults", {}), DEFAULT_FIELDS, "defaults")
    publication_settings(defaults)
    entries = mapping(manifest.get("collections"), None, "collections")
    exclude = manifest.get("exclude", [])
    if not isinstance(exclude, list):
        raise ConfigError("exclude must be a list of schema and table mappings")

    excluded = {
        names(mapping(entry, {"schema", "table"}, "exclude entry"), "schema", "table")
        for entry in exclude
    }
    seen_tables = set()
    published = []
    for source_id, entry in entries.items():
        try:
            if not SOURCE_ID.fullmatch(source_id) or source_id in RESERVED_IDS:
                raise ConfigError("invalid or reserved public ID")
            entry = {**defaults, **mapping(entry, COLLECTION_FIELDS, "entry")}
            schema, table, geometry = names(entry, "schema", "table", "geometry")
            if (schema, table) in excluded:
                continue
            if (schema, table) in seen_tables:
                raise ConfigError("a table may appear in only one collection")
            seen_tables.add((schema, table))
            publication_settings(entry)
            keywords = entry.get("keywords", [])
            if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
                raise ConfigError("keywords must be a list of strings")
            published.append(
                Collection(
                    source_id, schema, table, geometry,
                    optional_text(entry, "id_field"), optional_text(entry, "time_field"),
                    optional_text(entry, "title"), optional_text(entry, "description"),
                    keywords, entry.get("tiles", True), entry.get("cache", "static"),
                    entry.get("editable", False),
                )
            )
        except ConfigError as exc:
            raise ConfigError(f"collection {source_id!r}: {exc}") from exc
    return published
