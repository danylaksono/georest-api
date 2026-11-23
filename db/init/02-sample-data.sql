CREATE SCHEMA IF NOT EXISTS georest_demo;

CREATE TABLE georest_demo.demo_points (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    observed_at timestamptz NOT NULL,
    geom geometry(Point, 4326) NOT NULL
);
INSERT INTO georest_demo.demo_points (name, observed_at, geom) VALUES
    ('Alpha', '2025-01-01T00:00:00Z', ST_SetSRID(ST_MakePoint(1.1, 1.1), 4326)),
    ('Beta', '2025-02-01T00:00:00Z', ST_SetSRID(ST_MakePoint(1.2, 1.2), 4326));
COMMENT ON TABLE georest_demo.demo_points IS 'Demo observations';

CREATE TABLE georest_demo.demo_lines (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    geom geometry(LineString, 4326) NOT NULL
);
INSERT INTO georest_demo.demo_lines (name, geom) VALUES
    ('Demo line', ST_GeomFromText('LINESTRING(1.08 1.08, 1.25 1.25)', 4326));
COMMENT ON TABLE georest_demo.demo_lines IS 'Demo lines';

CREATE TABLE georest_demo.demo_polygons (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name text NOT NULL,
    geom geometry(Polygon, 4326) NOT NULL
);
INSERT INTO georest_demo.demo_polygons (name, geom) VALUES
    ('Demo area', ST_GeomFromText('POLYGON((1 1, 1.3 1, 1.3 1.3, 1 1.3, 1 1))', 4326));
COMMENT ON TABLE georest_demo.demo_polygons IS 'Demo polygons';

CREATE INDEX ON georest_demo.demo_points USING gist (geom);
CREATE INDEX ON georest_demo.demo_lines USING gist (geom);
CREATE INDEX ON georest_demo.demo_polygons USING gist (geom);
GRANT USAGE ON SCHEMA georest_demo TO georest_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA georest_demo TO georest_reader;
