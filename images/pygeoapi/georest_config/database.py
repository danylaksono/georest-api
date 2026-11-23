"""Inspect published tables using the restricted PostgreSQL login."""

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from datetime import time as midnight

import psycopg2
from psycopg2 import sql

from .manifest import Collection, ConfigError

WORLD = [-180, -90, 180, 90]
INTEGER_TYPES = {"int2", "int4", "int8"}
TEMPORAL_TYPES = {"date", "timestamp", "timestamptz"}


@dataclass(frozen=True)
class Table:
    primary_id: str
    integer_id: bool
    srid: int
    postgis_schema: str
    description: str | None
    bounds: list[float]
    interval: list[str] | None


def connect(settings):
    deadline = time.monotonic() + 42
    while True:
        try:
            connection = psycopg2.connect(**settings, connect_timeout=3)
        except psycopg2.OperationalError:
            if time.monotonic() >= deadline:
                raise ConfigError(
                    "could not connect to PostGIS as georest_reader; check initialization, "
                    "network, TLS, and credentials"
                ) from None
            time.sleep(1)
        else:
            connection.autocommit = True
            return connection


def postgis_schema(cursor) -> str:
    cursor.execute(
        "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
        "WHERE e.extname = 'postgis'"
    )
    extension = cursor.fetchone()
    if extension is None:
        raise ConfigError("the database requires the postgis extension")
    cursor.execute(
        sql.SQL("SET search_path TO pg_catalog, {}").format(sql.Identifier(extension[0]))
    )
    cursor.execute("SET statement_timeout TO '3s'")
    cursor.execute("SET TIME ZONE 'UTC'")
    return extension[0]


def table_columns(cursor, collection):
    cursor.execute(
        """
        SELECT a.attname, t.typname, a.attnotnull,
               EXISTS (
                   SELECT FROM pg_index i
                   WHERE i.indrelid = c.oid AND i.indkey[0] = a.attnum
                     AND i.indisunique AND i.indisvalid AND i.indnkeyatts = 1
                     AND i.indpred IS NULL AND i.indexprs IS NULL
               ) AS unique_key,
               EXISTS (
                   SELECT FROM pg_index i
                   WHERE i.indrelid = c.oid AND i.indkey[0] = a.attnum
                     AND i.indisprimary AND i.indnkeyatts = 1
               ) AS primary_key,
               obj_description(c.oid, 'pg_class')
        FROM pg_attribute a
        JOIN pg_type t ON t.oid = a.atttypid
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = %s AND c.relname = %s AND c.relkind IN ('r', 'p')
          AND a.attnum > 0 AND NOT a.attisdropped
          AND has_schema_privilege(n.oid, 'USAGE')
          AND has_table_privilege(c.oid, 'SELECT')
        """,
        (collection.schema, collection.table),
    )
    return {row[0]: row[1:] for row in cursor.fetchall()}


def geometry_srid(cursor, collection):
    cursor.execute(
        """
        SELECT srid FROM geometry_columns
        WHERE f_table_schema = %s AND f_table_name = %s AND f_geometry_column = %s
        """,
        (collection.schema, collection.table, collection.geometry),
    )
    geometry = cursor.fetchone()
    if geometry is None or geometry[0] <= 0:
        raise ConfigError("geometry column must have a declared PostGIS SRID")
    return geometry[0]


def get_bounds(cursor, collection, srid):
    bbox = sql.SQL("SELECT ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b) FROM ({}) AS extent")
    if srid == 4326:
        cursor.execute(
            bbox.format(sql.SQL("SELECT ST_EstimatedExtent(%s, %s, %s) AS b")),
            (collection.schema, collection.table, collection.geometry),
        )
        result = cursor.fetchone()
        if result and None not in result:
            return list(result)

    try:
        query = sql.SQL("SELECT ST_Extent(ST_Transform({}, 4326)) AS b FROM {}").format(
            sql.Identifier(collection.geometry),
            sql.Identifier(collection.schema, collection.table),
        )
        cursor.execute(bbox.format(query))
        result = cursor.fetchone()
        if result and None not in result:
            return [float(value) for value in result]
    except (psycopg2.errors.QueryCanceled, psycopg2.errors.InternalError):
        pass
    logging.warning("collection %s: using world extent", collection.id)
    return WORLD.copy()


def timestamp(value: date | datetime) -> str:
    if not isinstance(value, datetime):
        value = datetime.combine(value, midnight())
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def temporal_interval(cursor, collection):
    field = sql.Identifier(collection.time_field)
    table = sql.Identifier(collection.schema, collection.table)
    try:
        cursor.execute(sql.SQL("SELECT min({0}), max({0}) FROM {1}").format(field, table))
    except psycopg2.errors.QueryCanceled:
        return None
    start, end = cursor.fetchone()
    return [timestamp(start), timestamp(end)] if start is not None else None


def inspect_table(cursor, collection: Collection, extension_schema: str) -> Table:
    fields = table_columns(cursor, collection)
    if not fields:
        raise ConfigError("table is missing or not readable by georest_reader")

    id_field = collection.id_field
    if id_field is None:
        id_field = next((name for name, column in fields.items() if column[3]), None)
    if id_field not in fields or not all(fields[id_field][1:3]):
        raise ConfigError("requires a single-column primary key or a unique, non-null id_field")
    srid = geometry_srid(cursor, collection)

    interval = None
    if collection.time_field is not None:
        column = fields.get(collection.time_field)
        if column is None or column[0] not in TEMPORAL_TYPES:
            raise ConfigError("time_field must be a date, timestamp, or timestamptz column")
        interval = temporal_interval(cursor, collection)
        if interval is None:
            logging.warning("collection %s: temporal extent unavailable", collection.id)
    return Table(
        id_field, fields[id_field][0] in INTEGER_TYPES, srid, extension_schema,
        fields[id_field][4], get_bounds(cursor, collection, srid), interval,
    )


def inspect_manifest(collections, settings):
    connection = connect(settings)
    try:
        with connection.cursor() as cursor:
            extension_schema = postgis_schema(cursor)
            result = {}
            for collection in collections:
                try:
                    result[collection.id] = inspect_table(cursor, collection, extension_schema)
                except ConfigError as exc:
                    raise ConfigError(f"collection {collection.id!r}: {exc}") from exc
                except psycopg2.Error as exc:
                    raise ConfigError(
                        f"collection {collection.id!r}: PostGIS inspection failed ({exc.pgcode})"
                    ) from exc
            return result
    finally:
        connection.close()
