from sqlalchemy import text

from app.domain.region import tile_bounds_lonlat
from app.infrastructure import accident_models  # noqa: F401  Base.metadataへテーブル登録するためのimport
from app.infrastructure.accident_repository import AccidentTileQuery

# road_graph_repository.pyのtest_get_road_surface_tile_mvt_*と同じ考え方（実DB＝ridecompass_test
# への統合テスト、conftest.pyのroad_graph_sessionフィクスチャを共有する）。

MVT_Z, MVT_X, MVT_Y = 14, 14549, 6450


def _bbox():
    return tile_bounds_lonlat(MVT_Z, MVT_X, MVT_Y)


async def _insert_accident(session, accident_id, lat, lon, *, fatal, involves_bicycle, year=2023):
    await session.execute(
        text(
            "INSERT INTO accident_points "
            "(accident_id, occurred_year, fatal, involves_bicycle, attrs, geom, updated_at) "
            "VALUES (:id, :year, :fatal, :bicycle, '{}'::jsonb, "
            "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), now())"
        ),
        {"id": accident_id, "year": year, "fatal": fatal, "bicycle": involves_bicycle, "lat": lat, "lon": lon},
    )
    await session.flush()


async def test_get_accident_tile_mvt_returns_empty_bytes_when_no_points(road_graph_session):
    query = AccidentTileQuery(road_graph_session)

    tile = await query.get_accident_tile_mvt(MVT_Z, MVT_X, MVT_Y, _bbox())

    assert tile == b""


async def test_get_accident_tile_mvt_encodes_layer_and_properties(road_graph_session):
    import mapbox_vector_tile

    bbox = _bbox()
    lat = (bbox.min_latitude + bbox.max_latitude) / 2
    lon = (bbox.min_longitude + bbox.max_longitude) / 2
    await _insert_accident(road_graph_session, "2023-1", lat, lon, fatal=True, involves_bicycle=False)
    await _insert_accident(road_graph_session, "2023-2", lat, lon, fatal=False, involves_bicycle=True)

    query = AccidentTileQuery(road_graph_session)
    tile = await query.get_accident_tile_mvt(MVT_Z, MVT_X, MVT_Y, bbox)

    decoded = mapbox_vector_tile.decode(tile)
    assert set(decoded.keys()) == {"accidents"}
    properties = sorted(
        (feature["properties"] for feature in decoded["accidents"]["features"]),
        key=lambda p: p["fatal"],
    )
    assert properties == [
        {"fatal": False, "involves_bicycle": True, "occurred_year": 2023},
        {"fatal": True, "involves_bicycle": False, "occurred_year": 2023},
    ]


async def test_get_accident_tile_mvt_excludes_points_outside_tile(road_graph_session):
    bbox = _bbox()
    far_lat, far_lon = 43.0, 141.0  # 北海道、対象タイル外
    await _insert_accident(road_graph_session, "2023-far", far_lat, far_lon, fatal=False, involves_bicycle=False)

    query = AccidentTileQuery(road_graph_session)
    tile = await query.get_accident_tile_mvt(MVT_Z, MVT_X, MVT_Y, bbox)

    assert tile == b""
