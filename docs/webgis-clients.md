# Connect a WebGIS client

These examples use the demo origin `http://localhost`. Change the origin to your deployment's `PUBLIC_URL`. Find feature IDs in `/api/collections?f=json` and tile IDs in `/tiles/catalog`.

## MapLibre

Use the TileJSON endpoint as a vector source. Match `source-layer` to an entry in TileJSON's `vector_layers` array.

```js
map.on('load', () => {
  map.addSource('observations', {
    type: 'vector',
    url: 'http://localhost/tiles/demo_points',
  });
  map.addLayer({
    id: 'observations',
    type: 'circle',
    source: 'observations',
    'source-layer': 'demo_points',
    paint: { 'circle-radius': 6, 'circle-color': '#1565c0' },
  });
});
```

Center the map on longitude `1.15` and latitude `1.15` to see the demo. [MapLibre vector source reference](https://maplibre.org/maplibre-style-spec/sources/#vector)

## OpenLayers

For features, load GeoJSON from the OGC collection's `items` URL. Follow the response's pagination links if you need every feature in a larger collection. For tiles, use the Martin XYZ template with `MVT`.

```js
import GeoJSON from 'ol/format/GeoJSON.js';
import MVT from 'ol/format/MVT.js';
import VectorLayer from 'ol/layer/Vector.js';
import VectorTileLayer from 'ol/layer/VectorTile.js';
import VectorSource from 'ol/source/Vector.js';
import VectorTileSource from 'ol/source/VectorTile.js';

const features = new VectorLayer({
  source: new VectorSource({
    url: 'http://localhost/api/collections/demo_points/items?f=json',
    format: new GeoJSON(),
  }),
});
const tiles = new VectorTileLayer({
  source: new VectorTileSource({
    url: 'http://localhost/tiles/demo_points/{z}/{x}/{y}',
    format: new MVT(),
  }),
});
```

[OpenLayers vector tile source reference](https://openlayers.org/en/latest/apidoc/module-ol_source_VectorTile-VectorTile.html)

## QGIS

Add a **WFS / OGC API Features** connection using `http://localhost/api` and select the collection. For vector tiles, add a generic vector tile connection with `http://localhost/tiles/demo_points/{z}/{x}/{y}`. [QGIS OGC client documentation](https://docs.qgis.org/3.44/en/docs/user_manual/working_with_ogc/ogc_client_support.html)

If read authentication is enabled at Level 3, configure HTTP Basic credentials in the client for feature and tile requests. In browser applications, use the client's custom request handling or a server-side proxy to supply credentials. For cross-origin access, put the front-end origin in `CORS_ORIGINS`.
