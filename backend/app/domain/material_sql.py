"""材料の値をSQLで導出する式の、単一の情報源。

材料が何から導かれるかはdomainの知識のため、式をここに置く。参照する側
（タイル配信・材料の読み出し・欠損割合集計・派生バッチ）はいずれもRoad Graphの
オブジェクトを構築せずDBを直接引く。同じ判定式を呼び出し側ごとに独立して書くと
ドリフトするため、ここへ集約する。表を読む文（生データの表から`w`を作る副問い合わせ等）は
実行する層が持ち、ここは別名の列に対する式だけを持つ。

式はテーブルのエイリアスを固定で参照する。FROM句は読み出し側が組み立てる:

| 別名 | 何 |
|---|---|
| `w` | 道の生データ（`infrastructure/source_models.py: ways_source_sql`。タグは`w.tags`、`highway`・`surface`は列としても出す） |
| `re` | `road_edges`（区間の形） |
| `em` | `edge_materials`（区間に付く値） |
| `wm` | `way_materials`（道1本に付く値） |

**値が無ければNULL**（NULLの意味は`docs/modules/backend/static-road-attributes.md`「値が無ければNULL」）。真偽の材料の
「タグが無い」は別で、道の行があれば非該当（false）になる（`tag_absent_is_false_sql`）。
"""

from collections.abc import Iterable, Sequence

from app.domain.road import (
    SURFACE_CLASSES,
    SURFACE_OTHER_KEY,
    TRACK_GRADES,
    TRACK_HIGHWAY,
    UNKNOWN_ROAD_SURFACE,
    UNKNOWN_TRACK_SURFACE,
    SurfaceClass,
    TrackGrade,
)
from app.domain.traffic import poi_count_column


def normalized_tag_sql(tag: str) -> str:
    """`tags`JSONBの1キーを正規化して参照する式（小文字化・前後空白除去）。"""
    return f"lower(btrim(w.tags->>'{tag}'))"


def positive_integer_tag_sql(tag: str) -> str:
    """数値タグ（maxspeed/lanes等）を、数値としてパースでき0より大きい場合のみ
    値を持つ式として参照する（0以下・非数値はNULL＝未取得と同じ扱い）。"""
    raw = f"btrim(w.tags->>'{tag}')"
    return (
        f"CASE WHEN {raw} ~ '^[0-9]+(\\.[0-9]+)?$' AND trunc({raw}::numeric) > 0 "
        f"THEN trunc({raw}::numeric)::integer END"
    )


HIGHWAY_SQL = "w.highway"
SURFACE_NORMALIZED_SQL = "lower(btrim(w.surface))"
TRACKTYPE_NORMALIZED_SQL = normalized_tag_sql("tracktype")


