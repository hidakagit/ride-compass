# サンプル点から自前DBのEdgeへ空間マッチする際のスナップ半径（改善計画T44）。
# OSMのgeometryとORSが返すgeometryは同じ道路でも数m単位でずれうるため、GPSノイズ程度の
# 誤差は許容しつつ、別の道路（並走する歩道等）へ誤スナップしない範囲としてこの値を選んだ。
# openrouteservice_engine.py（明示引数）とAttributeRepository各メソッド（デフォルト引数）の
# 両方がこの定数をimportして参照する。片側だけ値を変えるとエンジン間で評価が食い違うため、
# 「コメントで揃える」手動同期にしない（設計原則2）。
SURFACE_MATCH_MAX_DISTANCE_M = 30.0

# 路面評価の正準定義（両ルーティングエンジン共通）:
# 「走行しやすい舗装路面か」を 良い(True) / 悪い(False) / 不明(None) の3値で判定し、
# road_score（舗装率%）は判定できた区間だけを分母にする（不明=無視。不明を「悪い」扱いに
# しない）。全区間が不明ならNone。OSMタグ語彙（classify_osm_surface）が両エンジン共通の
# 唯一の判定源（改善計画T21。以前はopenrouteserviceの数値ID語彙が別に存在したが、
# ORS産geometryのサンプル点を自前DBのEdgeへ空間マッチする方式へ統一し廃止した）。


def distance_weighted_road_score(pairs: list[tuple[float, bool | None]]) -> float | None:
    """(区間の距離, 走行しやすい舗装路面か)のペア列から、距離加重の舗装率(%)を算出する。

    不明（None）の区間は分母から除外する（不明を「悪い路面」扱いにしない、冒頭の正準定義
    参照）。判定できる区間が1つも無ければNone。両エンジンで共通の集約ロジック
    （road_graph_engine.pyはEdgeのdistance_m、openrouteservice_engine.pyはサンプル区間の
    distance_kmを渡す。単位はどちらでも比率の算出には影響しない）。
    """
    known = sum(distance for distance, is_good in pairs if is_good is not None)
    if known <= 0:
        return None
    good = sum(distance for distance, is_good in pairs if is_good)
    return round(good / known * 100, 1)


# OSMのsurfaceタグ（自由記述に近い文字列）による判定。
#
# この2集合が路面語彙の**単一ソース**であり、以下がすべてここへ追従する
# （改善計画T7。docs/design-review-2026-08-15.md 設計原則1）:
# - PostGIS側のMVT生成SQL（road_graph_repository.py: _ROAD_SURFACE_TILE_MVT_SQLがバインド）
# - フロントエンドの路面グループ定義との整合検証
#   （backend/scripts/export_openapi.pyがsurface-tags.jsonとして書き出し、
#   frontend/src/components/Map/roadFilterAxes.test.tsが表示グループとの対応を検証する。
#   タグを増減したらexport_openapi.pyの再実行とフロントのグループ定義の追従が必要）
GOOD_OSM_SURFACE_TAGS = {
    "asphalt",
    "paved",
    "concrete",
    "paving_stones",
    "concrete:plates",
    "concrete:lanes",
    # チップシール（表面処理舗装）。フロントの表示グループでは「アスファルト」に含めて
    # 緑表示していたのに評価上は不明（分母から除外）で、地図の色とルート評価が食い違って
    # いた（設計レビューF1）。ロードバイクで普通に走れる舗装のためGOODへ分類する。
    "chipseal",
    # レンガ舗装。paving_stonesと同様の平滑な舗装ブロックとして扱う（同F1、
    # フロントの「石畳・敷石」グループ内で唯一未分類だった）。
    "bricks",
}
BAD_OSM_SURFACE_TAGS = {
    "unpaved",
    "gravel",
    "dirt",
    "ground",
    "sand",
    "grass",
    "cobblestone",
    "sett",
    "compacted",
    "fine_gravel",
    "pebblestone",
    "mud",
    "woodchips",
    "earth",
    # 岩盤・粗い岩。フロントの「砂利・締固め」グループでは可視化済みなのに評価上は
    # 不明だった（設計レビューF1）。ロードバイクでは走行困難のためBADへ分類する。
    "rock",
    # 切り出していない粗い石畳。sett/cobblestoneと同等以下の走行性。
    "unhewn_cobblestone",
}


def classify_osm_surface(surface_tag: str | None) -> bool | None:
    """OSMのsurfaceタグから、走行しやすい舗装路面かどうかを判定する。タグが無い/未知の場合はNone。"""
    if surface_tag is None:
        return None
    normalized = surface_tag.strip().lower()
    if normalized in GOOD_OSM_SURFACE_TAGS:
        return True
    if normalized in BAD_OSM_SURFACE_TAGS:
        return False
    return None
