"""app/batch/precompute_way_landcover.pyの検証。

純粋ロジック（algorithm_version・infer_data_version_from_filename・build_ring・
count_pixels_in_ring）はrasterio.io.MemoryFileの合成ラスタで検証する（実ファイル不要）。
run()自体の結合検証はridecompass_test DBへの実接続と一時GeoTIFFファイルが要る
（他のprecomputeバッチのテストと同じ切り分け方針、conftest.pyのroad_graph_session/
road_graph_repositoryフィクスチャ参照）。
"""

import numpy as np
import pytest
import rasterio
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import LineString
from sqlalchemy import text

from app.batch.precompute_way_landcover import (
    algorithm_version,
    build_ring,
    count_pixels_in_ring,
    infer_data_version_from_filename,
    run,
    run_default,
)
from app.config import settings
from app.domain.graph import WaySpec
from tests.conftest import TEST_DATABASE_URL

NODE1 = (35.700, 139.700)
NODE2 = (35.701, 139.701)
# NODE1/NODE2をEPSG:32654へ変換すると概ねx=382000-383000, y=3950800-3951800m付近になる。
FAR_NODE1 = (34.500, 135.500)
FAR_NODE2 = (34.501, 135.501)


def test_algorithm_version_includes_ring_radii():
    assert algorithm_version(10, 100) == "v1-ring10-100"


def test_infer_data_version_from_filename_extracts_start_year():
    assert infer_data_version_from_filename("54S_20250101-20260101.tif") == "2025"


def test_infer_data_version_from_filename_returns_none_when_no_match():
    assert infer_data_version_from_filename("no-year-here.tif") is None


def _make_memory_dataset(fill_value: int, built_block: tuple[slice, slice] | None = None):
    transform = from_origin(382000, 3951800, 10, 10)
    data = np.full((100, 100), fill_value, dtype=np.uint8)
    if built_block is not None:
        data[built_block] = 7
    memfile = MemoryFile()
    with memfile.open(driver="GTiff", height=100, width=100, count=1, dtype="uint8", crs="EPSG:32654", transform=transform) as ds:
        ds.write(data, 1)
    return memfile


def test_count_pixels_in_ring_detects_mixed_classes():
    with _make_memory_dataset(fill_value=2, built_block=(slice(40, 60), slice(40, 60))) as memfile, memfile.open() as ds:
        # ボックス境界(x=782, y=3800)付近にまたがる線（ラスタ原点382000,3951800、10m画素、
        # 行40-59・列40-59がBuilt=x:[382400,382600), y:[3951200,3951400)）。
        line = LineString([(382600, 3951300), (382600, 3951350)])
        ring = build_ring(line, inner_m=10, outer_m=50)
        counts = count_pixels_in_ring(ds, ring)
        assert counts is not None
        assert 2 in counts and 7 in counts


def test_count_pixels_in_ring_returns_none_when_outside_raster():
    with _make_memory_dataset(fill_value=2) as memfile, memfile.open() as ds:
        line = LineString([(0, 0), (0, 10)])
        ring = build_ring(line, inner_m=10, outer_m=50)
        assert count_pixels_in_ring(ds, ring) is None


