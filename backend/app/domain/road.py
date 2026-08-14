# 路面評価の正準定義（両ルーティングエンジン共通）:
# 「走行しやすい舗装路面か」を 良い(True) / 悪い(False) / 不明(None) の3値で判定し、
# road_score（舗装率%）は判定できた区間だけを分母にする（不明=無視。不明を「悪い」扱いに
# しない）。全区間が不明ならNone。openrouteserviceの数値ID語彙（is_good_surface）と
# OSMタグ語彙（classify_osm_surface）のどちらから判定しても、この意味は共通とする。

# openrouteserviceのextra_info=surfaceが返す路面種別ID（Paved/Asphalt/Concrete/Paving Stones）。
# ロードバイクで走りやすい、舗装された滑らかな路面とみなす。OpenRouteServiceEngine専用
# （RoadGraphEngineは代わりにOSMタグ基準のclassify_osm_surfaceを使う）。
GOOD_SURFACE_IDS = {1, 3, 4, 14}

# openrouteserviceの路面種別ID 0 = Unknown（路面情報なし）。
# OSMタグ語彙の「タグ無し/未知のタグ」（classify_osm_surfaceがNoneを返すケース）に対応する。
UNKNOWN_SURFACE_ID = 0


def paved_percent(surface_summary: list[dict] | None) -> float | None:
    """区間ごとの路面種別内訳（{value, distance, amount}の配列）から、走行しやすい舗装路面の割合(%)を算出する。

    不明（Unknown、ID 0）の区間は分母から除外する（不明を「悪い路面」扱いにしない、
    冒頭の正準定義参照）。判定できる区間が1つも無ければNone。
    """
    if not surface_summary:
        return None
    known = sum(item["amount"] for item in surface_summary if item["value"] != UNKNOWN_SURFACE_ID)
    if known <= 0:
        return None
    good = sum(item["amount"] for item in surface_summary if item["value"] in GOOD_SURFACE_IDS)
    return round(good / known * 100, 1)


def surface_id_at_index(index: int, surface_values: list[list] | None) -> int | None:
    """openrouteserviceのextras.surface.values（[[start_idx, end_idx, surface_id], ...]）から、
    geometry上の指定インデックスが属する区間の路面種別IDを求める。該当区間が無ければNone。"""
    if not surface_values:
        return None
    for start, end, surface_id in surface_values:
        if start <= index <= end:
            return surface_id
    return None


def is_good_surface(surface_id: int | None) -> bool | None:
    """路面種別IDが走行しやすい舗装路面かどうかを判定する（GOOD_SURFACE_IDSと基準を統一）。

    ID 0（Unknown）はFalse（悪い）ではなくNone（不明）を返す。OSMタグ語彙の
    classify_osm_surfaceが未知タグにNoneを返すのと同じ扱いにし、不明な路面が
    難易度計算・road_scoreへ「悪い」として混入しないようにする（冒頭の正準定義参照）。
    """
    if surface_id is None or surface_id == UNKNOWN_SURFACE_ID:
        return None
    return surface_id in GOOD_SURFACE_IDS


# OSMのsurfaceタグ（自由記述に近い文字列）版。openrouteserviceの数値IDとは別の語彙のため、
# GOOD_SURFACE_IDSとは独立した基準として持つ（考え方は同じ: 走行しやすい舗装路面かどうか）。
GOOD_OSM_SURFACE_TAGS = {"asphalt", "paved", "concrete", "paving_stones", "concrete:plates", "concrete:lanes"}
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
