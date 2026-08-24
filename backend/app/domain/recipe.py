"""タグ由来の材料タグを正規化する純関数群（改善計画T122）。

タグの値パース（`parse_lanes`/`parse_maxspeed`）・cycleway系タグの分類（`cycleway_class`）・
タグ値の真偽判定（`tag_value_is`）を「材料タグの正規化」としてここを正準1箇所にしている。
複数のevaluationパイプライン（domain/evaluation.py・domain/traffic.py・
services/openrouteservice_engine.py）が同じ関数を参照する。

改善計画T292: 旧`RoadSuitabilityRecipe`・`MotorVehicleDensityRecipe`・`car_closeness`・
`road_suitability`・`cycleway_adjustment`・`threshold_adjustment`・`clamp_level`・
`flag_adjustment`・`validate_threshold_order`（highway別基準値＋タグ由来の加減点＋クランプ
という「専用Pythonレシピ」の採点構造、および`domain/traffic.py: car_stress_breakdown`等の
呼び出し元）は、car_stress軸をAXIS_DEFINITIONSの内部軸5つ+公開軸1つの階層構造で再現する
よう再設計したことに伴い削除した。
"""


def parse_lanes(tags: dict[str, str]) -> int | None:
    """lanesタグを正の整数へ変換する。表記ゆれ（小数点混じり等）は緩く許容し、
    パース不能・0以下はNone。"""
    raw = tags.get("lanes")
    if raw is None:
        return None
    try:
        value = int(float(raw.strip()))
    except ValueError:
        return None
    return value if value > 0 else None


def parse_maxspeed(tags: dict[str, str]) -> int | None:
    """maxspeedタグを正の整数(km/h)へ変換する。日本のOSMはkm/h数値表記が主のため、
    "50 mph"のような単位付き表記はパース対象外としNoneを返す（unknown安全。
    誤った単位変換で実際より安全側/危険側の値を作らないため）。"""
    raw = tags.get("maxspeed")
    if raw is None:
        return None
    cleaned = raw.strip().lower()
    if not cleaned or not cleaned.replace(".", "", 1).isdigit():
        return None
    value = int(float(cleaned))
    return value if value > 0 else None


def cycleway_values(tags: dict[str, str]) -> list[str]:
    """cycleway/cycleway:left/cycleway:right/cycleway:bothのうち設定済みの値を集める
    （left/right統合の正規化）。"""
    keys = ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")
    return [tags[k].strip().lower() for k in keys if tags.get(k)]


def cycleway_class(tags: dict[str, str]) -> str | None:
    """cycleway系タグの3分類（'track'|'lane'|'shared'|None）。road_graph_repository.py:
    _ROAD_SURFACE_TILE_MVT_SQLが焼き込む`cycleway_class`タイルプロパティと同じ判定基準
    （正準はこちら、SQL側はCASE式で1:1対応させ、test_road_graph_repository.pyの整合性
    テストで担保）。"""
    values = cycleway_values(tags)
    if "track" in values:
        return "track"
    if "lane" in values:
        return "lane"
    if any(v in ("shared_lane", "share_busway") for v in values):
        return "shared"
    return None


def tag_value_is(tags: dict[str, str], key: str, expected: str) -> bool:
    """タグの値が`expected`（大文字小文字・前後空白を許容）と一致するかどうか。
    motor_vehicle=no・lit/tunnel=yesのような「タグ有無・タグ値の正規化」に共通する判定。"""
    return (tags.get(key) or "").strip().lower() == expected
