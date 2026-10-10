"""材料の欠損割合（`infrastructure/material_coverage.py`の集計・`services/material_coverage_service.py`のレポート）。

レポートの組み立ては件数を与えて見る。集計はテスト用DBで流して、道と区間の母集団ごとに欠損を数えることを見る
（全材料の判定式が同じ1回の問い合わせに並ぶので、どれかが実在しない列を読めば問い合わせごと落ちる）。

ここで見ないもの:
- 材料ごとの判定式・測らない理由（カタログの宣言） → 宣言そのもので、テストに書き写さない
- どの材料も測るか測らない理由を持つか → `test_material_catalog.py`
- レポートを管理APIの応答へ出すこと・DBの失敗を503にすること → `test_material_catalog_routes.py`
"""

from datetime import datetime, timezone

import pytest

from app.batch import derive_elevation, derive_topology
from app.batch.dem_tile_store import PRODUCT_PRIORITY
from app.domain.material_catalog import MATERIAL_CATALOG
from app.domain.region import BoundingBox
from app.infrastructure.material_coverage import (
    MATERIAL_COVERAGE_EXCLUSIONS,
    MATERIAL_COVERAGE_SPECS,
    MaterialCoverageCounts,
    MaterialCoverageQuery,
)
from app.services.material_coverage_service import (
    MaterialCoverageCounted,
    MaterialCoverageExcluded,
    MaterialCoverageService,
    build_material_coverage_report,
)
from tests.conftest import raw_connection
from tests.source_ingest import dem_tile_records, ingest_records, way_record

COMPUTED_AT = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _counts(way_total: int = 10, edge_total: int = 4, **missing_overrides: int) -> MaterialCoverageCounts:
    missing = {material_id: 0 for material_id in MATERIAL_COVERAGE_SPECS}
    missing.update(missing_overrides)
    return MaterialCoverageCounts(way_total=way_total, edge_total=edge_total, missing_by_material=missing)


# --- レポート組み立て（純関数） ---


def test_build_report_lists_all_catalog_materials_in_catalog_order():
    report = build_material_coverage_report(_counts(), COMPUTED_AT)

    assert [e.material_id for e in report.materials] == list(MATERIAL_CATALOG)


def test_build_report_computes_ratio_against_population_total():
    report = build_material_coverage_report(_counts(way_total=10, edge_total=4, surface=8, gradient_percent=3), COMPUTED_AT)
    by_id = {e.material_id: e for e in report.materials}

    surface = by_id["surface"]
    assert isinstance(surface, MaterialCoverageCounted)
    assert surface.population == "way"
    assert (surface.total, surface.missing) == (10, 8)
    assert surface.missing_ratio == pytest.approx(0.8)

    gradient = by_id["gradient_percent"]
    assert isinstance(gradient, MaterialCoverageCounted)
    assert gradient.population == "edge"
    assert (gradient.total, gradient.missing) == (4, 3)
    assert gradient.missing_ratio == pytest.approx(0.75)


def test_build_report_marks_excluded_materials_with_reason():
    report = build_material_coverage_report(_counts(), COMPUTED_AT)
    by_id = {e.material_id: e for e in report.materials}

    wind = by_id["wind_drag_ratio"]
    assert isinstance(wind, MaterialCoverageExcluded)
    assert wind.excluded_reason == MATERIAL_COVERAGE_EXCLUSIONS["wind_drag_ratio"]


def test_build_report_returns_none_ratio_when_population_is_empty():
    report = build_material_coverage_report(_counts(way_total=0, edge_total=0), COMPUTED_AT)

    measured = [entry for entry in report.materials if isinstance(entry, MaterialCoverageCounted)]
    assert measured, "測る材料が1つも無い"
    for entry in measured:
        assert entry.total == 0
        assert entry.missing_ratio is None


# --- 集計（テスト用DB） ---


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.xdist_group(name="postgis")
@pytest.mark.postgis
async def test_the_report_counts_missing_values_per_population_on_the_database(road_graph_session):
    # 道3本（路面のタグは1本だけ）を取り込んで区間へ切る。標高は道1の周りにだけ置き、その区間だけが勾配を持つ。
    await ingest_records("osm_way", [
        way_record(way_id, [(139.70, 35.68 + 0.001 * way_id), (139.701, 35.68 + 0.001 * way_id)],
                   [way_id * 10, way_id * 10 + 1], tags)
        for way_id, tags in {1: {"surface": "asphalt"}, 2: {}, 3: {}}.items()])
    area = BoundingBox(min_latitude=35.6805, min_longitude=139.6995, max_latitude=35.6835, max_longitude=139.7015)
    await ingest_records("dem", dem_tile_records(
        PRODUCT_PRIORITY[0], 15, area, lambda lon, lat: 50.0 if lat < 35.6815 else None))
    async with raw_connection() as conn:
        await derive_topology.derive(conn)
        await derive_elevation.derive(conn, previous=None)

    report = await MaterialCoverageService(MaterialCoverageQuery(road_graph_session)).get_material_coverage()
    by_id = {e.material_id: e for e in report.materials}

    assert (report.way_total, report.edge_total) == (3, 3)
    assert [(by_id[m].total, by_id[m].missing) for m in ("surface", "gradient_percent")] == [(3, 2), (3, 2)]
