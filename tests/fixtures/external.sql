\getenv reader_password GEOREST_READER_PASSWORD
CREATE ROLE georest_reader LOGIN PASSWORD :'reader_password';
CREATE SCHEMA east;
CREATE SCHEMA west;

CREATE TABLE east.points (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    observed_at timestamptz NOT NULL DEFAULT now(),
    geom geometry(Point, 4326) NOT NULL
);
CREATE TABLE west.points (LIKE east.points INCLUDING ALL);
CREATE TABLE east.boundaries (LIKE east.points INCLUDING ALL);
CREATE TABLE east.hidden (LIKE east.points INCLUDING ALL);
CREATE TABLE east.unlisted (LIKE east.points INCLUDING ALL);
CREATE TABLE east.replace_with (LIKE east.points INCLUDING ALL);
CREATE TABLE east.invalid (name text, geom geometry(Point, 4326));

INSERT INTO east.points (name, geom) VALUES ('east', ST_GeomFromText('POINT(1.1 1.1)', 4326));
INSERT INTO west.points (name, geom) VALUES ('west', ST_GeomFromText('POINT(1.1 1.1)', 4326));
INSERT INTO east.replace_with (name, geom) VALUES ('replacement', ST_GeomFromText('POINT(1.1 1.1)', 4326));
GRANT USAGE ON SCHEMA east, west TO georest_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA east, west TO georest_reader;
