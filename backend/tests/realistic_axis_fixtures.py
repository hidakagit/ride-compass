"""統合寄りのテスト向け、本番相当の13軸データ（改善計画T350、T353で14→13軸）。

`domain/axis_definitions.py: AXIS_DEFINITIONS`のPython literalをT350で撤去し、DBが
唯一の正本になったため、プロセス起動直後は空のままで、`services/axis_registry_service.py:
refresh_axis_definitions`がDBから読み込むまで埋まらない。road_graph_engine・
openrouteservice_engine・evaluation_service・route_generator等、ルート生成の実処理を
テストするファイルの多くは、DBを介さず`RoutePreference()`や`compute_edge_cost`等を直接
呼ぶため、グローバルな`AXIS_DEFINITIONS`に「car_stress/night/gradient/wind等の実在の
axis_idを持つ、一貫した軸システム」が入っていることを暗黙に前提にしている
（`road_graph_engine.py`等が"car_stress"をハードコード参照するため、単なるダミー軸では
代替できない）。

**改善計画T352の完了確認（2026-08-28）**: 以前はnight・windの重み掛け替えロジックも
axis_idの直接ハードコードで、この「フルセット必須」の一因だった。T352で`time_scope`・
`supports_route_coloring`という性質ベースの宣言的フィールドへ汎用化した結果、
night・windは（car_stressと異なり）**もはや実在を前提としない**——存在しない場合は
単に「この性質を持つ軸が無い」として何も掛け替えず動作する（KeyError等では落ちない、
`test_evaluation.py: test_with_time_scope_*`・`test_axis_registry_service.py:
test_delete_allows_axis_id_after_t352_generalization`で裏付け済み）。それでも本
autouseフィクスチャ自体は撤去・縮小していない——car_stressのハードコード
（T352の対象外、`services/axis_registry_service.py: _CODE_COUPLED_AXIS_IDS`参照）が
残る以上、多くの既存テストが暗黙に「一貫した軸システム」を前提にし続けており、
個々のテストを1軸ずつに絞り込む監査は本タスクのスコープ外と判断した
（改善計画T352完了メモ参照）。

本モジュールは、撤去前のPython literalと同じ構造（axis_id・shape・材料参照・階層）を
テストコード側に複製した「テスト専用の固定フィクスチャ」。DBの現在値を検証する目的では
なく、あくまで「一貫した軸システムを必要とする他のロジックのテスト」を成立させるための
土台であり、個々のテストがこのモジュールの値を直接アサートすることは想定しない
（値そのものを検証したいテストは、testファイル内でさらに局所的な合成軸を定義すること。
`tests/test_difficulty.py`・`tests/test_axis_display.py`・`tests/test_evaluation_bulk.py`
参照）。DBの実データとは完全に独立しており、DB側の値が変わってもこのフィクスチャは
追従不要（追従すべきなのはDBの構造検証を行う`tests/test_migrate.py`のみ）。
"""

from contextlib import contextmanager

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    FlagSumShape,
    MaterialTerm,
)
from app.domain.registry import AxisDisplaySpec, TileInputSpec

