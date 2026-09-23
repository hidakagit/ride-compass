"""静的道路属性の派生分類。

すべて純関数・unknown安全（タグが無い/未知の値は`None`または`"unknown"`を返し、
根拠のない推測はしない）。OSMタグからこれらの分類を導く規則の正本はここ1箇所。

車ストレスは軸定義（DBが正本、軸スタジオから増減する）の内部軸と公開軸の階層構造で
再現している。自転車インフラは正規化フラグ材料（`domain/material_catalog.py`が宣言する
`highway_is_cycleway`等）の組み合わせで表す。

分類のほかに、**所要時間モデルのパラメータ**も持つ（`stop_seconds`: 停止要因1回あたりの
時間損失、`HIGHWAY_RANK`: 交差点で優先関係を判定するための階級順）。読むのは
`services/road_graph_engine.py`の走行時間合成で、評価軸の重み付けとは別の関心事
——軸は「その道を走るときのつらさ」、こちらは「そこを通るのにかかる時間」を表す。
"""

from typing import Literal, get_args
from app.domain.tuning import TUNING_PARAMETERS_BY_ID, stop_seconds_parameter_id, tuning_value

# 交差点判定の次数しきい値（この数以上の異なる隣接Nodeを持つNodeを交差点とみなす）。
INTERSECTION_DEGREE_THRESHOLD = 3

StopPoiKind = Literal[
    "traffic_signals",
    "crossing",
    "stop",
    "give_way",
    "level_crossing",
    "railway_crossing",
    "barrier",
    "traffic_calming",
]

_HIGHWAY_STOP_KINDS: dict[str, StopPoiKind] = {
    "traffic_signals": "traffic_signals",
    "crossing": "crossing",
    "stop": "stop",
    "give_way": "give_way",
}

# 踏切。`level_crossing`は車道が線路を渡る踏切、`crossing`は歩道・自転車道が渡る踏切で、
# 自転車にとってはどちらも同じ「線路を渡るため止まる/徐行する点」。路面電車側
# （tram_*）も同じ扱いにする。kindを分けたまま持つのは、後から集計を分けたくなったときに
# 生タグを読み直さずに済ませるため（集計キーへの写像は
# `batch/derive_counts.py: COUNT_KIND_OF`が持つ）。
_RAILWAY_STOP_KINDS: dict[str, StopPoiKind] = {
    "level_crossing": "level_crossing",
    "tram_level_crossing": "level_crossing",
    "crossing": "railway_crossing",
    "tram_crossing": "railway_crossing",
}

# 車止め・ゲート類（`barrier=*`）のうち、**自転車が止まる・降りる・すり抜けで大きく減速する
# ものだけ**を対象にする。値の網羅ではなく「進行を物理的に妨げる点か」で選んでおり、
# 次のものは意図的に外している:
# `kerb`（段差。lowered/flushが過半で停止要因として識別力が無い）・`toll_booth`
# （自動車専用道路上で、取込対象の道路には乗らない）・`entrance`（塀・柵の開口部＝通れる）・
# `fence`/`wall`/`guard_rail`/`jersey_barrier`（道に沿う構造物で、渡る点ではない）。
_BARRIER_STOP_VALUES: frozenset[str] = frozenset(
    {
        "cycle_barrier",
        "bollard",
        "gate",
        "lift_gate",
        "swing_gate",
        "sliding_gate",
        "bump_gate",
        "hampshire_gate",
        "kissing_gate",
        "wicket_gate",
        "stile",
        "turnstile",
        "block",
        "chain",
        "rope",
        "log",
        "planter",
        "height_restrictor",
        "motorcycle_barrier",
        "yes",
    }
)

# 減速構造（`traffic_calming=*`）。停止ではなく減速のため車止めとは別kindで持つが、
# 集計キーは同じ（`batch/derive_counts.py: COUNT_KIND_OF`）。`island`（中央島）・`no`は
# 進行を妨げないため外す。
_TRAFFIC_CALMING_VALUES: frozenset[str] = frozenset(
    {
        "hump",
        "bump",
        "table",
        "cushion",
        "chicane",
        "choker",
        "mini_bumps",
        "rumble_strip",
        "yes",
    }
)

# 停止要因POIのkind正準集合（SQL側のkindフィルタ用）。補給POI（SupplyPoiKind）も同じ
# `node_materials.kind`に入っているため、kindを絞らないCOUNTは停止密度へコンビニ・
# 自販機を誤算入する。停止要因を数える・まとめるSQLは必ずこの集合でフィルタする。
#
# **型の宣言から導く。** 集合を別に並べると、型に無いkindを集合へ入れられてしまい、
# その分だけ停止密度が静かに増える（引き当ての表と突き合わせる検査が要らなくなる）。
STOP_POI_KINDS: frozenset[str] = frozenset(get_args(StopPoiKind))


