"""MaterialSpec.extractorの単体テスト（改善計画T280）。

抽出フェーズをdomain/evaluation.pyの手書きループからMATERIAL_CATALOG駆動へ移した
ことに伴い、各材料のextractorが期待どおりの生値（欠損はNone）を返すことをここで
直接検証する。特にbridge/smoothness/cycleway_class/surfaceはこの改修で新たに
抽出可能になった材料（以前はMATERIAL_CATALOGへ登録済みでもevaluation.pyの
ループに専用コードが無く、実際には一切抽出されていなかった）で、evaluation.py側の
変更なしに使えるようになったことの証跡でもある。
"""

from app.domain.attributes import ElevationAttribute
from app.domain.graph import DirectedEdge
from app.domain.material_catalog import MATERIAL_CATALOG, MaterialExtractionContext


def _edge(highway: str | None = "residential") -> DirectedEdge:
    return DirectedEdge(
        edge_id="e1",
        from_node_id="n1",
        to_node_id="n2",
        geometry=[[35.0, 139.0], [35.0, 139.001]],
        distance_m=100.0,
        highway=highway,
    )


def _ctx(
    way_tags: dict[str, str] | None = None,
    edge: DirectedEdge | None = None,
    elevation_attributes: dict[str, ElevationAttribute] | None = None,
    surface_attributes: dict[str, str | None] | None = None,
    stop_counts: dict[str, int] | None = None,
    intersection_counts: dict[str, int] | None = None,
    accident_counts: dict[str, int] | None = None,
    accident_years_covered: int = 1,
    designated_edge_ids: set[str] | None = None,
) -> MaterialExtractionContext:
    e = edge or _edge()
    return MaterialExtractionContext(
        edge=e,
        edge_id=e.edge_id,
        way_tags=way_tags,
        distance_km=e.distance_m / 1000,
        elevation_attributes=elevation_attributes or {},
        surface_attributes=surface_attributes or {},
        stop_counts=stop_counts or {},
        intersection_counts=intersection_counts or {},
        accident_counts=accident_counts or {},
        accident_years_covered=accident_years_covered,
        designated_edge_ids=designated_edge_ids or set(),
    )


def test_all_cataloged_extractors_run_without_error_on_minimal_and_missing_context():
    """MATERIAL_CATALOG全件のextractorが、way_tagsあり/なしの両方で例外なく呼べる
    （新規材料追加時にありがちな未処理のNoneアクセスを回帰的に検知する）。"""
    for spec in MATERIAL_CATALOG.values():
        if spec.extractor is None:
            continue
        spec.extractor(_ctx(way_tags={}))
        spec.extractor(_ctx(way_tags=None))


def test_gradient_percent_extracts_average_grade_and_missing_is_none():
    spec = MATERIAL_CATALOG["gradient_percent"]
    attr = ElevationAttribute(
        edge_id="e1", average_grade=4.5, data_source="test", calculated_at="2026-01-01T00:00:00Z"
    )
    ctx = _ctx(elevation_attributes={"e1": attr})
    assert spec.extractor(ctx) == 4.5
    assert spec.extractor(_ctx()) is None


def test_surface_good_missing_tag_is_none_not_false():
    # bool_default="nan"の唯一の例外材料。「不明」を「悪路」と混同してはいけない。
    spec = MATERIAL_CATALOG["surface_good"]
    assert spec.bool_default == "nan"
    assert spec.extractor(_ctx(surface_attributes={"e1": "asphalt"})) is True
    assert spec.extractor(_ctx(surface_attributes={"e1": "unknown_tag"})) is None
    assert spec.extractor(_ctx()) is None


def test_stop_count_per_km_divides_by_distance():
    spec = MATERIAL_CATALOG["stop_count_per_km"]
    ctx = _ctx(edge=_edge(), stop_counts={"e1": 2})
    assert spec.extractor(ctx) == 2 / (100.0 / 1000)


def test_accident_count_per_km_year_needs_years_covered():
    spec = MATERIAL_CATALOG["accident_count_per_km_year"]
    ctx = _ctx(accident_counts={"e1": 4}, accident_years_covered=2)
    assert spec.extractor(ctx) == (4 / 0.1) / 2
    assert spec.extractor(_ctx(accident_counts={"e1": 4}, accident_years_covered=0)) is None


def test_no_lit_default_differs_between_missing_way_tags_and_missing_tag():
    """no_litの非対称な既定値（改善計画T280の元実装から移設、回帰の要）:
    way_tags自体が無ければ配列既定値のFalse（安全側=不明時は「街灯あり」扱いにしない
    誤りを避ける）、way_tagsはあるがlitタグが無ければTrue（安全側=街灯なし扱い）。"""
    spec = MATERIAL_CATALOG["no_lit"]
    assert spec.extractor(_ctx(way_tags=None)) is None  # 配列側でFalseへ解決される
    assert spec.extractor(_ctx(way_tags={})) is True
    assert spec.extractor(_ctx(way_tags={"lit": "yes"})) is False