_CAR_STRESS_HIGHWAY_BASE_MAPPING: dict[str, float] = {
    "cycleway": 1.0,
    "living_street": 1.0,
    "footway": 1.0,
    "path": 1.0,
    "residential": 2.0,
    "unclassified": 2.0,
    "track": 2.0,
    "tertiary": 3.0,
    "tertiary_link": 3.0,
    "secondary": 3.0,
    "secondary_link": 3.0,
    "primary": 4.0,
    "primary_link": 4.0,
    "trunk": 4.0,
    "trunk_link": 4.0,
}
_CAR_STRESS_BICYCLE_INFRA_FLAG_WEIGHTS: list[tuple[str, float]] = [
    ("highway_is_cycleway", -4.0),
    ("cycleway_has_track", -4.0),
    ("cycleway_has_lane", -2.0),
    ("cycleway_has_shared", -1.0),
    ("shared_pedestrian_path", -4.0),
]
_BICYCLE_INFRA_AXIS_BREAKPOINTS: list[tuple[float, float]] = [
    (-4.0, 0.0),
    (-2.0, 33.3),
    (-1.0, 66.7),
    (0.0, 100.0),
]
_CAR_STRESS_MAXSPEED_BREAKPOINTS: list[tuple[float, float]] = [
    (0.0, -1.0),
    (30.0, -1.0),
    (31.0, 0.0),
    (59.0, 0.0),
    (60.0, 1.0),
    (999.0, 1.0),
]
_CAR_STRESS_LANES_BREAKPOINTS: list[tuple[float, float]] = [
    (0.0, -1.0),
    (1.0, -1.0),
    (2.0, 0.0),
    (3.0, 0.0),
    (4.0, 1.0),
    (99.0, 1.0),
]
_CAR_STRESS_MOTOR_VEHICLE_NO_MAPPING: dict[bool, float] = {True: -1000.0, False: 0.0}
_UNSIGNALED_INTERSECTION_WEIGHT = 0.3