# 停止要因の集計キー（`edge_materials`・`way_materials`の件数列`poi_<キー>`）と、
# その日本語ラベル。**キーの単一ソース**で、材料
# （`domain/material_catalog.py`の`poi_*_per_km`）はこの一覧から生成する。
#
# `StopPoiKind`（取込時の分類）と1対1ではない。分ける基準は「評価軸で違う重みを付けたいか」
# だけで、次のように畳む:
# - 信号は`highway=traffic_signals`と`highway=crossing`＋`crossing=traffic_signals`の
#   両方の書かれ方があり、どちらも同じ「止まる信号」のため`signal`へまとめる
#   （分けずにまとめないと、押しボタン式・歩車分離の信号が横断歩道に紛れる）
# - `crossing`のうち信号を伴わないものだけが`crossing`（ほぼ停止要因にならない）
# - `give_way`は`stop`へ畳む（実データ上ほぼ存在せず、一時停止と重みを分ける意味が無い）
# - 踏切は車道用（`level_crossing`）と歩道・自転車道用（`railway_crossing`）を`level_crossing`へ
#   まとめる（自転車にとってはどちらも同じ「線路を渡る点」）
# - 車止め（`barrier`）と減速構造（`traffic_calming`）は`barrier`へまとめる（どちらも
#   「構造物のせいで止まる・大きく減速する」点で、重みを分ける根拠がまだ無い）
POI_COUNT_KINDS: dict[str, str] = {
    "signal": "信号",
    "crossing": "横断歩道(信号なし)",
    "stop": "一時停止・徐行",
    "level_crossing": "踏切",
    "barrier": "車止め・減速構造",
}

# 数える種別すべてに較正値の宣言があることを、読み込みの時点で確かめる。`tuning.py`は
# こちらをimportできない（循環する）ため、両者の対応を宣言から導けるのはこの向きだけで、
# 宣言の欠けは「その種別の待ちが0秒」として所要時間から見分けられずに消える。
_UNDECLARED_STOP_KINDS = tuple(
    kind for kind in POI_COUNT_KINDS
    if stop_seconds_parameter_id(kind) not in TUNING_PARAMETERS_BY_ID
)
if _UNDECLARED_STOP_KINDS:
    raise RuntimeError(
        f"停止要因の較正値が`domain/tuning.py`に宣言されていない種別: {_UNDECLARED_STOP_KINDS}")


# 停止要因1回あたりの時間損失（秒）は**待ちの期待値＋減速と再加速のロス**の合計で、
# 所要時間へそのまま足す量。信号の無い横断歩道が0なのは、自転車が止まらず通過できるため。
def stop_seconds(kind: str) -> float:
    """停止要因の種別から1回あたりの時間損失（秒）。

    秒数は`domain/tuning.py`が宣言する（走ってみて決める値のため、管理画面から変えられる）。
    """
    return tuning_value(stop_seconds_parameter_id(kind))


def stop_count_material_ids() -> tuple[str, ...]:
    """停止の待ちを所要時間へ足すのに要る材料id（`POI_COUNT_KINDS`と1対1）。

    走行モデルはこれらを**軸の構成と無関係に**必要とする。軸が分解した材料だけを
    経路へ運ぶ既定（`evaluation.py: route_facing_material_ids`）に任せると、停止の軸を
    非公開にした瞬間に所要時間から停止の待ちが静かに消える。
    """
    return tuple(f"poi_{kind}_per_km" for kind in POI_COUNT_KINDS)


# 同じ場所にある同種の点を1つの停止としてまとめる距離（m）。日本のOSMは1つの信号交差点を
# 流入路ごとの`highway=traffic_signals`と横断歩道位置の`highway=crossing`＋
# `crossing=traffic_signals`という複数ノードで描くため、ノードを素直に数えると停止回数を
# 上回る。集計時にこの距離でまとめてから数える。
POI_CLUSTER_EPS_M = 40.0


SupplyPoiKind = Literal[
    "convenience", "vending_drinks", "vending_unknown", "toilets", "drinking_water", "bicycle_parking"
]

_AMENITY_SUPPLY_KINDS: dict[str, SupplyPoiKind] = {
    "toilets": "toilets",
    "drinking_water": "drinking_water",
    "bicycle_parking": "bicycle_parking",
}

