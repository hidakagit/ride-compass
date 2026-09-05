"""MaterialSpec.extractorの単体テスト（改善計画T280）。

抽出フェーズをdomain/evaluation.pyの手書きループからMATERIAL_CATALOG駆動へ移した
ことに伴い、各材料のextractorが期待どおりの生値（欠損はNone）を返すことをここで
直接検証する。特にbridge/smoothness/surfaceはこの改修で新たに抽出可能になった材料
（以前はMATERIAL_CATALOGへ登録済みでもevaluation.pyのループに専用コードが無く、
実際には一切抽出されていなかった）で、evaluation.py側の変更なしに使えるようになった
ことの証跡でもある。
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


def test_lit_default_differs_between_missing_way_tags_and_missing_tag():
    """litの非対称な既定値（改善計画T280の元実装から移設、回帰の要）:
    way_tags自体が無ければ配列既定値のFalse（安全側=不明時は「街灯あり」扱いにしない
    誤りを避ける）、way_tagsはあるがlitタグが無ければFalse（街灯なし扱い）。"""
    spec = MATERIAL_CATALOG["lit"]
    assert spec.extractor(_ctx(way_tags=None)) is None  # 配列側でFalseへ解決される
    assert spec.extractor(_ctx(way_tags={})) is False
    assert spec.extractor(_ctx(way_tags={"lit": "yes"})) is True


def test_highway_requires_way_tags_present():
    # car_stress軸グループ全体をway_tags欠損時に評価しない既存仕様（way_tagsが空dictでも
    # 「取得できた」扱いなのでway_tags=Noneとは区別する）。
    highway_spec = MATERIAL_CATALOG["highway"]
    assert highway_spec.extractor(_ctx(way_tags={}, edge=_edge(highway="trunk"))) == "trunk"
    assert highway_spec.extractor(_ctx(way_tags=None, edge=_edge(highway="trunk"))) is None


def test_bicycle_infra_material_removed():
    """改善計画T347回帰テスト: bicycle_infra（優先順位付き分類、classify_bicycle_infrastructure
    経由）は「Python側に生データ加工ロジックを持たせない」設計原則に反するとして削除した。
    正規化フラグ材料4件（下記test_bicycle_infra_flag_materials_extract_from_cycleway_and_
    highway_tags参照）だけを正準とする。誤って復活しないことを固定するテスト。"""
    assert "bicycle_infra" not in MATERIAL_CATALOG


def test_bridge_smoothness_surface_are_now_extractable():
    """改善計画T280で新たに抽出可能になった材料（以前はMATERIAL_CATALOG登録済みでも
    evaluation.pyのループに専用コードが無く未抽出だった）。cycleway_classは改善計画T337で
    削除済み（どの評価軸・地図表示からも参照されない未使用材料だったため）。"""
    bridge = MATERIAL_CATALOG["bridge"]
    assert bridge.extractor(_ctx(way_tags={"bridge": "yes"})) is True
    assert bridge.extractor(_ctx(way_tags={})) is False
    assert bridge.extractor(_ctx(way_tags=None)) is None

    smoothness = MATERIAL_CATALOG["smoothness"]
    assert smoothness.extractor(_ctx(way_tags={"smoothness": " Good "})) == "good"
    assert smoothness.extractor(_ctx(way_tags={})) is None

    surface = MATERIAL_CATALOG["surface"]
    assert surface.extractor(_ctx(surface_attributes={"e1": "gravel"})) == "gravel"
    assert surface.extractor(_ctx()) is None


def test_cycleway_class_material_removed():
    """改善計画T337回帰テスト: cycleway_classは軸定義・地図表示のどちらからも参照が
    無い未使用材料だったため削除した。誤って復活しないことを固定するテスト。"""
    assert "cycleway_class" not in MATERIAL_CATALOG


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


def test_shared_pedestrian_path_material_extracts_from_footway_and_path_with_bicycle_tag():
    """改善計画T359: 河川敷サイクリングロード等「highway=footway/pathかつ
    bicycle=yes/designated」の区間を検知する材料（王子-荒川ルート検索の調査で発覚した、
    highway=cycleway系材料では拾えないタグパターンへの対応）。"""
    shared_pedestrian_path = MATERIAL_CATALOG["shared_pedestrian_path"]
    assert shared_pedestrian_path.extractor(
        _ctx(way_tags={"bicycle": "designated"}, edge=_edge(highway="footway"))
    ) is True
    assert shared_pedestrian_path.extractor(
        _ctx(way_tags={"bicycle": "yes"}, edge=_edge(highway="path"))
    ) is True
    # bicycleタグが無い普通の歩道・自転車通行不可の歩道は該当しない。
    assert shared_pedestrian_path.extractor(_ctx(way_tags={}, edge=_edge(highway="footway"))) is False
    assert (
        shared_pedestrian_path.extractor(_ctx(way_tags={"bicycle": "no"}, edge=_edge(highway="footway"))) is False
    )
    # highway=footway/path以外（residential等）は該当しない。
    assert (
        shared_pedestrian_path.extractor(
            _ctx(way_tags={"bicycle": "designated"}, edge=_edge(highway="residential"))
        )
        is False
    )
    assert shared_pedestrian_path.extractor(_ctx(way_tags=None)) is None


def test_oneway_and_designation_remain_unwired_by_design():
    """extractor未設定=意図的なDEFER（material_catalog.pyのコメント参照）。誤って
    extractorが付いた場合にこのテストが落ちるのではなく、逆に外れたことに気付けるよう
    現状を固定するテスト（着手時はこのテストごと更新する）。"""
    assert MATERIAL_CATALOG["oneway"].extractor is None
    assert MATERIAL_CATALOG["designation"].extractor is None


def test_is_emergency_transport_and_is_critical_logistics_are_unwired_by_design():
    """改善計画T338フォローアップ（2026-08-26）: designationを正規化フラグ材料
    （is_emergency_transport/is_critical_logistics）へ分解したが、is_designatedと違い
    どの内蔵軸からも参照されないため、種別ごとのper-edge kindを評価パイプラインへ運ぶ
    配線はトリガー付きDEFERのまま（designation/onewayと同じ既存パターン）。誤って
    extractorが付いた場合にこのテストが落ちるのではなく、逆に外れたことに気付けるよう
    現状を固定する。軸スタジオの選択肢からは除外しない（display_only=False、designationとは
    異なる）。"""
    assert MATERIAL_CATALOG["is_emergency_transport"].extractor is None
    assert MATERIAL_CATALOG["is_emergency_transport"].display_only is False
    assert MATERIAL_CATALOG["is_critical_logistics"].extractor is None
    assert MATERIAL_CATALOG["is_critical_logistics"].display_only is False


# --- 改善計画T339: 汎用extractorファクトリの単体テスト。既存の簡易extractorをこれらの
# ファクトリへ置き換えた際の振る舞い不変性は、上記の各材料テスト・
# test_all_cataloged_extractors_run_without_error_on_minimal_and_missing_contextが
# 既に間接的に担保している。ここではファクトリ自体を材料から独立して検証する。


def test_raw_way_tag_extractor_normalizes_and_handles_missing():
    from app.domain.material_catalog import raw_way_tag_extractor

    extractor = raw_way_tag_extractor("smoothness", normalize=True)
    assert extractor(_ctx(way_tags={"smoothness": " Good "})) == "good"
    assert extractor(_ctx(way_tags={})) is None
    assert extractor(_ctx(way_tags=None)) is None

    raw_extractor = raw_way_tag_extractor("smoothness")
    assert raw_extractor(_ctx(way_tags={"smoothness": " Good "})) == " Good "


def test_tag_equals_extractor_matches_and_negates():
    from app.domain.material_catalog import tag_equals_extractor

    bridge = tag_equals_extractor("bridge", "yes")
    assert bridge(_ctx(way_tags={"bridge": "yes"})) is True
    assert bridge(_ctx(way_tags={})) is False
    assert bridge(_ctx(way_tags=None)) is None

    negated = tag_equals_extractor("lit", "yes", negate=True)
    assert negated(_ctx(way_tags={"lit": "yes"})) is False
    assert negated(_ctx(way_tags={})) is True
    assert negated(_ctx(way_tags=None)) is None


def test_way_tag_parser_extractor_delegates_to_parser_and_handles_missing_way_tags():
    from app.domain.material_catalog import way_tag_parser_extractor
    from app.domain.recipe import parse_maxspeed

    extractor = way_tag_parser_extractor(parse_maxspeed)
    assert extractor(_ctx(way_tags={"maxspeed": "40"})) == 40
    assert extractor(_ctx(way_tags={})) is None
    assert extractor(_ctx(way_tags=None)) is None


def test_count_per_km_extractor_selects_correct_counts_dict():
    from app.domain.material_catalog import count_per_km_extractor

    extractor = count_per_km_extractor(lambda ctx: ctx.stop_counts)
    assert extractor(_ctx(stop_counts={"e1": 4}, edge=_edge())) == 40.0  # 4件/0.1km
    assert extractor(_ctx()) is None


def test_tracktype_material_is_extractable_without_a_dedicated_function():
    """改善計画T339完了条件の実証: tracktypeはmaterial_catalog.pyに専用のPython関数
    （`def _extract_tracktype`のようなもの）を持たず、汎用ファクトリ
    （raw_way_tag_extractor）への宣言だけでMATERIAL_CATALOGへ登録・抽出可能になっている。
    """
    tracktype = MATERIAL_CATALOG["tracktype"]
    assert tracktype.extractor(_ctx(way_tags={"tracktype": "Grade2"})) == "grade2"
    assert tracktype.extractor(_ctx(way_tags={})) is None
    assert tracktype.extractor(_ctx(way_tags=None)) is None


def test_all_materials_have_a_non_empty_description():
    # 改善計画T345: 軸スタジオの情報アイコンが表示する説明文。display_only材料
    # （designation、軸スタジオの選択肢からは除外される）も含め、MATERIAL_CATALOG
    # 登録済みの全材料が空でない説明文を持つことを確認する（新規材料追加時に
    # description記入漏れを検知する）。
    for spec in MATERIAL_CATALOG.values():
        assert spec.description.strip() != "", f"{spec.material_id} has no description"


def test_highway_surface_smoothness_have_distinct_value_labels():
    # 改善計画T345フォローアップ: 地図の絞り込みUIのグルーピング（多対一）とは独立した
    # 1値1ラベルの対訳表を持つことを確認する（同じラベルが複数のタグ値に付いていると、
    # 軸スタジオの候補セレクトで見分けが付かなくなる実害が過去に発生したため）。
    for material_id in ("highway", "surface", "smoothness"):
        value_labels = MATERIAL_CATALOG[material_id].value_labels
        assert len(value_labels) > 0, f"{material_id} has no value_labels"
        assert len(set(value_labels.values())) == len(value_labels), f"{material_id} has duplicate labels"


def test_value_label_falls_back_to_the_raw_value_for_unknown_values():
    # 改善計画T345さらなるフォローアップ2: 「論理名 - 物理名」形式で返す
    # （例: "住宅街の道路 - residential"）。
    highway = MATERIAL_CATALOG["highway"]
    assert highway.value_label("residential") == "住宅街の道路 - residential"
    # 対訳表に無い値（論理名が無い）は物理名のみ、" - "は付かない。
    assert highway.value_label("some_new_osm_value") == "some_new_osm_value"

    # value_labelsを持たない材料（例: gradient_percent）は常にvalueそのまま。
    gradient = MATERIAL_CATALOG["gradient_percent"]
    assert gradient.value_labels == {}
    assert gradient.value_label("anything") == "anything"


def test_full_label_combines_label_and_material_id():
    # 改善計画T345さらなるフォローアップ2: 材料名も値と同じ「論理名 - 物理名」形式
    # （例: "道路種別 - highway"）で軸スタジオへ返す（full_labelはGET /api/material-catalogの
    # labelフィールドが使う）。
    highway = MATERIAL_CATALOG["highway"]
    assert highway.full_label() == "道路種別 - highway"
