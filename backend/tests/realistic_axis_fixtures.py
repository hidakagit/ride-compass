"""統合寄りのテスト向け、本番相当の軸データ。

`AXIS_DEFINITIONS`はDBが唯一の正本で、プロセス起動直後は空のまま
`refresh_axis_definitions`がDBから読み込むまで埋まらない。ルート生成の実処理を
テストするファイルの多くはDBを介さず評価の純関数を直接呼ぶため、
「実在のaxis_idを持つ、一貫した軸システム」が入っていることを暗黙に前提にしている。

本モジュールは、撤去前のPython literalと同じ構造（axis_id・shape・材料参照・階層）を
テストコード側に複製した「テスト専用の固定フィクスチャ」。DBの現在値を検証する目的では
なく、あくまで「一貫した軸システムを必要とする他のロジックのテスト」を成立させるための
土台であり、個々のテストがこのモジュールの値を直接アサートすることは想定しない
（値そのものを検証したいテストは、testファイル内でさらに局所的な合成軸を定義すること。
`tests/test_difficulty.py`・`tests/test_axis_display.py`・`tests/test_evaluation_bulk.py`
参照）。DBの実データとは完全に独立しており、DB側の値が変わってもこのフィクスチャは
追従不要。
"""

from contextlib import contextmanager

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
)
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
        dedicated_way_value_layer=True,
        dynamic_way_value_needs_bearing=True,
    ),
    "wind": AxisDefinition(
        axis_id="wind",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="wind_drag_ratio")],
            breakpoints=[(-1.2, 0.0), (0.0, 15.0), (5.0, 100.0)],
        ),
        default_weight=0.26,
        label="風",
        description="向かい風が弱いほど易しい",
        category="動的",
        is_published=True,
        dedicated_way_value_layer=True,
        dynamic_way_value_needs_time=True,
        dynamic_way_value_needs_bearing=True,
        dynamic_way_value_needs_speed=True,
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
        # 本番の停止密度軸と同じ形（種別別のPOI密度4件、横断歩道は重み0）。軸idだけは
        # テストの読みやすさのため`stop_density`のままにしてある（本番はGUI採番のid）。
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="poi_signal_per_km", weight=1.0, required=False),
                MaterialTerm(material="poi_level_crossing_per_km", weight=1.5, required=False),
                MaterialTerm(material="poi_stop_per_km", weight=0.3, required=False),
                # 信号を伴わない横断歩道は、道なりに走る自転車の停止要因にならない。
                MaterialTerm(material="poi_crossing_per_km", weight=0.0, required=False),
            ],
            breakpoints=[(0.0, 0.0), (0.5, 20.0), (1.5, 50.0), (3.0, 75.0), (5.0, 100.0)],
        ),
        default_weight=0.20,
        label="停止密度",
        description="止まる回数（信号・踏切・一時停止）が少ないほど易しい。信号の無い横断歩道と交差点の多さは含みません。",
        category="推定",
        is_published=True,
        icon_id="density-stack",
        chip_label="停止密度",
        panel_hint="信号・踏切・一時停止が道路上でどれだけ密集しているかの目安です。"
        "信号の無い横断歩道と交差点は数えません。実際の位置は『停止要因』レイヤーで確認できます。",
        display_thresholds_override=[2.0, 4.0, 7.0, 12.0],
        display_band_labels_override=[
            "500m以上で1回停止",
            "250〜500mで1回停止",
            "143〜250mで1回停止",
            "83m〜143mで1回停止",
            "83m以下で1回停止",
        ],
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
        # 収録年数3で割った値（本番DBの実際の移行値と同じ、docs/records/tasks/T404.md参照）を使う。
        display_thresholds_override=[0.133, 0.267, 0.5],
    ),
    "night": AxisDefinition(
        axis_id="night",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="lit", weight=-50.0),
                MaterialTerm(material="has_tunnel", weight=50.0),
            ],
            breakpoints=[(-50.0, 0.0), (50.0, 100.0)],
        ),
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
    # 土地被覆（way_landcover）由来の材料を使う唯一の公開軸。この軸をフィクスチャへ
    # 含めないと、`trees_percent`/`built_percent`を実際に評価する経路がテストから
    # 消え、材料の配線が外れていても全経路が同じ「欠損」を返して一致してしまう。
    "openness": AxisDefinition(
        axis_id="openness",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="trees_percent", weight=-1.0),
                MaterialTerm(material="built_percent", weight=-1.0),
            ],
            breakpoints=[(-100.0, 0.0), (-80.0, 30.0), (-20.0, 100.0)],
        ),
        default_weight=0.0,
        label="開放度",
        description="周囲に建物・樹木などの遮蔽物が少ない[開けている]道ほど難しい",
        category="推定",
        is_published=True,
        chip_label="開放",
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
