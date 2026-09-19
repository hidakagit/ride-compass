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
