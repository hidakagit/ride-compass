"""材料の欠損割合集計（infrastructure/material_coverage.py・services/material_coverage_service.py）の
DB非依存テスト。実DBでの集計はtest_material_coverage_repository.py（postgis）が担う。"""

from datetime import datetime, timezone

import pytest

from app.domain.material_catalog import MATERIAL_CATALOG
from app.infrastructure.material_coverage import (
    MATERIAL_COVERAGE_EXCLUSIONS,
    MATERIAL_COVERAGE_SPECS,
    EdgeMaterialCoverageSpec,
    MaterialCoverageCounts,
    WayMaterialCoverageSpec,
    build_way_coverage_sql,
)
from app.infrastructure.osm_way_tag_sql import (
    BRIDGE_NORMALIZED_SQL,
    LANES_COUNT_CASE_SQL,
    LIT_NORMALIZED_SQL,
    MAXSPEED_KMH_CASE_SQL,
    MOTOR_VEHICLE_NORMALIZED_SQL,
    SMOOTHNESS_NORMALIZED_SQL,
    SURFACE_GOOD_CASE_SQL,
    SURFACE_NORMALIZED_SQL,
    TUNNEL_NORMALIZED_SQL,
)
from app.infrastructure.road_graph_repository import _ROAD_SURFACE_TILE_MVT_SQL
from app.services import material_coverage_service
from app.services.material_coverage_service import MaterialCoverageService, build_material_coverage_report

COMPUTED_AT = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _counts(way_total: int = 10, edge_total: int = 4, **missing_overrides: int) -> MaterialCoverageCounts:
    missing = {material_id: 0 for material_id in MATERIAL_COVERAGE_SPECS}
    missing.update(missing_overrides)
    return MaterialCoverageCounts(way_total=way_total, edge_total=edge_total, missing_by_material=missing)


# --- 宣言テーブルの網羅性 ---


def test_every_catalog_material_is_either_covered_or_explicitly_excluded():
    covered = set(MATERIAL_COVERAGE_SPECS)
    excluded = set(MATERIAL_COVERAGE_EXCLUSIONS)

    assert covered | excluded == set(MATERIAL_CATALOG)
    assert covered & excluded == set()


def test_exclusion_reasons_are_non_empty():
    for material_id, reason in MATERIAL_COVERAGE_EXCLUSIONS.items():
        assert reason.strip() != "", material_id


def test_specs_carry_source_description_and_population():
    for material_id, spec in MATERIAL_COVERAGE_SPECS.items():
        assert spec.source.strip() != "", material_id
        if isinstance(spec, WayMaterialCoverageSpec):
            assert spec.population == "way"
            assert spec.missing_condition.strip() != ""
        else:
            assert isinstance(spec, EdgeMaterialCoverageSpec)
            assert spec.population == "edge"
            assert spec.present_count_sql.lstrip().upper().startswith("SELECT COUNT(*)")


# --- way母集団の判定式は infrastructure/osm_way_tag_sql.py の共有SQL断片を
# _ROAD_SURFACE_TILE_MVT_SQLと文字どおり同じ定数から組み立てる（同じPython定数を
# 使う以上ドリフトしようがないため、両クエリの文字列を突き合わせる契約テストは不要）。


@pytest.mark.parametrize(
    ("material_id", "fragment"),
    [
        ("surface", SURFACE_NORMALIZED_SQL),
        ("surface_good", SURFACE_GOOD_CASE_SQL),
        ("smoothness", SMOOTHNESS_NORMALIZED_SQL),
        ("maxspeed_kmh", MAXSPEED_KMH_CASE_SQL),
        ("lanes_count", LANES_COUNT_CASE_SQL),
        ("lit", LIT_NORMALIZED_SQL),
        ("has_tunnel", TUNNEL_NORMALIZED_SQL),
        ("bridge", BRIDGE_NORMALIZED_SQL),
        ("motor_vehicle_no", MOTOR_VEHICLE_NORMALIZED_SQL),
    ],
)
def test_way_missing_condition_uses_shared_fragment_also_used_by_mvt_sql(material_id: str, fragment: str):
    """`MATERIAL_COVERAGE_SPECS`の判定式と`_ROAD_SURFACE_TILE_MVT_SQL`が、同じ
    `osm_way_tag_sql.py`の定数を実際に使っていることを確認する（両クエリが同じ
    Python文字列を参照する構成そのものが一致を保証するため、独立した2つの文字列を
    突き合わせる旧方式より確実）。"""
    spec = MATERIAL_COVERAGE_SPECS[material_id]
    assert isinstance(spec, WayMaterialCoverageSpec)

    assert fragment in spec.missing_condition
    assert fragment in _ROAD_SURFACE_TILE_MVT_SQL.text


