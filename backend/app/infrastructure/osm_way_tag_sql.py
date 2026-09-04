"""`osm_raw_ways`のOSMタグから材料の値・欠損を判定するSQL断片の単一の情報源。

`road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQL`（地図タイル配信、Road Graphを
構築せず`osm_raw_ways`を直接クエリする経路）と`material_coverage.py`
（材料ごとの欠損割合集計、DB全体を対象にした集計クエリ）は、いずれも
`domain/material_catalog.py`のPython版extractorとは別に、SQL側で同じOSMタグ分類ロジックを
必要とする（両者ともRoad Graphオブジェクトを構築せずosm_raw_waysへ直接アクセスするため、
`_evaluate_axes_bulk`のPython extractorをそのまま使えない）。同じ判定式を呼び出し側ごとに
独立して書くと、一方だけ変更してもう一方が古いまま残るドリフトを招くため、ここへ集約する。

全断片は`osm_raw_ways`のテーブルエイリアスを`w`固定で参照する（両呼び出し元とも
`FROM osm_raw_ways AS w`を前提にする）。
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