REALISTIC_AXIS_DEFINITIONS: dict[str, AxisDefinition] = {
    "gradient": AxisDefinition(
        axis_id="gradient",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (3.0, 25.0), (6.0, 50.0), (9.0, 75.0), (15.0, 100.0)],
        ),
        default_weight=0.15,
        label="勾配",
        description="登り坂の急さが小さいほど易しい",
        category="観測",
        is_published=True,
        icon_id="incline",
        chip_label="勾配",
    ),
    "wind": AxisDefinition(
        axis_id="wind",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="wind_penalty")],
            breakpoints=[(0.0, 0.0), (8.0, 100.0)],
        ),
        default_weight=0.26,
        label="風",
        description="向かい風が弱いほど易しい",
        category="動的",
        is_published=True,
        supports_route_coloring=True,
    ),
    "surface_q": AxisDefinition(
        axis_id="surface_q",
        shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
        default_weight=0.19,
        label="舗装質",
        description="舗装路であるほど易しい",
        category="観測",
        is_published=True,
        icon_id="wave",
        chip_label="舗装",
    ),
    "stop_density": AxisDefinition(
        axis_id="stop_density",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="stop_count_per_km"),
                MaterialTerm(
                    material="intersection_count_per_km",
                    weight=_UNSIGNALED_INTERSECTION_WEIGHT,
                    required=False,
                ),
            ],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.20,
        label="停止密度",
        description="信号・横断歩道・一時停止・踏切・交差点(次数3以上の分岐点、低い重み)が少ないほど易しい",
        category="観測",
        is_published=True,
        icon_id="density-stack",
        chip_label="停止密度",
        panel_hint="信号・横断歩道・一時停止・踏切等の停止要因が、沿線でどれだけ密集しているかの目安です。"
        "実際の位置は「停止要因」レイヤーで確認できます。",
        display_override=AxisDisplaySpec(
            kind="ramp",
            label="停止密度",
            category="trafficSafety",
            tile_inputs=[
                TileInputSpec(property="stop_per_km", weight=1.0),
                TileInputSpec(property="intersection_per_km", weight=_UNSIGNALED_INTERSECTION_WEIGHT),
            ],
            thresholds=[1.0, 2.0, 4.0],
            unit="回/km",
            note="信号・横断歩道・一時停止・踏切に無タグ交差点（重み0.3）を加えた"
            "停止要因の密度。way単位の事前集計（way_attribute_counts）由来",
        ),
    ),
    "car_stress_highway_base": AxisDefinition(
        axis_id="car_stress_highway_base",
        shape=CategoricalShape(material="highway", mapping=_CAR_STRESS_HIGHWAY_BASE_MAPPING),
        default_weight=0.0,
        label="車ストレス内部軸: highway基準値",
        description="highway種別による車の圧迫感の基準値(1-4、非公開)",
        category="推定",
        is_published=False,
    ),
    "car_stress_maxspeed_adjustment": AxisDefinition(
        axis_id="car_stress_maxspeed_adjustment",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="maxspeed_kmh")],
            breakpoints=_CAR_STRESS_MAXSPEED_BREAKPOINTS,
        ),
        default_weight=0.0,
        label="車ストレス内部軸: 制限速度補正",
        description="制限速度による補正(非公開)",
        category="推定",
        is_published=False,
    ),
    "car_stress_lanes_adjustment": AxisDefinition(
        axis_id="car_stress_lanes_adjustment",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="lanes_count")],
            breakpoints=_CAR_STRESS_LANES_BREAKPOINTS,
        ),
        default_weight=0.0,
        label="車ストレス内部軸: 車線数補正",
        description="車線数による補正(非公開)",
        category="推定",
        is_published=False,
    ),
    "car_stress_designation_adjustment": AxisDefinition(
        axis_id="car_stress_designation_adjustment",
        shape=CategoricalShape(material="is_designated", mapping={True: 1.0, False: 0.0}),
        default_weight=0.0,
        label="車ストレス内部軸: 指定路線補正",
        description="指定路線(緊急輸送道路・重要物流道路)該当による補正(非公開)",
        category="推定",
        is_published=False,
    ),
    "car_stress_motor_vehicle_no_adjustment": AxisDefinition(
        axis_id="car_stress_motor_vehicle_no_adjustment",
        shape=CategoricalShape(material="motor_vehicle_no", mapping=_CAR_STRESS_MOTOR_VEHICLE_NO_MAPPING),
        default_weight=0.0,
        label="車ストレス内部軸: 自動車通行不可の優先確定",
        description="motor_vehicle=noの区間を最良値へ強制する内部軸(非公開)",
        category="推定",
        is_published=False,
    ),
    "car_stress": AxisDefinition(
        axis_id="car_stress",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="car_stress_highway_base", required=True),
                MaterialTerm(material="car_stress_maxspeed_adjustment", required=False),
                MaterialTerm(material="car_stress_lanes_adjustment", required=False),
                MaterialTerm(material="car_stress_designation_adjustment", required=False),
                MaterialTerm(material="car_stress_motor_vehicle_no_adjustment", required=False),
            ],
            breakpoints=[(0.0, 0.0), (4.0, 100.0)],
        ),
        default_weight=0.20,
        label="車の圧迫感",
        description="推定される車の圧迫感(1-5)が低いほど易しい。自動車との近さ・速さ・車線数の指標で、信号や交差点の頻度は含まない(別軸)。自転車インフラの有無は別軸(自転車インフラ)で評価します。",
        category="推定",
        is_published=True,
        icon_id="warning-triangle",
        chip_label="圧迫感",
        panel_hint="道路種別・制限速度・車線数・指定路線・自動車通行可否から推定した"
        "車の圧迫感の目安です。実際の交通量そのものは加味していません。内訳は区間をクリックして"
        "確認できます。",
        display_override=AxisDisplaySpec(
            kind="ramp",
            label="車の圧迫感",
            category="trafficSafety",
            tile_inputs=[
                TileInputSpec(
                    property="highway",
                    categories=_CAR_STRESS_HIGHWAY_BASE_MAPPING,
                    has_unknown_fallback=True,
                ),
                TileInputSpec(
                    property="maxspeed_kmh",
                    breakpoints=_CAR_STRESS_MAXSPEED_BREAKPOINTS,
                ),
                TileInputSpec(
                    property="lanes_count",
                    breakpoints=_CAR_STRESS_LANES_BREAKPOINTS,
                ),
                TileInputSpec(
                    property="designation",
                    categories={"emergency_transport": 1.0, "critical_logistics": 1.0, "both": 1.0},
                ),
                TileInputSpec(
                    property="motor_vehicle_no",
                    boolean=True,
                    true_value=_CAR_STRESS_MOTOR_VEHICLE_NO_MAPPING[True],
                    false_value=_CAR_STRESS_MOTOR_VEHICLE_NO_MAPPING[False],
                ),
            ],
            thresholds=[2.0, 3.0, 4.0],
            note="改善計画T292: highway/maxspeed_kmh/lanes_count/"
            "designation/motor_vehicle_noの5材料から自動計算する。以前は専用の"
            "手書きexpression（旧carStressExpression.ts）が必要だったが、内部軸への"
            "階層再構成でtile_inputsの重み付き結合として表現できるようになった"
            "（改善計画T347でbicycle_infraタイルプロパティ自体を削除したため6→5材料へ）",
        ),
    ),
    "accident": AxisDefinition(
        axis_id="accident",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="accident_count_per_km_year")],
            breakpoints=[(0.0, 0.0), (0.5, 100.0)],
        ),
        default_weight=0.08,
        label="事故密度",
        description="事故密度(件/(km・年)、警察庁統計)が低いほど易しい",
        category="推定",
        is_published=True,
        icon_id="density-scatter",
        chip_label="事故密度",
        panel_hint="警察庁の交通事故統計をもとに、自転車関連事故が沿線でどれだけ近くに集中しているかの"
        "目安です[死亡事故は重めに算入]。実際の発生地点は「事故」レイヤーで確認できます。",
        display_override=AxisDisplaySpec(
            kind="ramp",
            label="事故密度",
            category="trafficSafety",
            tile_inputs=[TileInputSpec(property="accident_per_km", weight=1.0)],
            thresholds=[0.4, 0.8, 1.5],
            unit="件/km",
            note="警察庁統計（収録全年分、死亡事故は重み付き）の自転車関連事故の"
            "距離正規化密度。way単位の事前集計（way_attribute_counts）由来。"
            "正確な事故地点は既存の事故レイヤー（accidents、生の点表示）で確認できる",
        ),
    ),
    "night": AxisDefinition(
        axis_id="night",
        shape=FlagSumShape(flags=[("no_lit", 50.0), ("has_tunnel", 50.0)], cap=100.0),
        default_weight=0.0,
        label="夜間",
        description="街灯なし・トンネルが少ないほど易しい。既定重み0(夜間ライドを重視する場合に個別に上げる想定)",
        category="観測",
        is_published=True,
        icon_id="crescent-moon",
        chip_label="夜間",
        time_scope="night_only",
    ),
    "bicycle_infra_quality": AxisDefinition(
        axis_id="bicycle_infra_quality",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material=material, weight=weight)
                for material, weight in _CAR_STRESS_BICYCLE_INFRA_FLAG_WEIGHTS
            ],
            breakpoints=_BICYCLE_INFRA_AXIS_BREAKPOINTS,
        ),
        default_weight=0.15,
        label="自転車インフラ",
        description="専用の自転車インフラ（分離自転車道・自転車レーン等）が整備されているほど易しい。",
        category="推定",
        is_published=True,
        chip_label="自転車道",
        show_map_icon=False,
    ),
}


@contextmanager
def axis_definitions_snapshot():
    """AXIS_DEFINITIONSの現在の中身をスナップショットし、ブロック終了時に復元する
    （改善計画T350のcode-review対応: 以前はこのスナップショット/復元パターンが
    本ファイル・test_evaluation_bulk.py・test_axis_registry_service.pyの3箇所に
    独立実装されていたため、共通プリミティブへ集約した）。

    ブロック内でAXIS_DEFINITIONSへ何を書き込むか（差し替えるか、そもそも書き込まないか）は
    呼び出し側の責務——本関数自体は「今の中身を憶えておいて、後で戻す」だけを行う。
    """
    original = dict(AXIS_DEFINITIONS)
    try:
        yield original
    finally:
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(original)


@contextmanager
def realistic_axis_definitions():
    """AXIS_DEFINITIONSの中身を一時的に`REALISTIC_AXIS_DEFINITIONS`へ差し替える
    （終了時に元の内容へ復元する）。"""
    with axis_definitions_snapshot():
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(REALISTIC_AXIS_DEFINITIONS)
        yield REALISTIC_AXIS_DEFINITIONS
