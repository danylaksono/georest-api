
------------------------------------------------------------------------------------
-- QUERY: Find Extent (xmin ymin xmax ymax)

CREATE SCHEMA IF NOT EXISTS postgisftw;

CREATE OR REPLACE
	FUNCTION postgisftw.query_extent(table_name text)
RETURNS 
  TABLE(xmin double precision,
	    ymin double precision,
	   	xmax double precision,
		ymax double precision
	   )
AS $$
    BEGIN
	RETURN QUERY
		EXECUTE format(
		'with data as (
		  	SELECT st_geomfromtext(st_astext(ST_Extent(ST_Transform(ta.geom, 4326))))::geometry as geom 
		  	FROM ' || table_name ||' ta)
		SELECT
			min(st_xmin(data.geom)) as xmin,
			min(st_ymin(data.geom)) as ymin,
			max(st_xmax(data.geom)) as xmax,
			max(st_ymax(data.geom)) as ymax
		FROM data
		');
    END;
$$ 
LANGUAGE 'plpgsql' STABLE STRICT PARALLEL SAFE;
COMMENT ON FUNCTION postgisftw.query_extent IS 
'Get extent of a table or layer, returns xmin, ymin, xmax, ymax';

------------------------------------------------------------------------------------
-- QUERY: Get Column Statistics (avg, count, min, max, sum)

CREATE SCHEMA IF NOT EXISTS postgisftw;

CREATE OR REPLACE
	FUNCTION postgisftw.query_stats(
		table_name text,
		col_name text
	)
RETURNS 
  TABLE(col_avg double precision,
	    col_count double precision,
	   	col_min double precision,
		col_max double precision,
		col_sum double precision
	   )
AS $$
    BEGIN
	RETURN QUERY
		EXECUTE format(
		'SELECT
			avg(tbl.'|| quote_ident(col_name) || ')::double precision as col_avg,
			count(tbl.'|| quote_ident(col_name) || ')::double precision as col_count,
    		min(tbl.'|| quote_ident(col_name) || ')::double precision as col_min,
			max(tbl.'|| quote_ident(col_name) || ')::double precision as col_max,
    		sum(tbl.'|| quote_ident(col_name) || ')::double precision as col_sum
		 FROM ' || table_name || ' tbl
		');
    END;
$$ 
LANGUAGE 'plpgsql' STABLE STRICT PARALLEL SAFE;
COMMENT ON FUNCTION postgisftw.query_stats IS 
'Given field name, get basic statistics from specific table';



-- CREATE OR REPLACE
-- FUNCTION postgisftw.find_bbox(table_name text)
-- RETURNS
--   TABLE(feature_extent text)
-- AS $$
--     BEGIN
--     RETURN QUERY
    
--     END;
-- $$ LANGUAGE 'plpgsql'
-- STABLE
-- STRICT
-- PARALLEL SAFE;