def test_highway_and_bicycle_infra_require_way_tags_present():
    # car_stress軸グループ全体をway_tags欠損時に評価しない既存仕様（way_tagsが空dictでも
    # 「取得できた」扱いなのでway_tags=Noneとは区別する）。
    highway_spec = MATERIAL_CATALOG["highway"]
    assert highway_spec.extractor(_ctx(way_tags={}, edge=_edge(highway="trunk"))) == "trunk"
    assert highway_spec.extractor(_ctx(way_tags=None, edge=_edge(highway="trunk"))) is None


def test_bridge_smoothness_cycleway_class_surface_are_now_extractable():
    """改善計画T280で新たに抽出可能になった4材料（以前はMATERIAL_CATALOG登録済みでも
    evaluation.pyのループに専用コードが無く未抽出だった）。"""
    bridge = MATERIAL_CATALOG["bridge"]
    assert bridge.extractor(_ctx(way_tags={"bridge": "yes"})) is True
    assert bridge.extractor(_ctx(way_tags={})) is False
    assert bridge.extractor(_ctx(way_tags=None)) is None

    smoothness = MATERIAL_CATALOG["smoothness"]
    assert smoothness.extractor(_ctx(way_tags={"smoothness": " Good "})) == "good"
    assert smoothness.extractor(_ctx(way_tags={})) is None

    cycleway_class = MATERIAL_CATALOG["cycleway_class"]
    assert cycleway_class.extractor(_ctx(way_tags={"cycleway": "track"})) == "track"
    assert cycleway_class.extractor(_ctx(way_tags={})) is None

    surface = MATERIAL_CATALOG["surface"]
    assert surface.extractor(_ctx(surface_attributes={"e1": "gravel"})) == "gravel"
    assert surface.extractor(_ctx()) is None


def test_bicycle_infra_flag_materials_extract_from_cycleway_and_highway_tags():
    """改善計画T336で追加した正規化フラグ材料4件（highway_is_cycleway/cycleway_has_track/
    cycleway_has_lane/cycleway_has_shared）のextractor。way_tags欠損時はNone
    （car_stress軸グループ全体を評価しない既存仕様、他のway_tags依存材料と同じ）。"""
    highway_is_cycleway = MATERIAL_CATALOG["highway_is_cycleway"]
    assert highway_is_cycleway.extractor(_ctx(way_tags={}, edge=_edge(highway="cycleway"))) is True
    assert highway_is_cycleway.extractor(_ctx(way_tags={}, edge=_edge(highway="residential"))) is False
    assert highway_is_cycleway.extractor(_ctx(way_tags=None)) is None

    cycleway_has_track = MATERIAL_CATALOG["cycleway_has_track"]
    assert cycleway_has_track.extractor(_ctx(way_tags={"cycleway": "track"})) is True
    assert cycleway_has_track.extractor(_ctx(way_tags={"cycleway:left": "track"})) is True
    assert cycleway_has_track.extractor(_ctx(way_tags={"cycleway": "lane"})) is False
    assert cycleway_has_track.extractor(_ctx(way_tags=None)) is None

    cycleway_has_lane = MATERIAL_CATALOG["cycleway_has_lane"]
    assert cycleway_has_lane.extractor(_ctx(way_tags={"cycleway": "lane"})) is True
    assert cycleway_has_lane.extractor(_ctx(way_tags={"cycleway": "track"})) is False
    assert cycleway_has_lane.extractor(_ctx(way_tags=None)) is None

    cycleway_has_shared = MATERIAL_CATALOG["cycleway_has_shared"]
    assert cycleway_has_shared.extractor(_ctx(way_tags={"cycleway": "share_busway"})) is True
    assert cycleway_has_shared.extractor(_ctx(way_tags={"cycleway:both": "shared_lane"})) is True
    assert cycleway_has_shared.extractor(_ctx(way_tags={"cycleway": "lane"})) is False
    assert cycleway_has_shared.extractor(_ctx(way_tags=None)) is None


def test_oneway_and_designation_remain_unwired_by_design():
    """extractor未設定=意図的なDEFER（material_catalog.pyのコメント参照）。誤って
    extractorが付いた場合にこのテストが落ちるのではなく、逆に外れたことに気付けるよう
    現状を固定するテスト（着手時はこのテストごと更新する）。"""
    assert MATERIAL_CATALOG["oneway"].extractor is None
    assert MATERIAL_CATALOG["designation"].extractor is None
