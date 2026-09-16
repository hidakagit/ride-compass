"""静的道路属性の派生分類（docs/static-road-attributes-plan.md P0・§2.4）。

すべて純関数・unknown安全（タグが無い/未知の値は`None`または`"unknown"`を返し、
根拠のない推測はしない）。正準定義はここ1箇所（domain/road.pyのGOOD/BAD_OSM_SURFACE_TAGSと
同じ「正準1箇所」の運用）。

車ストレスは軸定義（DBが正本、軸スタジオから増減する）の内部軸と公開軸の階層構造で
再現している。自転車インフラは正規化フラグ材料（`domain/recipe.py: bicycle_infra_flags`）
の組み合わせで表し、`domain/material_catalog.py`の抽出器がそこから材料値を取り出す。

分類のほかに、**所要時間モデルのパラメータ**も持つ（`STOP_SECONDS`: 停止要因1回あたりの
時間損失、`HIGHWAY_RANK`: 交差点で優先関係を判定するための階級順）。読むのは
`services/road_graph_engine.py`の走行時間合成で、評価軸の重み付けとは別の関心事
——軸は「その道を走るときのつらさ」、こちらは「そこを通るのにかかる時間」を表す。
"""

from typing import Literal

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
# `road_graph_repository.py: _POI_COUNT_KIND_EXPR`が持つ）。
_RAILWAY_STOP_KINDS: dict[str, StopPoiKind] = {
    "level_crossing": "level_crossing",
    "tram_level_crossing": "level_crossing",
    "crossing": "railway_crossing",
    "tram_crossing": "railway_crossing",
}

# 車止め・ゲート類（`barrier=*`）のうち、**自転車が止まる・降りる・すり抜けで大きく減速する
# ものだけ**を対象にする。値の網羅ではなく「進行を物理的に妨げる点か」で選んでおり、
# 次のものは意図的に外している（判断の根拠と実データ件数は`docs/tasks/T654.md`参照）:
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
# 集計キーは同じ（`_POI_COUNT_KIND_EXPR`）。`island`（中央島）・`no`は進行を妨げないため外す。
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

# 停止要因POIのkind正準集合（SQL側のkindフィルタ用）。補給POI（convenience/
# vending_machine等、SupplyPoiKind）が同じ`osm_raw_pois`テーブルへ入っているため、
# kindを絞らないCOUNTは停止密度へコンビニ・自販機を誤算入する。停止密度系のSQL
# （_STOP_POI_COUNTS_SQL等）は必ずこの集合でフィルタする（片側import。
# StopPoiKindのLiteral値と乖離しないようテストで照合する）。
STOP_POI_KINDS = (
    frozenset(_HIGHWAY_STOP_KINDS.values())
    | frozenset(_RAILWAY_STOP_KINDS.values())
    | {"barrier", "traffic_calming"}
)


# 停止要因の集計キー（`edge_attribute_counts.poi_counts`・`way_attribute_counts.poi_counts`の
# jsonbキー）と、その日本語ラベル。**キーの単一ソース**で、材料
# （`domain/material_catalog.py`の`poi_*_per_km`）はこの一覧から生成する。
#
# `StopPoiKind`（取込時の分類）と1対1ではない。分ける基準は「評価軸で違う重みを付けたいか」
# だけで、次の3点で異なる:
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

# 停止要因1回あたりの時間損失（秒）。**待ちの期待値＋減速と再加速のロス**の合計で、
# 所要時間へそのまま足す量。
#
# 内訳の考え方（信号の場合）:
# - 待ちの期待値 ＝ 赤に当たる確率 × 平均待ち時間 ＝ (赤/サイクル) × (赤/2)。サイクル120秒・
#   赤60秒なら 0.5 × 30 ＝ 15秒
# - 減速と再加速 ＝ 巡航速度まで戻すのに要る余分な時間。時速20kmで6秒前後
#
# 信号の無い横断歩道が0なのは、自転車は止まらず通過できるため（停止密度の軸でも重み0）。
# **これらの値は一般的な信号サイクルからの見積もりで、実走データでの較正が要る。**
STOP_SECONDS: dict[str, float] = {
    "signal": 21.0,
    "crossing": 0.0,
    "stop": 8.0,
    "level_crossing": 25.0,
    "barrier": 8.0,
}


def stop_seconds(kind: str) -> float:
    """停止要因の種別から1回あたりの時間損失（秒）。未知の種別は0。"""
    return STOP_SECONDS.get(kind, 0.0)


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

# 交差点ノードから何m以内の信号POIを「その交差点の信号」とみなすか。
#
# **較正されていない**。同じ交差点の点をまとめる距離（`POI_CLUSTER_EPS_M`）と同じ値だが、
# 問うていることが違う（あちらは「同じ停止か」、こちらは「この交差点に信号があるか」）ため
# 別の値として持つ。まとめる距離を動かしても走行モデルの横断の費用が一緒に動かないように
# するのが目的。
#
# **この値は結果を大きく動かす**: 幹線が集まる交差点のうち信号ありとみなす割合は、半径10mで
# 37.4%・60mで67.9%まで変わり、頭打ちが無い。広げるほど「信号が無いのに上位の道を渡る」と
# みなされる交差点が減り、横断の費用が付かなくなる。データからは決まらないため、実走での
# 確認が要る（`domain/routing.py: TurnCostSpec`の秒数も同じ）。
SIGNAL_MATCH_RADIUS_M = 40.0

