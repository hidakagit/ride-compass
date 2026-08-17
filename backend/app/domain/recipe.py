"""レシピ付き軸（`domain/traffic.py: traffic_stress_breakdown`・`domain/safety.py:
safety_breakdown`）が共有する判定プリミティブ（改善計画T122）。

両軸は「highway別基準値＋タグ由来の加減点＋クランプ」という同一の採点構造をパラメータだけ
変えて実装しており、この構造そのものをここへ切り出す。`*Recipe`モデル・`*_breakdown`関数・
APIの`*Override`モデル自体はフィールド集合が異なる（交通ストレス=lanes_low、安全度=lit/
tunnel）ため軸ごとに残し、無理に共通のPydanticモデルへは寄せない（採点構造だけを共通化する）。

タグの値パース（`parse_lanes`/`parse_maxspeed`）・cycleway系タグの分類（`cycleway_class`）は
どちらの軸からも同じ意味で参照される「材料タグの正規化」のため、traffic.pyから移設して
ここを正準1箇所にした（safety.pyがtraffic.py経由で間接importしていた旧構成を解消）。
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
    テストで担保）。traffic_stress_breakdown・safety_breakdownの両方がcycleway_adjustment
    経由でこの分類を使う。"""
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


def clamp_level(value: int, min_level: int, max_level: int) -> int:
    """basisと各補正の合計をmin_level〜max_levelの範囲へ丸める。"""
    return max(min_level, min(max_level, value))


def threshold_adjustment(
    value: int | None,
    low_threshold: int | None,
    low_adjustment: int,
    high_threshold: int | None,
    high_adjustment: int,
) -> int:
    """value（maxspeed/lanes等の数値材料タグ）が低い方の閾値以下/高い方の閾値以上の
    どちらに該当するかで補正値を返す（該当しなければ0）。

    low_threshold/high_thresholdはNoneなら「その方向の補正を持たない」ことを表す
    （安全度のlanesはhigh方向のみ採用し、交通ストレスのlanes_lowに相当する補正を
    持たない非対称な構造を、呼び出し側の条件分岐を増やさずに吸収するため）。

    low<highが常に成り立つ前提（`*Override` APIモデルの`model_validator`が
    `validate_threshold_order`で検証済み）。この前提の下では2条件は排他的なので、
    どちらを先に判定しても結果は同じになる（旧traffic.pyのlanesはhigh優先、
    maxspeedはlow優先で実装が割れていたが、この前提のため常に同値だった）。
    """
    if value is None:
        return 0
    if low_threshold is not None and value <= low_threshold:
        return low_adjustment
    if high_threshold is not None and value >= high_threshold:
        return high_adjustment
    return 0


def cycleway_adjustment(tags: dict[str, str], track_adjustment: int, lane_adjustment: int, shared_adjustment: int) -> int:
    """cycleway系タグの分類（`cycleway_class`）に応じた補正値を返す。"""
    match cycleway_class(tags):
        case "track":
            return track_adjustment
        case "lane":
            return lane_adjustment
        case "shared":
            return shared_adjustment
        case _:
            return 0


def flag_adjustment(is_present: bool, adjustment: int) -> int:
    """is_presentがTrueならadjustmentを、Falseなら0を返す。「タグ有無→±N」という構造の
    補正パターンに共通（lit/tunnel/designation等）。呼び出し側が`tag_value_is`等で
    条件を作ってから渡す（このプリミティブ自体はタグの中身を知らない）。"""
    return adjustment if is_present else 0


def validate_threshold_order(low: int, high: int, label: str) -> None:
    """low<highでなければValueErrorを送出する。`*Override` APIモデルの`model_validator`
    から呼ぶ共通の閾値順序検証（改善計画T121-a: TrafficStressRecipeOverrideにだけ
    存在しSafetyRecipeOverrideには無い、という「片方だけ直し忘れる」非対称の再発防止）。

    low>=highだと、`threshold_adjustment`の2条件（value<=low・value>=high）が排他的で
    なくなり、どちらの分岐を先に評価するかによって結果が変わってしまう
    （＝レシピとして意味を持たなくなる）。
    """
    if low >= high:
        raise ValueError(f"{label}_low_threshold must be less than {label}_high_threshold")
