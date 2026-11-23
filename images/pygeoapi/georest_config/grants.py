"""Reconcile PostgreSQL grants for the dedicated GeoREST service logins."""

import os

import psycopg2
from psycopg2 import sql

from .database import postgis_schema
from .manifest import ConfigError

READER = "georest_reader"
EDITOR = "georest_editor"
USER_SCHEMA = "n.nspname <> 'information_schema' AND left(n.nspname, 3) <> 'pg_'"


def ensure_login(cursor, role, password):
    cursor.execute(
        "SELECT rolcanlogin, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = %s",
        (role,),
    )
    present = cursor.fetchone()
    if present is None:
        if not password or password == "demo-editor-password":
            raise ConfigError(f"provision a password for {role} before creating it")
        cursor.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(role), sql.Literal(password)
        ))
    elif not present[0] or any(present[1:]):
        raise ConfigError(f"{role} must be a dedicated unprivileged login")


def referenced_sequences(cursor, tables):
    sequences = set()
    for schema, table in tables:
        cursor.execute(
            """
            WITH relation AS (
                SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND c.relname = %s
            )
            SELECT n.nspname, sequence.relname
            FROM pg_depend d
            JOIN pg_class sequence ON sequence.oid = d.objid AND sequence.relkind = 'S'
            JOIN pg_namespace n ON n.oid = sequence.relnamespace
            JOIN relation ON relation.oid = d.refobjid
            WHERE d.classid = 'pg_class'::regclass AND d.refclassid = 'pg_class'::regclass
              AND d.deptype IN ('a', 'i')
            UNION
            SELECT n.nspname, sequence.relname
            FROM pg_depend d JOIN pg_attrdef a ON d.objid = a.oid
            JOIN pg_class sequence ON sequence.oid = d.refobjid AND sequence.relkind = 'S'
            JOIN pg_namespace n ON n.oid = sequence.relnamespace
            JOIN relation ON relation.oid = a.adrelid
            WHERE d.classid = 'pg_attrdef'::regclass AND d.refclassid = 'pg_class'::regclass
            """,
            (schema, table),
        )
        sequences.update(cursor.fetchall())
    return sequences


def direct_grants(cursor, role):
    cursor.execute(
        "SELECT DISTINCT n.nspname, c.relname, c.relkind = 'S' "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "CROSS JOIN LATERAL aclexplode(c.relacl) acl "
        "WHERE acl.grantee = %s::regrole AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S') "
        f"AND {USER_SCHEMA}",
        (role,),
    )
    relations = cursor.fetchall()
    cursor.execute(
        "SELECT DISTINCT n.nspname FROM pg_namespace n "
        "CROSS JOIN LATERAL aclexplode(n.nspacl) acl "
        f"WHERE acl.grantee = %s::regrole AND {USER_SCHEMA}",
        (role,),
    )
    return relations, {item[0] for item in cursor.fetchall()}


def set_grants(cursor, role, database, extension, tables, sequences=()):
    role_name = sql.Identifier(role)
    schemas = {extension} | {schema for schema, _ in (*tables, *sequences)}
    previous_relations, previous_schemas = direct_grants(cursor, role)
    for schema, relation, is_sequence in previous_relations:
        relation_type = sql.SQL("SEQUENCE" if is_sequence else "TABLE")
        cursor.execute(sql.SQL("REVOKE ALL ON {} {} FROM {}").format(
            relation_type, sql.Identifier(schema, relation), role_name
        ))
    for schema in previous_schemas - schemas:
        cursor.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}").format(sql.Identifier(schema), role_name))
    for schema in schemas:
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(sql.Identifier(schema), role_name))
    cursor.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), role_name))

    privileges = sql.SQL("SELECT" if role == READER else "SELECT, INSERT, UPDATE, DELETE")
    for schema, table in sorted(tables):
        cursor.execute(sql.SQL("GRANT {} ON TABLE {} TO {}").format(
            privileges, sql.Identifier(schema, table), role_name
        ))
    for schema, sequence in sorted(sequences):
        cursor.execute(sql.SQL("GRANT USAGE ON SEQUENCE {} TO {}").format(
            sql.Identifier(schema, sequence), role_name
        ))


def audit_writes(cursor, role, tables, sequences):
    cursor.execute(
        "SELECT n.nspname, c.relname, c.relkind = 'S' "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        f"WHERE {USER_SCHEMA} AND CASE "
        "WHEN c.relkind = 'S' THEN has_sequence_privilege(%(role)s, c.oid, 'USAGE, UPDATE') "
        "WHEN c.relkind IN ('r','p','v','m','f') THEN "
        "has_table_privilege(%(role)s, c.oid, 'INSERT, UPDATE, DELETE, TRUNCATE') "
        "OR has_any_column_privilege(%(role)s, c.oid, 'INSERT, UPDATE') ELSE false END",
        {"role": role},
    )
    for schema, relation, is_sequence in cursor.fetchall():
        allowed = sequences if is_sequence else tables
        if (schema, relation) not in allowed:
            raise ConfigError(
                f"{role} retains effective write access to {schema}.{relation}; "
                "remove privileges inherited from another role, ownership, or PUBLIC"
            )


def reconcile(collections, database, allow_edits):
    dsn = os.environ.get("GEOREST_ADMIN_DSN")
    if not dsn:
        raise ConfigError("pass GEOREST_ADMIN_DSN to the grants command")
    try:
        connection = psycopg2.connect(dsn, connect_timeout=5)
    except psycopg2.Error:
        raise ConfigError("could not connect with GEOREST_ADMIN_DSN") from None
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("SELECT current_database(), pg_try_advisory_xact_lock(hashtext('georest-grants'))")
            actual_database, locked = cursor.fetchone()
            if actual_database != database["dbname"] or not locked:
                raise ConfigError("the grants database must match PGDATABASE and have no active reconciliation")
            extension = postgis_schema(cursor)
            ensure_login(cursor, READER, database["password"])
            ensure_login(cursor, EDITOR, os.environ.get("GEOREST_EDITOR_PASSWORD"))

            published = {(layer.schema, layer.table) for layer in collections}
            editable = {(layer.schema, layer.table) for layer in collections if allow_edits and layer.editable}
            sequences = referenced_sequences(cursor, editable)
            set_grants(cursor, READER, actual_database, extension, published)
            set_grants(cursor, EDITOR, actual_database, extension, editable, sequences)
            audit_writes(cursor, READER, set(), set())
            audit_writes(cursor, EDITOR, editable, sequences)
    except psycopg2.Error as exc:
        raise ConfigError(f"could not apply grants; changes rolled back ({exc.pgcode})") from None
    finally:
        connection.close()
