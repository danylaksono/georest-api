from pathlib import Path

import pytest
from georest_config.manifest import ConfigError, read_manifest


def test_publication_precedence():
    path = Path(__file__).resolve().parents[1] / "config/collections.example.yml"
    points, boundaries = read_manifest(path)
    assert (points.id, points.schema, points.cache, points.tiles) == (
        "survey-points", "survey", "volatile", True,
    )
    assert boundaries.tiles is False


@pytest.mark.parametrize(
    "source",
    [
        "collections: {health: {schema: a, table: b, geometry: c}}",
        "collections: {one: {schema: a, table: b, geometry: c, tiles: 'false'}}",
        "collections: {one: {schema: a, table: b, geometry: c}, one: {schema: d}}",
    ],
)
def test_invalid_manifest(tmp_path, source):
    path = tmp_path / "invalid.yml"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(ConfigError):
        read_manifest(path)