def test_build_way_coverage_sql_has_one_filter_column_per_way_material_and_binds_surface_tags():
    statement = build_way_coverage_sql()
    sql = statement.text

    way_material_ids = [m for m, s in MATERIAL_COVERAGE_SPECS.items() if isinstance(s, WayMaterialCoverageSpec)]
    assert sql.startswith("SELECT count(*) AS total")
    assert sql.rstrip().endswith("FROM osm_raw_ways AS w")
    for material_id in way_material_ids:
        assert f" AS {material_id}" in sql
    assert sql.count("count(*) FILTER") == len(way_material_ids)
    compiled_params = statement.compile().params
    assert "asphalt" in compiled_params["good_tags"]
    assert "gravel" in compiled_params["bad_tags"]


def test_build_way_coverage_sql_without_surface_good_does_not_bind_tags():
    statement = build_way_coverage_sql({"highway": MATERIAL_COVERAGE_SPECS["highway"]})

    assert ":good_tags" not in statement.text
    assert statement.compile().params == {}


# --- レポート組み立て（純関数） ---


def test_build_report_lists_all_catalog_materials_in_catalog_order():
    report = build_material_coverage_report(_counts(), COMPUTED_AT)

    assert [e.material_id for e in report.materials] == list(MATERIAL_CATALOG)
    assert report.computed_at == COMPUTED_AT
    assert report.way_total == 10
    assert report.edge_total == 4


def test_build_report_computes_ratio_against_population_total():
    report = build_material_coverage_report(_counts(way_total=10, edge_total=4, surface=8, gradient_percent=3), COMPUTED_AT)
    by_id = {e.material_id: e for e in report.materials}

    surface = by_id["surface"]
    assert surface.population == "way"
    assert (surface.total, surface.missing) == (10, 8)
    assert surface.missing_ratio == pytest.approx(0.8)
    assert surface.label == MATERIAL_CATALOG["surface"].full_label()
    assert surface.dtype == "categorical"
    assert surface.missing_semantics == "unknown"
    assert surface.excluded_reason is None

    gradient = by_id["gradient_percent"]
    assert gradient.population == "edge"
    assert (gradient.total, gradient.missing) == (4, 3)
    assert gradient.missing_ratio == pytest.approx(0.75)


def test_build_report_marks_excluded_materials_with_reason():
    report = build_material_coverage_report(_counts(), COMPUTED_AT)
    by_id = {e.material_id: e for e in report.materials}

    wind = by_id["wind_drag_ratio"]
    assert wind.population is None
    assert wind.total is None and wind.missing is None and wind.missing_ratio is None
    assert wind.missing_semantics is None
    assert wind.excluded_reason == MATERIAL_COVERAGE_EXCLUSIONS["wind_drag_ratio"]


def test_build_report_returns_none_ratio_when_population_is_empty():
    report = build_material_coverage_report(_counts(way_total=0, edge_total=0), COMPUTED_AT)

    for entry in report.materials:
        if entry.excluded_reason is None:
            assert entry.total == 0
            assert entry.missing_ratio is None


def test_build_report_fails_fast_when_material_is_registered_nowhere(monkeypatch):
    monkeypatch.setattr(material_coverage_service, "MATERIAL_COVERAGE_EXCLUSIONS", {})

    with pytest.raises(ValueError, match="wind_drag_ratio"):
        build_material_coverage_report(_counts(), COMPUTED_AT)


# --- サービス ---


class FakeCoverageQuery:
    def __init__(self, counts: MaterialCoverageCounts):
        self._counts = counts
        self.calls = 0

    async def get_material_coverage_counts(self) -> MaterialCoverageCounts:
        self.calls += 1
        return self._counts


async def test_service_builds_report_from_repository_counts():
    query = FakeCoverageQuery(_counts(way_total=100, edge_total=50, surface=85))
    service = MaterialCoverageService(query)  # type: ignore[arg-type]

    report = await service.get_material_coverage()

    assert query.calls == 1
    assert report.way_total == 100
    assert report.edge_total == 50
    surface = next(e for e in report.materials if e.material_id == "surface")
    assert surface.missing_ratio == pytest.approx(0.85)
    assert report.computed_at.tzinfo is not None
