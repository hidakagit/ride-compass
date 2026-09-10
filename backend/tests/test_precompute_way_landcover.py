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
    raster_set_fingerprint,
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


def test_raster_source_rejects_rings_that_stick_out_of_the_raster(tmp_path):
    """リングがラスタ範囲からはみ出すwayは、そのラスタの対象にしない。

    一部だけ重なるラスタで割合を出すと、重なった側の土地被覆だけで100%を分け合う
    「もっともらしい数値」が正規の行として入り、NULLでないため鮮度台帳にも現れない。
    """
    from app.batch.precompute_way_landcover import _RasterSource

    raster_path = tmp_path / "bounds.tif"
    transform = from_origin(382000, 3951800, 10, 10)  # x:[382000,383000] y:[3950800,3951800]
    with rasterio.open(
        raster_path, "w", driver="GTiff", height=100, width=100, count=1, dtype="uint8",
        crs="EPSG:32654", transform=transform,
    ) as ds:
        ds.write(np.full((100, 100), 2, dtype=np.uint8), 1)

    source = _RasterSource(str(raster_path))
    try:
        inside = build_ring(LineString([(382400, 3951300), (382500, 3951300)]), inner_m=10, outer_m=100)
        assert source.contains(inside)

        # 西端（x=382000）へ寄せた線。100mバッファがラスタの外へ出る。
        straddling = build_ring(LineString([(382050, 3951300), (382150, 3951300)]), inner_m=10, outer_m=100)
        assert not source.contains(straddling)
        assert source.intersects(straddling)

        far = build_ring(LineString([(0, 0), (0, 100)]), inner_m=10, outer_m=100)
        assert not source.contains(far)
        assert not source.intersects(far)
    finally:
        source.close()


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

    async def test_run_records_no_value_for_way_outside_raster_bounds(
        self, road_graph_repository, road_graph_session, tmp_path
    ):
        """ラスタ範囲外のwayは割合NULLの行で「計算済み・値なし」を記録する。

        行を作らないと、増分実行が毎回同じwayをラスタ読み込みからやり直す（結果は毎回同じ）。
        材料としての扱いは行が無い場合と変わらない——読み出しはLEFT JOINで、NULL列は
        欠損としてそのまま扱われる。
        """
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

        row = (
            await road_graph_session.execute(
                text(
                    "SELECT trees_percent, valid_pixels, source_raster_set, algorithm_version "
                    "FROM way_landcover WHERE osm_way_id = 101"
                )
            )
        ).one()
        assert row.trees_percent is None
        assert row.valid_pixels is None
        assert row.source_raster_set  # どのラスタ構成で値なしと決めたかを残す
        assert row.algorithm_version == "v1-ring10-100"

    async def test_run_records_no_value_for_way_whose_ring_straddles_the_raster_edge(
        self, road_graph_repository, road_graph_session, tmp_path
    ):
        """リングがラスタ端をまたぐwayは割合を書かない（偏った割合を書き込まない）。

        値なしの行だけを残す。ラスタを足せば値を持ちうるため、行にはラスタ構成の指紋を
        添え、構成が変われば増分実行が対象へ戻す（下のテスト参照）。
        """
        way = WaySpec(osm_way_id=104, node_ids=[9, 10], highway="residential")
        await road_graph_repository.save_raw_ways([way], {9: NODE1, 10: NODE2})
        await road_graph_session.commit()

        # NODE1/NODE2はEPSG:32654で概ね(382389,3951454)-(382481,3951563)。ラスタの南西端を
        # そこへ合わせ、100mバッファが西・南へはみ出す配置にする。
        raster_path = tmp_path / "edge.tif"
        transform = from_origin(382450, 3952500, 10, 10)  # x:[382450,383450] y:[3951500,3952500]
        with rasterio.open(
            raster_path, "w", driver="GTiff", height=100, width=100, count=1, dtype="uint8",
            crs="EPSG:32654", transform=transform,
        ) as ds:
            ds.write(np.full((100, 100), 2, dtype=np.uint8), 1)

        exit_code = await run(TEST_DATABASE_URL, [str(raster_path)], 100.0, 10.0, "2025", False, False)
        assert exit_code == 0

        row = (
            await road_graph_session.execute(
                text("SELECT trees_percent, source_raster_set FROM way_landcover WHERE osm_way_id = 104")
            )
        ).one()
        assert row.trees_percent is None
        assert row.source_raster_set

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

    async def test_no_value_row_is_skipped_on_rerun_with_the_same_rasters(
        self, road_graph_repository, road_graph_session, tmp_path
    ):
        """同じラスタ構成での再実行は、値なしと確定済みのwayを対象にしない。

        本タスク（T688）が無くすはずの無駄そのもの。行が無いままだと、結果が毎回同じ
        「値なし」であるにも関わらず実行のたびにラスタ読み込みからやり直される。
        """
        way = WaySpec(osm_way_id=105, node_ids=[11, 12], highway="residential")
        await road_graph_repository.save_raw_ways([way], {11: FAR_NODE1, 12: FAR_NODE2})
        await road_graph_session.commit()

        raster_path = tmp_path / "far2.tif"
        transform = from_origin(382000, 3951800, 10, 10)
        with rasterio.open(
            raster_path, "w", driver="GTiff", height=100, width=100, count=1, dtype="uint8",
            crs="EPSG:32654", transform=transform,
        ) as ds:
            ds.write(np.full((100, 100), 2, dtype=np.uint8), 1)

        await run(TEST_DATABASE_URL, [str(raster_path)], 100.0, 10.0, "2025", False, False)
        first = (
            await road_graph_session.execute(
                text("SELECT computed_at FROM way_landcover WHERE osm_way_id = 105")
            )
        ).one()

        # 同じ構成での2回目は対象0件のため、行の内容（computed_at）が動かない。
        await run(TEST_DATABASE_URL, [str(raster_path)], 100.0, 10.0, "2025", False, False)
        second = (
            await road_graph_session.execute(
                text("SELECT computed_at FROM way_landcover WHERE osm_way_id = 105")
            )
        ).one()

        assert second.computed_at == first.computed_at

    async def test_no_value_row_is_retried_when_the_raster_set_changes(
        self, road_graph_repository, road_graph_session, tmp_path
    ):
        """ラスタ構成が変われば、値なしと確定済みのwayも増分実行の対象へ戻る。

        「値なし」はそのラスタ構成での結論でしかない——1枚足せば、境界またぎ・範囲外
        だったwayは値を持ちうる。指紋で判定しないと、ラスタを追加しても取りこぼす。
        """
        way = WaySpec(osm_way_id=106, node_ids=[13, 14], highway="residential")
        await road_graph_repository.save_raw_ways([way], {13: FAR_NODE1, 14: FAR_NODE2})
        await road_graph_session.commit()

        # 1枚目はwayから外れており、値なしの行だけが残る。
        far_raster = tmp_path / "far3.tif"
        with rasterio.open(
            far_raster, "w", driver="GTiff", height=100, width=100, count=1, dtype="uint8",
            crs="EPSG:32654", transform=from_origin(382000, 3951800, 10, 10),
        ) as ds:
            ds.write(np.full((100, 100), 2, dtype=np.uint8), 1)
        await run(TEST_DATABASE_URL, [str(far_raster)], 100.0, 10.0, "2025", False, False)
        assert (
            await road_graph_session.execute(
                text("SELECT trees_percent FROM way_landcover WHERE osm_way_id = 106")
            )
        ).one().trees_percent is None

        # wayを覆う2枚目を足す（--recompute無しのまま）。
        near_raster = tmp_path / "near3.tif"
        with rasterio.open(
            near_raster, "w", driver="GTiff", height=200, width=200, count=1, dtype="uint8",
            crs="EPSG:32654", transform=from_origin(-6000, 3832500, 10, 10),
        ) as ds:
            ds.write(np.full((200, 200), 2, dtype=np.uint8), 1)
        await run(TEST_DATABASE_URL, [str(far_raster), str(near_raster)], 100.0, 10.0, "2025", False, False)

        row = (
            await road_graph_session.execute(
                text("SELECT trees_percent FROM way_landcover WHERE osm_way_id = 106")
            )
        ).one()
        assert row.trees_percent == 100.0


def test_raster_set_fingerprint_ignores_order_and_directory():
    # 同じラスタ集合なら、渡す順や置き場所が違っても同じ指紋になる（順序で値なし行が
    # 無駄に対象へ戻らないようにするため）。
    a = raster_set_fingerprint(["/data/a.tif", "/data/b.tif"])
    b = raster_set_fingerprint(["/other/b.tif", "/other/a.tif"])
    assert a == b
    assert a != raster_set_fingerprint(["/data/a.tif"])