# 自販機のうち「口に入るものが買える」と言い切れる`vending`の値。OSM wikiで使用実績のある値の
# うち飲食物を売る機械だけを挙げる。複数の値は`;`で連結されるため、分割した要素のどれかが
# ここにあれば飲料自販機として扱う。
SUPPLY_VENDING_VALUES: frozenset[str] = frozenset(
    {
        "drinks", "beverages", "coffee", "water", "milk", "food", "sweets",
        "ice_cream", "chewing_gums", "bread", "fruit", "vegetables", "eggs",
    }
)


# 交差点で「自分が走ってきた道より上位の道と交わるか」を判定するための階級順（大きいほど
# 上位）。**優先関係の判定だけに使う**——値そのものに意味は無く、比較結果だけが使われる。
# 評価軸が持つhighwayの重み付け（DBの軸定義）とは別の関心事で、
# あちらは「その道を走るときの圧迫感」、こちらは「その道を横断・合流するときの待ち」。
HIGHWAY_RANK: dict[str, int] = {
    "motorway": 6, "motorway_link": 6,
    "trunk": 5, "trunk_link": 5,
    "primary": 4, "primary_link": 4,
    "secondary": 3, "secondary_link": 3,
    "tertiary": 2, "tertiary_link": 2,
    "unclassified": 1, "residential": 1, "living_street": 1, "service": 1,
}


#: 「車列の切れ目を待つ」交差点とみなす最低の階級。生活道路・サービス道路（階級1）を
#: 横切るのに待ちは要らない——待ちが要るのは通過交通のある道で、この表では tertiary 以上。
#: **階級の大小だけで判定すると、自転車道（0）からサービス道路（1）へ出るだけで成立する**
#: （自転車道・歩道は階級表に無く0になるため）。
MAJOR_CROSSING_MIN_RANK = HIGHWAY_RANK["tertiary"]


def highway_rank(highway: str | None) -> int:
    """OSMのhighwayタグ生値を階級順へ写す。自転車道・歩道・未知の値は0（最下位）。"""
    return HIGHWAY_RANK.get(highway or "", 0)


# OSMのoneway値のうち「逆方向への通行不可」を意味するもの。
ONEWAY_FORWARD_ONLY = {"yes", "true", "1"}
ONEWAY_BACKWARD_ONLY = {"-1", "reverse"}
# 同じく「両方向通行可」を明示するもの。`oneway`が無い場合と区別が要る——無い場合は
# `junction`による暗黙の一方通行へ進むが、明示されているならそちらが優先する。
ONEWAY_BIDIRECTIONAL = {"no", "false", "0"}
# `oneway`タグが無くても一方通行になるjunctionの値。環状交差点は構造として一方向にしか
# 通れず、OSMは個々のwayへ`oneway`を付けない慣行がある。
ONEWAY_JUNCTION_VALUES = {"roundabout", "circular"}


# --- タグの引き当てを、SQLへ渡せる表と式で持つ -------------------------------
#
# 分類はDB側で行う。派生の入力も出力もDBにあり、タグを読むためだけに行を取り出さない。
# Pythonのif順で表していた優先順位は`priority`列が持つ（小さいほど先に当たる）。

#: 引き当ての順。**先に書いた群が先に当たる**——優先順位はこの並びから振るため、
#: 「停止要因を補給・休憩より先に当てる」は群を並べ替えない限り破れない。
_TAG_KIND_GROUPS: tuple[tuple[str, dict[str, str]], ...] = (
    ("railway", dict(_RAILWAY_STOP_KINDS)),
    ("highway", dict(_HIGHWAY_STOP_KINDS)),
    ("barrier", {value: "barrier" for value in sorted(_BARRIER_STOP_VALUES)}),
    ("traffic_calming", {v: "traffic_calming" for v in sorted(_TRAFFIC_CALMING_VALUES)}),
    ("shop", {"convenience": "convenience"}),
    ("amenity", dict(_AMENITY_SUPPLY_KINDS)),
)

#: (タグ名, 値, 付ける種別, 優先順位)。値は前後の空白を落として小文字にしてから比べる。
TAG_KIND_RULES: tuple[tuple[str, str, str, int], ...] = tuple(
    (tag_key, value, kind, priority)
    for priority, (tag_key, values) in enumerate(_TAG_KIND_GROUPS, start=1)
    for value, kind in values.items()
)

