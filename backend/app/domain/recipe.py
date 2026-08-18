"""レシピ付き軸（`domain/traffic.py: car_stress_breakdown`・`domain/safety.py:
safety_breakdown`）が共有する判定プリミティブ（改善計画T122）。

両軸は「highway別基準値＋タグ由来の加減点＋クランプ」という同一の採点構造をパラメータだけ
変えて実装しており、この構造そのものをここへ切り出す。`*Recipe`モデル・`*_breakdown`関数・
APIの`*Override`モデル自体はフィールド集合が異なる（車ストレス=lanes_low、安全度=lit/
tunnel）ため軸ごとに残し、無理に共通のPydanticモデルへは寄せない（採点構造だけを共通化する）。

タグの値パース（`parse_lanes`/`parse_maxspeed`）・cycleway系タグの分類（`cycleway_class`）は
どちらの軸からも同じ意味で参照される「材料タグの正規化」のため、traffic.pyから移設して
ここを正準1箇所にした（safety.pyがtraffic.py経由で間接importしていた旧構成を解消）。

`RoadSuitabilityRecipe`（道路適正）・`MotorVehicleDensityRecipe`（自動車密度）は、
車ストレス・安全度の両方が共通の土台として参照する「車との近さ」（N2 =
道路適正＋自動車密度）を構成する2つの独立したレシピ（改善計画: 車との近さ材料の
共有元化）。値そのものが両軸で一致していたため（living_street基準値の統一で確定）、
`*Recipe`モデルの一部としてではなく独立したレシピとして切り出し、研究モードでも
1箇所の上書きが両軸へ反映されるようにした。`car_closeness()`がこの2つを合成する。
"""

from pydantic import BaseModel, Field


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
    テストで担保）。car_stress_breakdown・safety_breakdownの両方がcycleway_adjustment
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
    （安全度のlanesはhigh方向のみ採用し、車ストレスのlanes_lowに相当する補正を
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


def road_suitability(
    highway: str | None,
    tags: dict[str, str],
    base_by_highway: dict[str, int],
    track_adjustment: int,
    lane_adjustment: int,
    shared_adjustment: int,
) -> tuple[int | None, int]:
    """「道路適正」（highway別基準値＋cycleway分離度）を1組で返す。車との近さ系の軸
    （車ストレス・安全度）が共通して最初に評価する材料で、両軸のbase_by_highway・
    cycleway系補正量は既定値が一致している（改善計画: 車との近さ材料の共有元化）。

    それでも`*Recipe`モデル自体は軸ごとに独立させたまま（研究モードでの上書きは
    軸単位、片方を変えてももう片方に影響しない）にする。ここが1箇所にまとまるのは
    「highwayからbaseを引いてcyclewayを足す」という手順そのもので、値の出どころ
    （各軸のrecipe）は呼び出し側が渡す。

    base_by_highwayに未登録のhighwayは(None, 0)を返す（*_breakdownの早期リターン判定用、
    cycleway補正は意味を持たないため0で揃える）。
    """
    base = base_by_highway.get(highway or "")
    if base is None:
        return None, 0
    cycleway_adj = cycleway_adjustment(tags, track_adjustment, lane_adjustment, shared_adjustment)
    return base, cycleway_adj


# highway別基準値（12区分）。旧`TRAFFIC_STRESS_BASE_BY_HIGHWAY`/`SAFETY_BASE_BY_HIGHWAY`は
# living_street基準値の統一（車ストレス側2→1）により完全に同一の値になったため、
# ここ1箇所へ統合した（改善計画: 車との近さ材料の共有元化）。
ROAD_SUITABILITY_BASE_BY_HIGHWAY: dict[str, int] = {
    "cycleway": 1,
    "living_street": 1,
    "residential": 2,
    "unclassified": 2,
    "track": 2,
    "tertiary": 3,
    "tertiary_link": 3,
    "secondary": 3,
    "secondary_link": 3,
    "primary": 4,
    "primary_link": 4,
    "trunk": 4,
    "trunk_link": 4,
}


class RoadSuitabilityRecipe(BaseModel):
    """「道路適正」（N1 = highway別基準値＋cycleway分離度）のレシピ。車ストレス・
    安全度の両方が`road_suitability()`経由で参照する共通の土台で、軸固有のレシピ
    （`CarStressRecipe`/`SafetyRecipe`）とは独立して研究モードで上書きできる
    （改善計画: 車との近さ材料の共有元化）。
    """

    base_by_highway: dict[str, int] = Field(default_factory=lambda: dict(ROAD_SUITABILITY_BASE_BY_HIGHWAY))
    cycleway_track_adjustment: int = -2
    cycleway_lane_adjustment: int = -1
    cycleway_shared_adjustment: int = -1