def _sql_literals(values: Iterable[str]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def _surface_class_branches(classes: Sequence[SurfaceClass]) -> str:
    return " ".join(
        f"WHEN {SURFACE_NORMALIZED_SQL} IN ({_sql_literals(c.tags)}) THEN '{c.key}'" for c in classes if c.tags
    )


def surface_class_sql(classes: Sequence[SurfaceClass]) -> str:
    """surfaceタグの路面区分。タグが無ければNULL、区分に無い値は`SURFACE_OTHER_KEY`。"""
    return (
        f"CASE {_surface_class_branches(classes)} "
        f"WHEN {SURFACE_NORMALIZED_SQL} IS NOT NULL THEN '{SURFACE_OTHER_KEY}' END"
    )


def surface_estimate_sql(classes: Sequence[SurfaceClass], grades: Sequence[TrackGrade]) -> str:
    """路面の見込み（`domain/road.py: SurfaceEstimate`）。surfaceの区分、無ければ等級から写した区分、
    どちらも無ければ道路種別で分けた「不明」。どの道も値を持つ。"""
    grade_branches = " ".join(
        f"WHEN {TRACKTYPE_NORMALIZED_SQL} = '{g.value}' THEN '{g.surface_class}'" for g in grades
    )
    return (
        f"CASE {_surface_class_branches(classes)} {grade_branches} "
        f"WHEN {HIGHWAY_SQL} = '{TRACK_HIGHWAY}' THEN '{UNKNOWN_TRACK_SURFACE.key}' "
        f"ELSE '{UNKNOWN_ROAD_SURFACE.key}' END"
    )


SURFACE_CLASS_SQL = surface_class_sql(SURFACE_CLASSES)
SURFACE_ESTIMATE_SQL = surface_estimate_sql(SURFACE_CLASSES, TRACK_GRADES)
SMOOTHNESS_NORMALIZED_SQL = normalized_tag_sql("smoothness")
MAXSPEED_KMH_CASE_SQL = positive_integer_tag_sql("maxspeed")
LANES_COUNT_CASE_SQL = positive_integer_tag_sql("lanes")
LIT_NORMALIZED_SQL = normalized_tag_sql("lit")
TUNNEL_NORMALIZED_SQL = normalized_tag_sql("tunnel")
BRIDGE_NORMALIZED_SQL = normalized_tag_sql("bridge")
MOTOR_VEHICLE_NORMALIZED_SQL = normalized_tag_sql("motor_vehicle")
BICYCLE_NORMALIZED_SQL = normalized_tag_sql("bicycle")

# 自転車インフラ系材料（highway_is_cycleway以外）が参照するcyclewayタグの完全な集合。
CYCLEWAY_TAG_NAMES = ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")
# 上記いずれかに値があるかを見るARRAY式（どのタグにも値が無い場合のみ欠損）。
_CYCLEWAY_TAGS_ARRAY_SQL = "ARRAY[" + ", ".join(f"lower(btrim(w.tags->>'{tag}'))" for tag in CYCLEWAY_TAG_NAMES) + "]"


def tag_absent_is_false_sql(condition: str) -> str:
    """タグが無ければ非該当（false）。`w`の行が無ければ不明（NULL）——行が無い区間はありうる。
    `road_edges.osm_way_id`の外部キーは`way_materials`へ向き、道の生データへは向かないため、取込で消えた道を、
    派生を作り直すまでの区間が指し続ける。"""
    return f"CASE WHEN w.osm_way_id IS NOT NULL THEN COALESCE({condition}, false) END"


def tag_is_value_sql(tag: str, expected: str) -> str:
    return tag_absent_is_false_sql(f"{normalized_tag_sql(tag)} = '{expected}'")


# 橋・トンネルとみなすのは、道が地面から浮いているか地中にある値だけ（値の意味は OSM wiki の
# Key:bridge・Key:tunnel）。地図の「橋・高架」「トンネル」と、勾配で地表を拾わない区間
# （`attributes.py: elevation_values_sql` の on_structure）が同じ道を指すよう、両方がここを読む。
# 建物の下の通路（building_passage）・道の下の水路（culvert）・水面すれすれの低い橋
# （low_water_crossing）は道が地表にあり、載っていない値も普通の道として扱う——知らない値を
# 構造物に入れると、地図に誤った橋・トンネルが出る。
_BRIDGE_STRUCTURE_VALUES = ("yes", "viaduct", "cantilever", "covered", "suspension_bridge", "boardwalk")
_TUNNEL_STRUCTURE_VALUES = ("yes", "avalanche_protector")
IS_BRIDGE_SQL = tag_absent_is_false_sql(f"{BRIDGE_NORMALIZED_SQL} IN ({_sql_literals(_BRIDGE_STRUCTURE_VALUES)})")
IS_TUNNEL_SQL = tag_absent_is_false_sql(f"{TUNNEL_NORMALIZED_SQL} IN ({_sql_literals(_TUNNEL_STRUCTURE_VALUES)})")


def cycleway_has_value_sql(*values: str) -> str:
    listed = ", ".join(f"'{v}'" for v in values)
    return tag_absent_is_false_sql(f"{_CYCLEWAY_TAGS_ARRAY_SQL} && ARRAY[{listed}]")


def per_km_value_sql(count: str) -> str:
    """区間の件数の式`count`を区間の長さ1kmあたりにする。件数がNULLなら欠損のまま。"""
    return f"{count} / (re.distance_m / 1000.0)"


def poi_density_value_sql(kind: str) -> str:
    """停止要因POIの種別別密度。列がNULLなら値が無い＝欠損。"""
    return per_km_value_sql(f"em.{poi_count_column(kind)}")


def landcover_value_sql(key: str) -> str:
    """区間単位の土地被覆。道1本の値へは落とさない——区間の値は全区間ぶん計算されており、
    落とす先は「同じ道の平均」でしかない（区間ごとの違いを消す）。"""
    return f"em.lc_{key}"


def length_weighted_mean_sql(value: str) -> str:
    """区間の値（`value`）を区間の長さで重み付けた平均の集約式。`GROUP BY`の中で、平均する区間を
    `re`・`em`として並べた行に対して使う。

    向きのある値（ジオメトリの始点→終点を正とする勾配等）も、同じ道の区間ならそのまま平均する。区間は
    道の点を並びの順に切ったもの（`batch/derive_topology.py`）で、どの区間も道と同じ向きを正とする。
    勾配なら、各区間の勾配へ長さを掛けると長さが約分されて標高差だけが残り、結果は両端の標高差を全長で
    割った値になる（崖を下って上り返す道は打ち消し合って0になる）。区間の方位で向きを揃え直すと、
    つづら折りのように道の両端を結ぶ方位から90度より大きく離れる区間の符号が反転し、登り続ける道が
    0%近くに打ち消し合う。値の無い区間は呼び出し側が除く——残すと分母の長さだけに数えられる。
    """
    return f"sum(({value}) * re.distance_m) / sum(re.distance_m)"