#: 自販機だけは`vending`の値が`;`で連なるため表に落ちない。式で当てる。どの群よりも
#: 後に見る（`amenity`の表に`vending_machine`は無いので、ここが最後の引き当てになる）。
_VENDING_PRIORITY = len(_TAG_KIND_GROUPS) + 1

#: 信号の判定。**`TAG_KIND_RULES`と違い、値を正規化せずそのまま比べる**——
#: 現行の判定がそうであり、ここで揃えると付く信号の数が変わる。
TRAFFIC_SIGNAL_SQL = (
    "(tags->>'highway' = 'traffic_signals'"
    " OR (tags->>'highway' = 'crossing'"
    "     AND position('signals' in coalesce(tags->>'crossing', '')) > 0))"
)

_ONEWAY_DIRECTIONS: dict[str, str] = {
    **{value: "forward" for value in sorted(ONEWAY_FORWARD_ONLY)},
    **{value: "backward" for value in sorted(ONEWAY_BACKWARD_ONLY)},
    **{value: "both" for value in sorted(ONEWAY_BIDIRECTIONAL)},
}

#: 引き当ての順。`oneway:bicycle`（自転車に限り一方通行規制の対象外、という例外タグ）を
#: `oneway`より前へ、`junction`からの含意を最後へ置く。
_DIRECTION_GROUPS: tuple[tuple[str, dict[str, str]], ...] = (
    ("oneway:bicycle", _ONEWAY_DIRECTIONS),
    ("oneway", _ONEWAY_DIRECTIONS),
    ("junction", {value: "forward" for value in sorted(ONEWAY_JUNCTION_VALUES)}),
)

#: (タグ名, 値, 通行方向, 優先順位)。
DIRECTION_RULES: tuple[tuple[str, str, str, int], ...] = tuple(
    (tag_key, value, direction, priority)
    for priority, (tag_key, values) in enumerate(_DIRECTION_GROUPS, start=1)
    for value, direction in values.items()
)

#: どの規則にも当たらない道は両方向。
DIRECTION_DEFAULT = "both"


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _values_clause(rules: tuple[tuple[str, str, str, int], ...]) -> str:
    return ", ".join(
        f"({_quote(key)}, {_quote(value)}, {_quote(result)}, {priority})"
        for key, value, result, priority in rules)


def _rule_match_sql(rules: tuple[tuple[str, str, str, int], ...]) -> str:
    """表の規則に当たった候補を (id, result, priority) で返す断片。"""
    return f"""
    SELECT s.id, r.result, r.priority
    FROM src s JOIN (VALUES {_values_clause(rules)})
                 AS r(tag_key, tag_value, result, priority)
      ON lower(btrim(s.tags->>r.tag_key)) = r.tag_value"""


def tag_kind_sql(source: str) -> str:
    """`source`（`id`・`tags`を返す関係）の各行へ、停止要因・補給休憩の種別を1つ付ける。

    どれにも当たらない行は返らない。
    """
    vending = ", ".join(_quote(v) for v in sorted(SUPPLY_VENDING_VALUES))
    return f"""
WITH src AS ({source}),
matched AS ({_rule_match_sql(TAG_KIND_RULES)}
    UNION ALL
    SELECT s.id, v.result, {_VENDING_PRIORITY}
    FROM src s
    CROSS JOIN LATERAL (
        SELECT CASE WHEN coalesce(array_length(q.vals, 1), 0) = 0 THEN 'vending_unknown'
                    WHEN q.vals && ARRAY[{vending}] THEN 'vending_drinks' END AS result
        FROM (SELECT array_remove(array_agg(nullif(btrim(lower(t)), '')), NULL) AS vals
              FROM unnest(string_to_array(coalesce(s.tags->>'vending', ''), ';')) AS t) q
    ) v
    WHERE lower(btrim(s.tags->>'amenity')) = 'vending_machine' AND v.result IS NOT NULL
)
SELECT DISTINCT ON (id) id, result AS kind FROM matched ORDER BY id, priority
"""


def direction_sql(source: str) -> str:
    """`source`（`id`・`tags`を返す関係）の各行へ通行方向を付ける。

    どれにも当たらない行も`DIRECTION_DEFAULT`で返る——道は必ずどちらかに通れる。
    """
    return f"""
WITH src AS ({source}),
matched AS ({_rule_match_sql(DIRECTION_RULES)}),
best AS (SELECT DISTINCT ON (id) id, result FROM matched ORDER BY id, priority)
SELECT s.id, coalesce(b.result, {_quote(DIRECTION_DEFAULT)}) AS direction
FROM src s LEFT JOIN best b ON b.id = s.id
"""
