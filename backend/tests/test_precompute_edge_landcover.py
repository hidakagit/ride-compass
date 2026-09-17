"""app/batch/precompute_edge_landcover.pyの検証。

ラスタ読み出しそのもの（build_ring・count_pixels_in_ring・RasterSource）は
`test_precompute_way_landcover.py`が共有モジュール`app/batch/_landcover.py`に対して
検証しており、ここで重ねない。ここが見るのは**区間単位に特有の部分**——物理区間ごとに
1回だけ読むこと、forward/backwardが同じ1行を共有すること、増分実行が2周目で止まること。

ridecompass_test DBへの実接続と一時GeoTIFFが要る（他のprecomputeバッチのテストと同じ
切り分け）。
"""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from sqlalchemy import text

from app.batch.precompute_edge_landcover import run
from app.domain.graph import WaySpec, build_road_graph
from tests.conftest import TEST_DATABASE_URL
from tests.road_graph_scaffolds import NODE1, NODE2, NODE3

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


def _write_all_trees_raster(path) -> str:
    """対象ノード（NODE1〜NODE3）のリングを完全に覆う、全画素Treesのラスタ。"""
    transform = from_origin(370000, 3960000, 10, 10)
    with rasterio.open(
        path, "w", driver="GTiff", height=1500, width=1500, count=1, dtype="uint8",
        crs="EPSG:32654", transform=transform,
    ) as ds:
        ds.write(np.full((1500, 1500), 2, dtype=np.uint8), 1)
    return str(path)


async def _save_way_with_edges(repository, session, way_specs, nodes) -> None:
    await repository.save_raw_ways(way_specs, nodes)
    await repository.save_graph(build_road_graph(way_specs, nodes, graph_version="v1"))
    await session.commit()


async def test_物理区間ごとに1行だけ書く(road_graph_repository, road_graph_session, tmp_path):
    """`road_edges`はforward/backwardを別行で持つが、鍵は向きに依らないため行は1つ。

    edge_idを鍵にすると、路面タイルが代表として残す向き（edge_id昇順）に行が無いときだけ
    値が落ちる。
    """
    way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
    await _save_way_with_edges(road_graph_repository, road_graph_session, [way], {1: NODE1, 2: NODE2})

    assert await run(TEST_DATABASE_URL, [_write_all_trees_raster(tmp_path / "54S_2025.tif")], 100.0, 10.0,
                     None, False, False) == 0

    rows = (
        await road_graph_session.execute(
            text("SELECT node_lo, node_hi, trees_percent, algorithm_version FROM edge_landcover WHERE osm_way_id = 100")
        )
    ).all()
    edge_count = (
        await road_graph_session.execute(text("SELECT count(*) FROM road_edges WHERE osm_way_id = 100"))
    ).scalar_one()
    assert edge_count == 2
    assert len(rows) == 1
    assert rows[0].trees_percent == 100.0
    assert rows[0].algorithm_version == "v1-ring10-100"
    assert rows[0].node_lo <= rows[0].node_hi


async def test_区間を2本持つwayは区間ごとに行を持つ(road_graph_repository, road_graph_session, tmp_path):
    """交差点で切られたwayは、区間の数だけ行ができる（way平均へ畳まない）。"""
    way = WaySpec(osm_way_id=101, node_ids=[1, 2, 3], highway="residential")
    crossing = WaySpec(osm_way_id=102, node_ids=[2, 3], highway="residential")
    await _save_way_with_edges(
        road_graph_repository, road_graph_session, [way, crossing], {1: NODE1, 2: NODE2, 3: NODE3}
    )

    assert await run(TEST_DATABASE_URL, [_write_all_trees_raster(tmp_path / "54S_2025.tif")], 100.0, 10.0,
                     None, False, False) == 0

    count = (
        await road_graph_session.execute(
            text("SELECT count(*) FROM edge_landcover WHERE osm_way_id = 101")
        )
    ).scalar_one()
    assert count == 2


async def test_増分実行は計算済みの区間を対象にしない(road_graph_repository, road_graph_session, tmp_path):
    """2周目は0件。全区間を毎回読み直すと、本番規模では実行のたびに数時間を払う。"""
    way = WaySpec(osm_way_id=103, node_ids=[1, 2], highway="residential")
    await _save_way_with_edges(road_graph_repository, road_graph_session, [way], {1: NODE1, 2: NODE2})
    raster = _write_all_trees_raster(tmp_path / "54S_2025.tif")

    assert await run(TEST_DATABASE_URL, [raster], 100.0, 10.0, None, False, False) == 0
    first = (
        await road_graph_session.execute(text("SELECT computed_at FROM edge_landcover WHERE osm_way_id = 103"))
    ).scalar_one()

    assert await run(TEST_DATABASE_URL, [raster], 100.0, 10.0, None, False, False) == 0
    second = (
        await road_graph_session.execute(text("SELECT computed_at FROM edge_landcover WHERE osm_way_id = 103"))
    ).scalar_one()
    assert first == second


async def test_ラスタ範囲外の区間も値なしで記録する(road_graph_repository, road_graph_session, tmp_path):
    """行を残さないと、増分実行が毎回同じ区間をラスタ読み込みからやり直す
    （way単位と同じ扱い）。"""
    way = WaySpec(osm_way_id=104, node_ids=[1, 2], highway="residential")
    await _save_way_with_edges(road_graph_repository, road_graph_session, [way], {1: NODE1, 2: NODE2})

    far_path = tmp_path / "far_2025.tif"
    with rasterio.open(
        far_path, "w", driver="GTiff", height=50, width=50, count=1, dtype="uint8",
        crs="EPSG:32654", transform=from_origin(100000, 3000000, 10, 10),
    ) as ds:
        ds.write(np.full((50, 50), 2, dtype=np.uint8), 1)

    assert await run(TEST_DATABASE_URL, [str(far_path)], 100.0, 10.0, None, False, False) == 0

    row = (
        await road_graph_session.execute(
            text("SELECT trees_percent, source_raster_set FROM edge_landcover WHERE osm_way_id = 104")
        )
    ).one()
    assert row.trees_percent is None
    assert row.source_raster_set
