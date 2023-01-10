from fastapi import FastAPI, HTTPException
from typing import Tuple
from pydantic import BaseModel
from geojson import Feature, FeatureCollection, Point
from shapely.geometry import shape, Point as ShapelyPoint, mapping

app = FastAPI()

class Point(BaseModel):
    lat: float
    lon: float

@app.get("/buffer")
def get_buffer(lat: float, lon:float, radius: float):
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise HTTPException(status_code=400, detail="Invalid latitude or longitude")
    shapely_point = ShapelyPoint(float(lat), float(lon))
    buffer = shapely_point.buffer(float(radius))
    geo_json = mapping(buffer)
    return Feature(geometry=geo_json, properties={})