DEFAULT_ROAD_SUITABILITY_RECIPE = RoadSuitabilityRecipe()


class MotorVehicleDensityRecipe(BaseModel):
    """「自動車密度」（制限速度・車線数[多い方]・指定路線該当）のレシピ。`RoadSuitabilityRecipe`
    と合わせて「車との近さ」（N2）を構成する、車ストレス・安全度が共通で参照する
    もう1つの土台（改善計画: 車との近さ材料の共有元化）。
    """

    maxspeed_low_threshold: int = 30
    maxspeed_low_adjustment: int = -1
    maxspeed_high_threshold: int = 60
    maxspeed_high_adjustment: int = 1
    lanes_high_threshold: int = 4
    lanes_high_adjustment: int = 1
    designation_adjustment: int = 1


DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE = MotorVehicleDensityRecipe()


def flag_adjustment(is_present: bool, adjustment: int) -> int:
    """is_presentがTrueならadjustmentを、Falseなら0を返す。「タグ有無→±N」という構造の
    補正パターンに共通（lit/tunnel/designation等）。呼び出し側が`tag_value_is`等で
    条件を作ってから渡す（このプリミティブ自体はタグの中身を知らない）。"""
    return adjustment if is_present else 0


def car_closeness(
    highway: str | None,
    tags: dict[str, str],
    is_designated: bool,
    road_suitability_recipe: RoadSuitabilityRecipe,
    motor_vehicle_density_recipe: MotorVehicleDensityRecipe,
) -> tuple[int | None, int, int, int, int]:
    """「車との近さ」（N2 = 道路適正＋自動車密度）を1組で返す。車ストレス・安全度の
    両方が共通の土台として評価する材料で、軸固有の補正（車ストレス: 車線数[少ない方]、
    安全度: 街灯・トンネル）はこの結果に呼び出し側が追加する（改善計画: 車との近さ材料の
    共有元化）。

    戻り値は`(base, cycleway_adj, maxspeed_adj, lanes_high_adj, designation_adj)`。
    highway未登録時は`(None, 0, 0, 0, 0)`（`road_suitability()`と同じ「早期リターン判定用」
    の約束）。
    """
    base, cycleway_adj = road_suitability(
        highway,
        tags,
        road_suitability_recipe.base_by_highway,
        road_suitability_recipe.cycleway_track_adjustment,
        road_suitability_recipe.cycleway_lane_adjustment,
        road_suitability_recipe.cycleway_shared_adjustment,
    )
    if base is None:
        return None, 0, 0, 0, 0
    maxspeed_adj = threshold_adjustment(
        parse_maxspeed(tags),
        motor_vehicle_density_recipe.maxspeed_low_threshold,
        motor_vehicle_density_recipe.maxspeed_low_adjustment,
        motor_vehicle_density_recipe.maxspeed_high_threshold,
        motor_vehicle_density_recipe.maxspeed_high_adjustment,
    )
    lanes_high_adj = threshold_adjustment(
        parse_lanes(tags),
        None,
        0,
        motor_vehicle_density_recipe.lanes_high_threshold,
        motor_vehicle_density_recipe.lanes_high_adjustment,
    )
    designation_adj = flag_adjustment(is_designated, motor_vehicle_density_recipe.designation_adjustment)
    return base, cycleway_adj, maxspeed_adj, lanes_high_adj, designation_adj


def validate_threshold_order(low: int, high: int, label: str) -> None:
    """low<highでなければValueErrorを送出する。`*Override` APIモデルの`model_validator`
    から呼ぶ共通の閾値順序検証（改善計画T121-a: CarStressRecipeOverrideにだけ
    存在しSafetyRecipeOverrideには無い、という「片方だけ直し忘れる」非対称の再発防止）。

    low>=highだと、`threshold_adjustment`の2条件（value<=low・value>=high）が排他的で
    なくなり、どちらの分岐を先に評価するかによって結果が変わってしまう
    （＝レシピとして意味を持たなくなる）。
    """
    if low >= high:
        raise ValueError(f"{label}_low_threshold must be less than {label}_high_threshold")
