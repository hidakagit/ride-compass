"""タグ由来の材料タグを正規化する純関数群（改善計画T122）。

タグの値パース（`parse_lanes`/`parse_maxspeed`）・cycleway系タグの集約（`cycleway_values`）・
タグ値の真偽判定（`tag_value_is`）を「材料タグの正規化」としてここを正準1箇所にしている。
複数のevaluationパイプライン（domain/evaluation.py・domain/traffic.py）が同じ関数を参照する。

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


def tag_value_is(tags: dict[str, str], key: str, expected: str) -> bool:
    """タグの値が`expected`（大文字小文字・前後空白を許容）と一致するかどうか。
    motor_vehicle=no・lit/tunnel=yesのような「タグ有無・タグ値の正規化」に共通する判定。"""
    return (tags.get(key) or "").strip().lower() == expected


def bicycle_infra_flags(tags: dict[str, str], highway: str | None) -> dict[str, bool]:
    """改善計画T336: `domain/material_catalog.py`のhighway_is_cycleway/cycleway_has_track/
    cycleway_has_lane/cycleway_has_shared材料（正規化フラグ材料id→真偽値）と同じキーを
    まとめて返す。`domain/evaluation.py: axis_inspector_breakdown`/`compute_edge_axis_scores`が
    手組みするmaterials辞書へそのまま`**bicycle_infra_flags(tags, highway)`で混ぜ込める
    （bicycle_infra[classify_bicycle_infrastructure]と同じ材料抽出を1箇所にまとめ、
    複数箇所への手書き複製を避ける）。

    改善計画T359: `shared_pedestrian_path`は、河川敷サイクリングロード等
    「highway=footway/pathかつbicycle=yes/designated（自転車通行可の歩行者道）」という
    別のOSMタグパターンを検知する（王子-荒川ルート調査で発覚、highway=cycleway/track等の
    車道併設インフラとは別に、車道から完全分離された共用道を拾えていなかった）。
    """
    values = cycleway_values(tags)
    return {
        "highway_is_cycleway": highway == "cycleway",
        "cycleway_has_track": "track" in values,
        "cycleway_has_lane": "lane" in values,
        "cycleway_has_shared": any(v in ("share_busway", "shared_lane") for v in values),
        "shared_pedestrian_path": highway in ("footway", "path") and tags.get("bicycle") in ("yes", "designated"),
    }


def bicycle_infra_flags_or_none(tags: dict[str, str] | None, highway: str | None) -> dict[str, bool] | None:
    """改善計画T347フォローアップ: `bicycle_infra_flags`を「データ欠損はNone」の規約に
    倒すラッパー。呼び出し元（material_catalog.pyのextractor・evaluation.py:
    compute_edge_axis_scores・road_graph_engine.pyの_build_segment_details）が
    同じガード条件を複数箇所で手書きしていたため、旧classify_bicycle_infrastructureが
    実際に持っていた「unknown」判定条件をここへ1箇所へ集約する（設計原則1: 正準定義は1箇所）。

    `tags is None`（タグ自体が未取得）はNone。`bicycle_infra_flags`自体はhighway=Noneでも
    例外を投げず具体的なbool値を返してしまうが、素朴に`highway is None`だけをNoneへ倒すと、
    旧関数が実際には許していた「highwayは不明だがcyclewayタグから分離自転車道と判定できる」
    ケース（`highway == "cycleway" or "track" in values`をhighwayの有無より先に判定していた
    ため、cyclewayタグさえあればhighwayがNoneでも判定できた）まで誤ってNoneに倒してしまう。
    旧関数が本当にunknownを返していたのは「highwayも解決できず、かつcycleway由来の
    いずれのフラグも立たない」場合のみ（最終catch-all）なので、フラグ計算後にその条件
    （highway=None かつ 全フラグFalse）でだけNoneへ倒す。
    """
    if tags is None:
        return None
    flags = bicycle_infra_flags(tags, highway)
    if highway is None and not any(flags.values()):
        return None
    return flags
