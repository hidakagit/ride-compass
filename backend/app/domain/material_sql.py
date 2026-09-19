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

from app.domain.traffic import POI_COUNT_KINDS


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
# 真偽の材料は`COALESCE(..., false)`で閉じる。Python側のextractorはway_tagsが取得できて
# いればタグ不在をFalseとして返し、読み出し経路のway_tagsは該当Wayが無くても空辞書になる
# ため、NULLを残すと意味がずれる（`EdgeMaterialBundle.way_tags`のdocstring参照）。

LANDCOVER_SQL_KEYS = (
    "trees", "built", "crops", "rangeland", "water", "bare", "flooded_veg", "snow_ice",
)


def _tag_is(tag: str, expected: str) -> str:
    return f"COALESCE({normalized_tag_sql(tag)} = '{expected}', false)"


def _cycleway_has(*values: str) -> str:
    listed = ", ".join(f"'{v}'" for v in values)
    return f"COALESCE({CYCLEWAY_TAGS_ARRAY_SQL} && ARRAY[{listed}], false)"


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


# 材料id → 値を求めるSQL式。`MATERIAL_CATALOG`に載っていて**ここに無い材料**は、SQLでは
# 求められないもの（リクエスト時に決まる風、評価へ配線していないDEFER材料）。
MATERIAL_VALUE_SQL: dict[str, str] = {
    "gradient_percent": "e.average_grade",
    "surface_good": SURFACE_GOOD_CASE_SQL,
    "surface": SURFACE_NORMALIZED_SQL,
    # 区間のhighwayはsplit時にwayから写したもの。探索がグラフ側で見ているのと同じ列を使う。
    "highway": HIGHWAY_SQL_FOR_EDGE,
    "smoothness": SMOOTHNESS_NORMALIZED_SQL,
    "tracktype": "w.tags->>'tracktype'",
    "maxspeed_kmh": MAXSPEED_KMH_CASE_SQL,
    "lanes_count": LANES_COUNT_CASE_SQL,
    "has_tunnel": _tag_is("tunnel", "yes"),
    "bridge": _tag_is("bridge", "yes"),
    "motor_vehicle_no": _tag_is("motor_vehicle", "no"),
    "lit": _tag_is("lit", "yes"),
    "highway_is_cycleway": "COALESCE(" + HIGHWAY_SQL_FOR_EDGE + " = 'cycleway', false)",
    "cycleway_has_track": _cycleway_has("track"),
    "cycleway_has_lane": _cycleway_has("lane"),
    "cycleway_has_shared": _cycleway_has("share_busway", "shared_lane"),
    "shared_pedestrian_path": (
        f"COALESCE(re.highway IN ('footway', 'path') "
        f"AND {BICYCLE_NORMALIZED_SQL} IN ('yes', 'designated'), false)"
    ),
    "is_designated": "COALESCE(d.is_designated, false)",
    # 件数は区間の長さで割る。長さ0の区間は「密度が定義できない」＝欠損。
    "intersection_count_per_km": (
        "CASE WHEN re.distance_m > 0 THEN c.intersection_count / (re.distance_m / 1000.0) END"
    ),
    # 事故はさらに収録年数で割る。年数が0以下なら欠損（年正規化ができない）。
    "accident_count_per_km_year": (
        "CASE WHEN re.distance_m > 0 AND :accident_years > 0 "
        "THEN c.accident_count / (re.distance_m / 1000.0) / :accident_years END"
    ),
    **{f"{key}_percent": landcover_value_sql(key) for key in LANDCOVER_SQL_KEYS},
    **{f"poi_{kind}_per_km": poi_density_value_sql(kind) for kind in POI_COUNT_KINDS},
}


# `EdgeMaterialArrays`が標高属性を組み立てるとき、勾配だけは材料の列から読む
# （表示用の標高列と重複して持たないため）。
MATERIAL_ID_GRADIENT_PERCENT = "gradient_percent"


