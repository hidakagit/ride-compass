"""一貫した軸システムを必要とするテストのための土台。

`AXIS_DEFINITIONS`はDBが唯一の正本で、プロセス起動直後は空のまま
`refresh_axis_definitions`がDBから読むまで埋まらない。評価の純関数を直接呼ぶテストは
「軸が1つも無い」状態では退化した結果（重み空・スコアNone）でも通ってしまうため、
土台として一貫した軸システムを入れる。

**本番の軸は模さない。** ここが配るのは軸の*性質*（shapeの種類・必須でない項・負の重み・
時間帯限定・表示の上書き・専用way値配信）であって、本番のid・ラベル・調整値ではない。
本番を借りると、その軸が今もそう動くという誤った仕様をテストが語る。

個々のテストがここの値を直接アサートすることは想定しない——値そのものを見たいテストは、
そのファイル内で必要な性質だけを持つ軸を組み立てる。
"""

from contextlib import contextmanager

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
)

FIXTURE_AXIS_DEFINITIONS: dict[str, AxisDefinition] = {
    # 専用way値配信を持つ軸。needs_*の組み合わせが違う2本を置き、
    # 「要求が揃っていない呼び出しを落とす」経路を両方通す。
    "axis_way_value_scored": AxisDefinition(
        axis_id="axis_way_value_scored",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="wind_drag_ratio")],
            breakpoints=[(-1.0, 0.0), (0.0, 20.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="軸ウ",
        description="",
        category="動的",
        is_published=True,
        dedicated_way_value_layer=True,
        dynamic_way_value_needs_time=True,
        dynamic_way_value_needs_bearing=True,
        dynamic_way_value_needs_speed=True,
    ),
    "axis_way_value_signed": AxisDefinition(
        axis_id="axis_way_value_signed",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (5.0, 50.0), (10.0, 100.0)],
        ),
        default_weight=0.2,
        label="軸グ",
        description="",
        category="観測",
        is_published=True,
        icon_id="incline",
        dedicated_way_value_layer=True,
        dynamic_way_value_needs_bearing=True,
    ),
    # 分類のshape。真偽2値のmappingを持つ唯一の軸。
    "axis_categorical": AxisDefinition(
        axis_id="axis_categorical",
        shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
        default_weight=0.2,
        label="軸カ",
        description="",
        category="観測",
        is_published=True,
        chip_label="チップカ",
    ),
    # 必須でない項と重み0の項を持つ軸。欠損しても軸全体が評価不能にならない経路と、
    # 「登録はされているが寄与しない材料」の経路を通す。表示の上書きもここが持つ。
    "axis_optional_terms": AxisDefinition(
        axis_id="axis_optional_terms",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="poi_signal_per_km", weight=1.0, required=False),
                MaterialTerm(material="poi_level_crossing_per_km", weight=1.5, required=False),
                MaterialTerm(material="poi_stop_per_km", weight=0.3, required=False),
                MaterialTerm(material="poi_crossing_per_km", weight=0.0, required=False),
            ],
            breakpoints=[(0.0, 0.0), (1.0, 50.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="軸オ",
        description="",
        category="推定",
        is_published=True,
        panel_hint="この軸の説明。",
        display_thresholds_override=[1.0, 2.0, 3.0],
        display_band_labels_override=["段1", "段2", "段3", "段4"],
    ),
    # 実行時スケールを要する材料（収録年数で割る前の生値がタイルに焼かれている）を使う
    # 唯一の軸。配線が外れると地図の値だけが静かに桁違いになる。
    "axis_runtime_scaled": AxisDefinition(
        axis_id="axis_runtime_scaled",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="accident_count_per_km_year")],
            breakpoints=[(0.0, 0.0), (1.0, 100.0)],
        ),
        default_weight=0.1,
        label="軸ラ",
        description="",
        category="推定",
        is_published=True,
        display_thresholds_override=[0.25, 0.5, 0.75],
    ),
    # 時間帯限定の軸。既定重み0で、負の重みを持つ項がある。
    "axis_night_only": AxisDefinition(
        axis_id="axis_night_only",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="lit", weight=-50.0),
                MaterialTerm(material="has_tunnel", weight=50.0),
            ],
            breakpoints=[(-50.0, 0.0), (50.0, 100.0)],
        ),
        default_weight=0.0,
        label="軸ナ",
        description="",
        category="観測",
        is_published=True,
        time_scope="night_only",
    ),
    # 地図にアイコンを出さない軸。
    "axis_no_map_icon": AxisDefinition(
        axis_id="axis_no_map_icon",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="highway_is_cycleway", weight=-4.0)],
            breakpoints=[(-4.0, 0.0), (0.0, 100.0)],
        ),
        default_weight=0.1,
        label="軸ノ",
        description="",
        category="推定",
        is_published=True,
        show_map_icon=False,
    ),
    # 土地被覆由来の材料を使う唯一の軸。外すと`trees_percent`/`built_percent`を実際に
    # 評価する経路がテストから消え、配線が外れていても全経路が同じ「欠損」を返して
    # 一致してしまう。
    "axis_landcover": AxisDefinition(
        axis_id="axis_landcover",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="trees_percent", weight=-1.0),
                MaterialTerm(material="built_percent", weight=-1.0),
            ],
            breakpoints=[(-100.0, 0.0), (0.0, 100.0)],
        ),
        default_weight=0.0,
        label="軸ド",
        description="",
        category="推定",
        is_published=True,
    ),
}


@contextmanager
def axis_definitions_snapshot():
    """`AXIS_DEFINITIONS`の今の中身を憶えておき、ブロック終了時に戻す。

    ブロック内で何を書き込むか（差し替えるか、そもそも書き込まないか）は呼び出し側の責務。
    """
    original = dict(AXIS_DEFINITIONS)
    try:
        yield original
    finally:
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(original)


@contextmanager
def fixture_axis_definitions():
    """`AXIS_DEFINITIONS`を一時的に`FIXTURE_AXIS_DEFINITIONS`へ差し替える。"""
    with axis_definitions_snapshot():
        AXIS_DEFINITIONS.clear()
        AXIS_DEFINITIONS.update(FIXTURE_AXIS_DEFINITIONS)
        yield FIXTURE_AXIS_DEFINITIONS
