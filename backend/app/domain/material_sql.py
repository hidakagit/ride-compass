"""材料の値をSQLで導出する式の、単一の情報源。

材料が何から導かれるかはdomainの知識のため、式をここに置く。参照する側
（`road_graph_repository.py`のタイル配信・材料の読み出し、`material_coverage.py`の
欠損割合集計）はいずれもRoad Graphのオブジェクトを構築せずDBを直接引くため、
`material_catalog.py`のPython extractorをそのまま使えない。同じ判定式を呼び出し側ごとに
独立して書くとドリフトするため、ここへ集約する。

式はテーブルのエイリアスを固定で参照する（`w`＝`osm_raw_ways`）。FROM句は読み出し側が
組み立てる。

人が書いた期待値との突き合わせは`tests/test_material_sql.py`。
"""

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
# 区間（road_edges）側のhighway。splitのときwayから写したもので、探索・0次フィルタは
# こちらを見る（way側はタイル配信が見る）。
HIGHWAY_SQL_FOR_EDGE = "re.highway"
SURFACE_NORMALIZED_SQL = "lower(btrim(w.surface))"
# :good_tags/:bad_tags バインドパラメータを要する（domain/road.py:
# GOOD_OSM_SURFACE_TAGS/BAD_OSM_SURFACE_TAGS、呼び出し元がbindparamsで渡す）。
SURFACE_GOOD_CASE_SQL = (
    f"CASE WHEN {SURFACE_NORMALIZED_SQL} = ANY(:good_tags) THEN true "
    f"WHEN {SURFACE_NORMALIZED_SQL} = ANY(:bad_tags) THEN false END"
)
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
# 上記いずれかに値があるかを見るARRAY式（4タグとも無い場合のみ欠損）。
CYCLEWAY_TAGS_ARRAY_SQL = "ARRAY[" + ", ".join(f"lower(btrim(w.tags->>'{tag}'))" for tag in CYCLEWAY_TAG_NAMES) + "]"


# --- 区間単位の材料の値を求める式 ---------------------------------------------
#
# 読み出し側が用意するエイリアス:
#   w  osm_raw_ways（LEFT JOIN、道路データの無い区間ではNULL行）
#   re road_edges
#   c  edge_attribute_counts（LEFT JOIN）
#   e  elevation_attributes（LEFT JOIN）
#   el edge_landcover（LEFT JOIN）
#   wl way_landcover（LEFT JOIN、elが無い区間のフォールバック）
#   d  指定路線のLATERAL（`is_designated`）
#
# 束ねるバインドパラメータ: :good_tags・:bad_tags・:accident_years
#
# **「wayが無い」と「タグが無い」を分ける。** 前者は不明（NULL）、後者は非該当（false）。
# 材料ごとの宣言もこれらを別々に指している——`MaterialSpec.bool_default="nan"`は前者を
# 守るためにあり、カバレッジの`missing_semantics="definite"`は後者が確定値だと言っている。
# `COALESCE(条件, false)`だけで閉じると、wayの行が無い区間まで「非該当」と答えてしまい、
# 前者の宣言が働かない。
#
# 本番では現在wayの行が無い区間は0件だが、これは「いまPBFが最新だから」であって、
# 遅延構築や再取込の途中では起きる（`docs/batch-pipeline-dependencies.md`）。

LANDCOVER_SQL_KEYS = (
    "trees", "built", "crops", "rangeland", "water", "bare", "flooded_veg", "snow_ice",
)


_WAY_PRESENT_PREFIX = "CASE WHEN w.osm_way_id IS NULL THEN NULL ELSE COALESCE("


def way_present_or_null_sql(condition: str) -> str:
    """wayの行が無ければNULL（不明）、あればタグの有無で真偽（非該当はfalse）。"""
    return f"{_WAY_PRESENT_PREFIX}{condition}, false) END"


def folds_tag_absence_to_false(value_sql: str) -> bool:
    """その値式が、wayの行さえあればタグの不在をfalseへ畳むものか。

    「wayの行が無い（不明）」と「タグが無い（非該当）」を分ける材料の判定を、値式の
    組み立て方から導く——材料の一覧を別に持つと、材料を1つ足したとき片方が取り残される。
    """
    return value_sql.startswith(_WAY_PRESENT_PREFIX)


def tag_is_value_sql(tag: str, expected: str) -> str:
    return way_present_or_null_sql(f"{normalized_tag_sql(tag)} = '{expected}'")


def cycleway_has_value_sql(*values: str) -> str:
    listed = ", ".join(f"'{v}'" for v in values)
    return way_present_or_null_sql(f"{CYCLEWAY_TAGS_ARRAY_SQL} && ARRAY[{listed}]")


def poi_density_value_sql(kind: str) -> str:
    """停止要因POIの種別別密度。`poi_counts`がNULLなら未集計＝欠損、行があって載っていない
    種別は0件と確定できる。"""
    return (
        "CASE WHEN c.poi_counts IS NOT NULL AND re.distance_m > 0 "
        f"THEN COALESCE((c.poi_counts->>'{kind}')::double precision, 0) "
        "/ (re.distance_m / 1000.0) END"
    )


def landcover_value_sql(key: str) -> str:
    """区間単位の土地被覆。行が無ければway単位へ落とす（読み出し側と同じ規約）。"""
    return f"COALESCE(el.{key}_percent, wl.{key}_percent)"




# `EdgeMaterialArrays`が標高属性を組み立てるとき、勾配だけは材料の列から読む
# （表示用の標高列と重複して持たないため）。
MATERIAL_ID_GRADIENT_PERCENT = "gradient_percent"