class TestRunIntegration:
    pytestmark = [
        pytest.mark.asyncio(loop_scope="module"),
        pytest.mark.xdist_group(name="postgis"),
        pytest.mark.postgis,
    ]

    async def test_run_default_raises_when_raster_paths_unset_and_not_dry_run(self, monkeypatch):
        monkeypatch.setattr(settings, "lulc_raster_paths", "")
        with pytest.raises(ValueError, match="lulc_raster_paths"):
            await run_default(TEST_DATABASE_URL, False)

    async def test_run_default_dry_run_does_not_require_raster_paths(self, monkeypatch):
        monkeypatch.setattr(settings, "lulc_raster_paths", "")
        assert await run_default(TEST_DATABASE_URL, True) == 0

    async def test_run_writes_percentages_for_way_within_raster_bounds(
        self, road_graph_repository, road_graph_session, tmp_path
    ):
        way = WaySpec(osm_way_id=100, node_ids=[1, 2], highway="residential")
        await road_graph_repository.save_raw_ways([way], {1: NODE1, 2: NODE2})
        await road_graph_session.commit()

        raster_path = tmp_path / "54S_20250101-20260101.tif"
        transform = from_origin(382000, 3951800, 10, 10)
        data = np.full((100, 100), 2, dtype=np.uint8)  # 全画素Trees
        with rasterio.open(
            raster_path, "w", driver="GTiff", height=100, width=100, count=1, dtype="uint8",
            crs="EPSG:32654", transform=transform,
        ) as ds:
            ds.write(data, 1)

        exit_code = await run(TEST_DATABASE_URL, [str(raster_path)], 100.0, 10.0, None, False, False)
        assert exit_code == 0

        row = (
            await road_graph_session.execute(
                text("SELECT trees_percent, data_version, algorithm_version FROM way_landcover WHERE osm_way_id = 100")
            )
        ).one()
        assert row.trees_percent == 100.0
        assert row.data_version == "2025"  # ファイル名から推定
        assert row.algorithm_version == "v1-ring10-100"

    async def test_run_skips_way_outside_raster_bounds(self, road_graph_repository, road_graph_session, tmp_path):
        way = WaySpec(osm_way_id=101, node_ids=[3, 4], highway="residential")
        await road_graph_repository.save_raw_ways([way], {3: FAR_NODE1, 4: FAR_NODE2})
        await road_graph_session.commit()

        raster_path = tmp_path / "far.tif"
        transform = from_origin(382000, 3951800, 10, 10)
        with rasterio.open(
            raster_path, "w", driver="GTiff", height=100, width=100, count=1, dtype="uint8",
            crs="EPSG:32654", transform=transform,
        ) as ds:
            ds.write(np.full((100, 100), 2, dtype=np.uint8), 1)

        exit_code = await run(TEST_DATABASE_URL, [str(raster_path)], 100.0, 10.0, "2025", False, False)
        assert exit_code == 0

        result = await road_graph_session.execute(
            text("SELECT 1 FROM way_landcover WHERE osm_way_id = 101")
        )
        assert result.first() is None

    async def test_run_dry_run_does_not_write(self, road_graph_repository, road_graph_session, tmp_path):
        way = WaySpec(osm_way_id=102, node_ids=[5, 6], highway="residential")
        await road_graph_repository.save_raw_ways([way], {5: NODE1, 6: NODE2})
        await road_graph_session.commit()

        exit_code = await run(TEST_DATABASE_URL, [], 100.0, 10.0, "2025", False, True)
        assert exit_code == 0

        result = await road_graph_session.execute(
            text("SELECT 1 FROM way_landcover WHERE osm_way_id = 102")
        )
        assert result.first() is None

    async def test_run_recompute_flag_reprocesses_existing_rows(
        self, road_graph_repository, road_graph_session, tmp_path
    ):
        way = WaySpec(osm_way_id=103, node_ids=[7, 8], highway="residential")
        await road_graph_repository.save_raw_ways([way], {7: NODE1, 8: NODE2})
        await road_graph_session.commit()

        raster_path = tmp_path / "recompute.tif"
        transform = from_origin(382000, 3951800, 10, 10)
        with rasterio.open(
            raster_path, "w", driver="GTiff", height=100, width=100, count=1, dtype="uint8",
            crs="EPSG:32654", transform=transform,
        ) as ds:
            ds.write(np.full((100, 100), 2, dtype=np.uint8), 1)
        await run(TEST_DATABASE_URL, [str(raster_path)], 100.0, 10.0, "2025", False, False)

        # 2回目（--recompute無し）は増分実行のため対象0件（既に行がある）→ラスタを別内容に
        # 差し替えても反映されないことを確認する。
        with rasterio.open(raster_path, "r+") as ds:
            ds.write(np.full((100, 100), 7, dtype=np.uint8), 1)
        await run(TEST_DATABASE_URL, [str(raster_path)], 100.0, 10.0, "2025", False, False)
        row = (
            await road_graph_session.execute(
                text("SELECT trees_percent, built_percent FROM way_landcover WHERE osm_way_id = 103")
            )
        ).one()
        assert row.trees_percent == 100.0

        # --recomputeありなら新しいラスタ内容が反映される。
        await run(TEST_DATABASE_URL, [str(raster_path)], 100.0, 10.0, "2025", True, False)
        row = (
            await road_graph_session.execute(
                text("SELECT trees_percent, built_percent FROM way_landcover WHERE osm_way_id = 103")
            )
        ).one()
        assert row.built_percent == 100.0
