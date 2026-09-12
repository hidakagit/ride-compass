import math
from collections import defaultdict

from typing import Callable

from pydantic import Field

from app.domain.difficulty import distance_weighted_difficulty, weighted_mean_by_distance
from app.domain.strict_model import StrictModel


class Coordinates(StrictModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RouteSegment(StrictModel):
    distance_km: float
    duration_minutes: float
    geometry: dict


class RouteSegmentDetail(StrictModel):
    """周回ルートの1区間（サンプル点i→i+1）の詳細。地図上の難易度レイヤー描画に使う。

    符号付き材料（`material_values`に入る`gradient_percent`等）の正準定義:
    **符号付き・進行方向基準**（登り=正、下り=負、ElevationAttribute.average_gradeから
    算出）。フロントの勾配色分け（routeStyleModes.ts）はこの符号を前提に「下り」
    カテゴリを持つため、絶対値で返してはならない。

    geometryはこの区間が実際に通る道なり形状（GeoJSON LineString、ルート全体geometryの
    部分列）。地図の区間色分けを道路形状に沿って描くために使う。フロントは
    geometryがnullの場合のみ始点・終点の直線で代替描画する（MapView.tsx:
    segmentsToFeatureCollection）。
    """

    geometry: dict | None = None
    start_latitude: float
    start_longitude: float
    end_latitude: float
    end_longitude: float
    cumulative_distance_km: float
    distance_km: float
    estimated_arrival_time: str | None = None
    # axis_id→difficulty(0-100)の汎用dict。軸スタジオで公開軸を自由に増減できる設計と
    # 整合するよう固定フィールドにはしない。評価できなかった軸（欠損データ等）は
    # キー自体を含めない（`compute_edge_axis_scores`・`evaluate_axis_difficulties`と
    # 同じ「データ無しはキーを持たない」規約）。
    axis_difficulties: dict[str, float] = Field(default_factory=dict)
    # 「重み付き寄与度」（この区間の合成に使ったのと同じ重み配分で
    # axis_id別に分解した値、`arr*weight/weighted_weight_sums`）。axis_difficultiesと
    # 同じ「データ無しはキーを持たない」規約。全軸のこの値を合計すると
    # difficulty（丸め前）と一致する——frontendが「重み付き寄与度」内訳を独自
    # 再計算せず表示するために使う（domain/evaluation.py: compose_costs_from_axis_matrix
    # 参照）。
    axis_contributions: dict[str, float] = Field(default_factory=dict)
    # 重み>0の公開軸が参照する材料id→値の汎用辞書（`AXIS_DEFINITIONS`の`materials`
    # プロパティから導出、軸名のハードコード無し）。axis_difficultiesと同じ
    # 「値が無い材料はキーを持たない」規約。評価に使っていない軸の材料は出ない。
    material_values: dict[str, float] = Field(default_factory=dict)
    # categorical材料id→この区間の値（例: highway→"residential"）。数値の
    # `material_values`と同じ材料の内訳（docs/tasks/T689.md）だが、値が文字列のため器を
    # 分ける。ルート集約では距離加重で「値ごとの延長割合」へ畳む
    # （`merge_material_category_shares`）。
    material_categories: dict[str, str] = Field(default_factory=dict)
    # axis_id→折れ点を通す前の生値。単位が定まる軸だけが持つ（`axis_display.py:
    # raw_value_unit`）。得点（0-100）は目盛りの引き方に依存する相対評価のため、軸単体で
    # 経路を判断するにはこの絶対値が要る。axis_difficultiesと同じ「データ無しはキーを
    # 持たない」規約。
    axis_raw_values: dict[str, float] = Field(default_factory=dict)
    difficulty: float | None = None


class RouteCandidate(StrictModel):
    """`overall_difficulty`: segmentsの`difficulty`（絶対基準0-100）の距離加重平均
    （domain/difficulty.py: distance_weighted_difficulty）。異なる実験（重み・条件）間の
    比較にも使える絶対基準（研究インターフェース改善 §10-7）。候補タブの並び順は
    この値の昇順で決まる（route_generator.py参照）。
    segments欠損時・全区間difficulty欠損時はNone。

    `axis_difficulties`: `RouteSegmentDetail.axis_difficulties`と同じ
    axis_id→difficulty(0-100)の汎用dictを、ルート全区間に対して1回だけ集約したもの
    （`merge_axis_difficulties`を`aggregate_segments_into_bins`のビン単位ではなく
    候補全体へ適用）。軸スタジオでの軸増減に自動追従する（BottomSheetのルート
    全体プロファイル等が使う）。評価できなかった軸はキー自体を含めない（segments欠損時は
    空dict）。
    """

    id: str
    direction_label: str
    distance_km: float
    geometry: dict
    elevation_gain_m: float | None = None
    min_elevation_m: float | None = None
    max_elevation_m: float | None = None
    segments: list[RouteSegmentDetail] | None = None
    overall_difficulty: float | None = None
    # 難易度の総量（`overall_difficulty` × 距離km、domain/difficulty.py: difficulty_load）。
    # 平均は距離で正規化されるため遠回りするほど下がるのに対し、総量は距離が伸びれば
    # そのまま増える。候補の順位付けには使わず（並び順は`overall_difficulty`昇順のまま）、
    # 「長い分だけ疲れる」を平均と併せて読み取るための判断材料として持つ。
    difficulty_load: float | None = None
    axis_difficulties: dict[str, float] = Field(default_factory=dict)
    # `RouteSegmentDetail.axis_contributions`をルート全区間へ距離加重平均で
    # 集約したもの（`merge_axis_contributions`、`axis_difficulties`と同じ集約方法）。
    # 合計は丸め誤差を除いて`overall_difficulty`と一致する（`route_generator.py:
    # _with_axis_contributions`が付与する）。フロントの「内訳（重み付き寄与度）」表示は
    # このフィールドをそのまま使い、ルート設定の重みを使った独自再計算はしない。
    axis_contributions: dict[str, float] = Field(default_factory=dict)
    # `RouteSegmentDetail.axis_raw_values`をルート全区間へ距離加重平均で集約したもの
    # （`merge_axis_raw_values`）。単位は`GET /api/axis-catalog`の`raw_value_unit`が持ち、
    # 「◯◯/km」なら走行距離を掛けて経路全体の実数（例: 止まる回数）にできる。
    axis_raw_values: dict[str, float] = Field(default_factory=dict)
    # `RouteSegmentDetail.material_values`を候補全区間へ距離加重平均で集約したもの
    # （`merge_material_values`、`axis_difficulties`と同じ集約方法）。
    material_values: dict[str, float] = Field(default_factory=dict)
    # categorical材料id→{値: その値が占める延長割合(0〜1)}。
    # `RouteSegmentDetail.material_categories`を距離加重で畳んだもの
    # （`merge_material_category_shares`）。合成軸の内訳のうち、数値として平均できない
    # 材料をこちらで出す。
    material_category_shares: dict[str, dict[str, float]] = Field(default_factory=dict)
    # 経路を構成するEdge idの列（起点から順）。フロントは候補どうしの共通部分を集合演算で
    # 求め、別の道を通る区間を出すのに使う（区間の乗り換え、docs/tasks/T621.md）。
    # backendはステートレスのため、乗り換え後の経路もこのidの列で受け取って評価し直す。
    # エンジンが経路をEdgeの列として持たない場合は空のまま。
    edge_ids: list[str] = Field(default_factory=list)
    # `geometry.coordinates`におけるEdgeの境界点の位置（`edge_ids`より1件多い）。
    # 隣接Edgeの境界点は重複させずに連結するため、座標列だけからはEdgeの境目を復元
    # できない。Edge単位で決めた区間を地図へ帯として描くのに使う
    # （`coordinates[offsets[i]:offsets[j] + 1]`がEdge i〜j-1の形状）。
    edge_point_offsets: list[int] = Field(default_factory=list)
    # 距離だけで選んだ最短経路か（目的地モードのみ。周回は目標距離が距離を決めるため常にFalse）。
    # フロントはこの候補の`distance_km`を基準に、他の候補が何km余分に走るかを出す。
    # 軸設定に沿った候補と最短経路が同じ経路になることもあるため、複数の候補が同時に
    # Trueになることは無い代わりに、1本もTrueが無い場合（最短経路を求められなかった）もある。
    is_shortest_distance: bool = False


# road_graphエンジンのsegmentsはEdge単位（交差点間、1候補あたり150〜230件、30km級）で
# APIペイロード・フロント描画コストが嵩むため、約500m単位に集約してから返す。
SEGMENT_BIN_DISTANCE_KM = 0.5


def aggregate_segments_into_bins(
    segments: list[RouteSegmentDetail], bin_distance_km: float = SEGMENT_BIN_DISTANCE_KM
) -> list[RouteSegmentDetail]:
    """連続するEdge単位の`RouteSegmentDetail`を、累積距離`bin_distance_km`単位で
    グルーピングし、1ビン1件の`RouteSegmentDetail`へ集約する。

    集約方法（フィールドの性質ごと）:
    - 距離加重平均: 各difficulty系（domain/difficulty.py: distance_weighted_difficulty、
      Noneの区間は除外し残りの距離で再正規化）・material_values（material_id単位で同じ
      考え方、`merge_material_values`）
    - 先頭からの引き継ぎ: cumulative_distance_km/estimated_arrival_time/
      start_latitude/start_longitude（ビン開始時点の値）
    - 末尾からの引き継ぎ: end_latitude/end_longitude（ビン終了時点の値）
    - 合計: distance_km
    - 連結: geometry（ビン内の全形状点を、隣接区間の境界点を重複させずに連結）

    最後のビンは`bin_distance_km`未満でも単独のビンとして残す（経路全体の距離を
    正しく合計するため、切り捨てや次ビンへの繰り越しはしない）。`segments`が空なら
    空リストを返す。既存の`RouteSegmentDetail`型のまま返すため、OpenAPI契約・
    フロント型への影響が無い設計（フロントは単にEdge単位からビン単位へ粒度が変わる
    だけで、型自体は変わらない）。
    """
    if not segments:
        return []

    bins: list[list[RouteSegmentDetail]] = []
    current_bin: list[RouteSegmentDetail] = []
    current_bin_distance = 0.0
    for segment in segments:
        current_bin.append(segment)
        current_bin_distance += segment.distance_km
        if current_bin_distance >= bin_distance_km:
            bins.append(current_bin)
            current_bin = []
            current_bin_distance = 0.0
    if current_bin:
        bins.append(current_bin)

    return [_merge_segment_bin(bin_segments) for bin_segments in bins]


def _concat_segment_geometries(segments: list[RouteSegmentDetail]) -> dict | None:
    coordinates: list[list[float]] = []
    for segment in segments:
        if segment.geometry is None:
            continue
        points = segment.geometry["coordinates"]
        if coordinates and points and coordinates[-1] == points[0]:
            points = points[1:]
        coordinates.extend(points)
    if len(coordinates) < 2:
        return None
    return {"type": "LineString", "coordinates": coordinates}


def _round_significant(value: float, digits: int = 4) -> float:
    """有効数字`digits`桁へ丸める（値のスケールに依存しない丸め）。

    0〜100のdifficultyと違い、物理量の生値・材料値はスケールが軸ごとに違う
    （事故密度は`件/(km・年)`で有効域0〜0.5、勾配は`%`で0〜15程度）。
    固定の小数桁で丸めると、桁の小さい軸で値がまるごと潰れる。
    """
    if value == 0.0 or not math.isfinite(value):
        return value
    return round(value, -int(math.floor(math.log10(abs(value)))) + (digits - 1))


def _merge_axis_value_dict(
    segments: list[RouteSegmentDetail],
    field_getter: Callable[[RouteSegmentDetail], dict[str, float]],
    round_value: Callable[[float], float] = lambda v: round(v, 1),
) -> dict[str, float]:
    """複数の`RouteSegmentDetail`が持つキー→float辞書（`field_getter`で指定）を、
    キーごとに距離加重平均へ集約する共通ロジック（`merge_axis_difficulties`/
    `merge_axis_contributions`/`merge_axis_raw_values`/`merge_material_values`の共有実装）。
    渡されたsegments群のどの区間にも無いキーは結果にも含めない
    （各フィールド共通の「データ無しはキーを持たない」規約）。

    `round_value`は集約後の丸め方。**0〜100のdifficulty系と、スケールが軸ごとに違う
    物理量（生値・材料値）とで必要な粒度が違う**ため、呼び出し側が指定する。
    """
    axis_ids = {axis_id for s in segments for axis_id in field_getter(s)}
    merged: dict[str, float] = {}
    for axis_id in axis_ids:
        value = weighted_mean_by_distance(
            [(field_getter(s).get(axis_id), s.distance_km) for s in segments]
        )
        if value is not None:
            merged[axis_id] = round_value(value)
    return merged


def merge_axis_difficulties(segments: list[RouteSegmentDetail]) -> dict[str, float]:
    """`RouteSegmentDetail.axis_difficulties`をaxis_idごとに距離加重平均へ集約する。
    `_merge_segment_bin`がビン単位（500m）の集約に使うほか、
    `RouteCandidate.axis_difficulties`はこの関数を候補の全区間へ1回
    適用するだけで得られる（新しい計算式は不要、`route_generator.py`参照）。
    """
    return _merge_axis_value_dict(segments, lambda s: s.axis_difficulties)


def merge_axis_raw_values(segments: list[RouteSegmentDetail]) -> dict[str, float]:
    """`RouteSegmentDetail.axis_raw_values`をaxis_idごとに距離加重平均へ集約する
    （`merge_axis_difficulties`と同じ集約方法）。単位が「◯◯/km」の軸なら、この値へ
    走行距離を掛けると経路全体での実数（例: 止まる回数）になる。"""
    return _merge_axis_value_dict(segments, lambda s: s.axis_raw_values, _round_significant)


def merge_axis_contributions(segments: list[RouteSegmentDetail]) -> dict[str, float]:
    """`RouteSegmentDetail.axis_contributions`（「重み付き寄与度」）を
    axis_idごとに距離加重平均へ集約する。`merge_axis_difficulties`と同じ集約方法
    （`_merge_axis_value_dict`共有実装）。`_merge_segment_bin`のビン単位集約、
    `RouteCandidate.axis_contributions`（`route_generator.py:
    _with_axis_contributions`）の両方が使う。
    """
    return _merge_axis_value_dict(segments, lambda s: s.axis_contributions)


def merge_material_values(segments: list[RouteSegmentDetail]) -> dict[str, float]:
    """`RouteSegmentDetail.material_values`を材料idごとに距離加重平均へ集約する。
    `merge_axis_difficulties`と同じ集約方法（`_merge_axis_value_dict`共有実装）。
    """
    return _merge_axis_value_dict(segments, lambda s: s.material_values, _round_significant)


def merge_material_category_shares(segments: list[RouteSegmentDetail]) -> dict[str, dict[str, float]]:
    """`RouteSegmentDetail.material_categories`を材料idごとに「値→延長割合」へ畳む。

    数値材料の`merge_material_values`（距離加重平均）に対応するcategorical版。真偽値材料を
    0/1で運んで平均が割合になるのと同じ考え方を、値が3つ以上ある材料へ広げたもの。
    分母はその材料の値を持つ区間の距離合計で、値の無い区間は分母にも入れない
    （「観測できた範囲でどの値が多いか」を表す）。
    """
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for segment in segments:
        distance_km = segment.distance_km or 0.0
        if distance_km <= 0:
            continue
        for material_id, value in segment.material_categories.items():
            totals[material_id][value] += distance_km
    shares: dict[str, dict[str, float]] = {}
    for material_id, by_value in totals.items():
        total = sum(by_value.values())
        if total <= 0:
            continue
        shares[material_id] = {
            value: round(distance / total, 4)
            for value, distance in sorted(by_value.items(), key=lambda item: (-item[1], item[0]))
        }
    return shares


# ビンへ畳むときに引き継がない辞書フィールドと、その理由。
# `tests/test_route.py`がモデル側から辞書フィールドを引き、この宣言に無いものが
# 落ちていないかを検査する（足し忘れは型でも例外でも現れないため）。
BIN_DROPPED_DICT_FIELDS: dict[str, str] = {
    # categorical材料は平均できず、ビンの代表値を1つ選ぶと延長割合が500m単位へ量子化される。
    # ルート全体の割合（`RouteCandidate.material_category_shares`）はEdge単位のsegmentsから
    # 畳む必要があるため、`road_graph_engine`がビニングの前に計算する。区間単位の値には
    # 消費者がいない。
    "material_categories": "ビン代表値では延長割合が歪むため、ビニング前に候補全体の割合へ畳む",
}


def _merge_segment_bin(segments: list[RouteSegmentDetail]) -> RouteSegmentDetail:
    first, last = segments[0], segments[-1]
    return RouteSegmentDetail(
        geometry=_concat_segment_geometries(segments),
        start_latitude=first.start_latitude,
        start_longitude=first.start_longitude,
        end_latitude=last.end_latitude,
        end_longitude=last.end_longitude,
        cumulative_distance_km=first.cumulative_distance_km,
        distance_km=round(sum(s.distance_km for s in segments), 2),
        estimated_arrival_time=first.estimated_arrival_time,
        axis_difficulties=merge_axis_difficulties(segments),
        axis_contributions=merge_axis_contributions(segments),
        axis_raw_values=merge_axis_raw_values(segments),
        material_values=merge_material_values(segments),
        difficulty=distance_weighted_difficulty([(s.difficulty, s.distance_km) for s in segments]),
    )
