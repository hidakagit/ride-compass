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

**未計算はNULL**。値の列がNULLなら、その材料はまだ計算されていない。「タグが無い」は
別で、そちらは非該当（false）になる（`tag_absent_is_false_sql`）。
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
    """タグが無ければ非該当（false）。**wayの行は必ずある**——区間はwayの派生で、
    `road_edges.osm_way_id`がNOT NULL + FKのため「wayの行が無い区間」は作れない。"""
    return f"COALESCE({condition}, false)"


def tag_is_value_sql(tag: str, expected: str) -> str:
    return tag_absent_is_false_sql(f"{normalized_tag_sql(tag)} = '{expected}'")


def cycleway_has_value_sql(*values: str) -> str:
    listed = ", ".join(f"'{v}'" for v in values)
    return tag_absent_is_false_sql(f"{_CYCLEWAY_TAGS_ARRAY_SQL} && ARRAY[{listed}]")


def poi_density_value_sql(kind: str) -> str:
    """停止要因POIの種別別密度。列がNULLなら未計算＝欠損。"""
    column = f"em.{poi_count_column(kind)}"
    return (f"CASE WHEN {column} IS NOT NULL AND re.distance_m > 0 "
            f"THEN {column} / (re.distance_m / 1000.0) END")


def landcover_value_sql(key: str) -> str:
    """区間単位の土地被覆。道1本の値へは落とさない——区間の値は全区間ぶん計算されており、
    落とす先は「同じ道の平均」でしかない（区間ごとの違いを消す）。"""
    return f"em.lc_{key}"
