"""Check the public demo through Traefik."""

import argparse
import json
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

MVT_TYPES = {"application/x-protobuf", "application/vnd.mapbox-vector-tile"}
DEMO_COLLECTIONS = {"demo_points", "demo_lines", "demo_polygons"}


def request(url, *, method="GET", headers=None, data=None):
    try:
        response = urlopen(Request(url, method=method, headers=headers or {}, data=data), timeout=12)
    except HTTPError as error:
        response = error
    with response:
        return response.status, response.headers, response.read()


def json_response(url):
    status, _, body = request(url)
    assert status == 200, f"GET {url} returned {status}"
    return json.loads(body)


def collection_ids(origin):
    return {item["id"] for item in json_response(f"{origin}/api/collections?f=json")["collections"]}


def tile_ids(origin):
    return set(json_response(f"{origin}/tiles/catalog")["tiles"])


def demo_tile_urls(origin):
    tilejson = json_response(f"{origin}/tiles/demo_points")
    direct = tilejson["tiles"][0].format(z=4, x=8, y=7)
    ogc = json_response(f"{origin}/api/collections/demo_points/tiles?f=json")
    template = next(link["href"] for link in ogc["links"] if link["rel"] == "item")
    through_api = template.format(
        tileMatrixSetId="WebMercatorQuad", tileMatrix=4, tileRow=7, tileCol=8
    )
    expected = urlsplit(origin)
    for url in (direct, through_api):
        actual = urlsplit(url)
        assert (actual.scheme, actual.netloc) == (expected.scheme, expected.netloc), url
    return direct, through_api


def tile_bytes(url):
    status, headers, body = request(url)
    assert status == 200 and body, f"expected a nonempty tile from {url}, got {status}"
    assert headers.get_content_type() in MVT_TYPES, headers.get("Content-Type")
    return body


def smoke(origin, level):
    assert collection_ids(origin) == DEMO_COLLECTIONS
    assert tile_ids(origin) == DEMO_COLLECTIONS
    items = f"{origin}/api/collections/demo_points/items"
    assert json_response(f"{items}?f=json")["numberReturned"] >= 2
    query = urlencode({"f": "json", "filter-lang": "cql2-text", "filter": "name = 'Alpha'"})
    features = json_response(f"{items}?{query}")
    assert features["type"] == "FeatureCollection"
    assert [item["properties"]["name"] for item in features["features"]] == ["Alpha"]
    assert features["features"][0]["geometry"]["type"] == "Point"

    direct, through_api = demo_tile_urls(origin)
    assert tile_bytes(direct) == tile_bytes(through_api)
    for path in ("/api/admin", "/dashboard/", "/tiles/health", "/tiles/metrics", "/tiles/config", "/apix"):
        assert request(origin + path)[0] in (403, 404), path
    baseline = json_response(f"{items}?f=json")["numberReturned"]
    assert request(items, method="POST")[0] in (401, 403, 404, 405)
    assert json_response(f"{items}?f=json")["numberReturned"] == baseline

    if level >= 2:
        assert request(direct)[1]["X-Cache"] == "HIT"
        assert request(direct, headers={"Cookie": "test=1"})[1]["X-Cache"] == "PASS"
        assert request(direct, headers={"Authorization": "Bearer disposable"})[1]["X-Cache"] == "PASS"
        assert request(direct, method="PURGE")[0] in (403, 404, 405)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost")
    parser.add_argument("--level", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    smoke(args.url.rstrip("/"), args.level)
    print(f"Level {args.level} demo smoke passed")


if __name__ == "__main__":
    main()