# POIノードが「その区間の上にある」と判定する許容距離（m）。判定はwayの構成ノードである
# ことが主で、この距離は同じway内のどの区間に属するかを切り分けるためのもの
# （ノードは区間の線上にあるため、浮動小数の誤差を吸収できれば足りる）。
POI_ON_EDGE_TOLERANCE_M = 1.0


def classify_stop_poi(tags: dict[str, str]) -> StopPoiKind | None:
    """信号・横断歩道・一時停止・踏切の分類（静的道路属性P1、計画書§2.2）。node取込の
    対象node判定にも使う（osm_adapter.py: osm_node_to_poi_spec、Noneを返すnodeは取込対象外）。

    railway/highway/barrier/traffic_calmingは独立したタグのため同一nodeに複数付きうる。
    優先順位は railway → highway → barrier → traffic_calming で、止まる度合いが強い方を
    先に見る（踏切は自転車にとって一時停止の法的義務が信号・横断歩道より強く、質的に
    異なる）。いずれにも該当しなければNone（対象外・評価しない）。

    ここで返すkindは`import_profile.yaml`のnodeルールと対で意味を持つ——**プロファイルが
    通してもここがNoneを返すnodeは取り込まれない**ため、片方だけ増やしても何も起きない
    （`tests/test_import_profile.py`が両者の一致を検証する）。
    """
    railway = (tags.get("railway") or "").strip().lower()
    if railway in _RAILWAY_STOP_KINDS:
        return _RAILWAY_STOP_KINDS[railway]
    highway = (tags.get("highway") or "").strip().lower()
    if highway in _HIGHWAY_STOP_KINDS:
        return _HIGHWAY_STOP_KINDS[highway]
    if (tags.get("barrier") or "").strip().lower() in _BARRIER_STOP_VALUES:
        return "barrier"
    if (tags.get("traffic_calming") or "").strip().lower() in _TRAFFIC_CALMING_VALUES:
        return "traffic_calming"
    return None


SupplyPoiKind = Literal["convenience", "vending_machine", "toilets", "drinking_water", "bicycle_parking"]

_AMENITY_SUPPLY_KINDS: dict[str, SupplyPoiKind] = {
    "vending_machine": "vending_machine",
    "toilets": "toilets",
    "drinking_water": "drinking_water",
    "bicycle_parking": "bicycle_parking",
}


def classify_supply_poi(tags: dict[str, str]) -> SupplyPoiKind | None:
    """補給・休憩ポイント（コンビニ・自販機・トイレ・給水・駐輪場）の分類
    （static-road-attributes-plan.md §2.3）。classify_stop_poiと同じくnode取込の対象判定にも
    使う（osm_adapter.py: osm_node_to_poi_spec）。停止要因POIとタグ名（shop/amenity vs
    highway/railway）が独立しており衝突しないため、優先順位の考慮は不要。

    実店舗との乖離（閉店・移転にOSM側が追従できていないリスク）はタグ自体からは
    分からない。`backend/scripts/measure_poi_freshness.py`で要素の最終編集日時を
    代理指標に計測すると、コンビニ（shop=convenience）は直近2年以内の編集が関東全域で
    62.4%と明確に新しいが、自販機・トイレ・給水・駐輪場は5年以上未編集が58〜59%と高く、
    実店舗との乖離リスクが相対的に高い（フロント側mapLayers.ts: supplyPoiのpanelHintで
    「鮮度に注意」と明記して利用者に伝える。取込・分類自体は5種すべて対象とし、鮮度の
    扱いは表示側の注意喚起に留める）。
    """
    if (tags.get("shop") or "").strip().lower() == "convenience":
        return "convenience"
    amenity = (tags.get("amenity") or "").strip().lower()
    return _AMENITY_SUPPLY_KINDS.get(amenity)


# 交差点で「自分が走ってきた道より上位の道と交わるか」を判定するための階級順（大きいほど
# 上位）。**優先関係の判定だけに使う**——値そのものに意味は無く、比較結果だけが使われる。
# 評価軸が持つhighwayの重み付け（`car_stress_highway_base`、DBの軸定義）とは別の関心事で、
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
#: （自転車道・歩道は階級表に無く0になるため。[T800](../../../docs/tasks/T800.md)で
#: この判定を入れてから、その形の発火が増えていた）。
MAJOR_CROSSING_MIN_RANK = HIGHWAY_RANK["tertiary"]


def highway_rank(highway: str | None) -> int:
    """OSMのhighwayタグ生値を階級順へ写す。自転車道・歩道・未知の値は0（最下位）。"""
    return HIGHWAY_RANK.get(highway or "", 0)
