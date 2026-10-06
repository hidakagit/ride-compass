import math
from collections import defaultdict

from typing import Annotated, Any, Callable, Iterable, Literal, Mapping, TypeVar

from pydantic import Field, WithJsonSchema

from app.domain.difficulty import (
    OverallDifficulty,
    distance_weighted_difficulty,
    round_difficulty,
    weighted_mean_by_distance,
)
from app.domain.geo import Latitude, Longitude
from app.domain.strict_model import StrictModel


# GeoJSONのLineString（座標は[経度, 緯度]）。契約には形を載せるが、検証はしない——数千点の座標を
# 組み立てのたびにたどることになる。形は組み立てる側（`_concat_segment_geometries`・
# `services/road_graph_engine.py: concat_edge_geometries`等）が決める。
LineStringGeometry = Annotated[
    dict[str, Any],
    WithJsonSchema(
        {
            "type": "object",
            "properties": {
                "type": {"const": "LineString", "type": "string"},
                "coordinates": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
            },
            "required": ["type", "coordinates"],
        }
    ),
]


class Coordinates(StrictModel):
    latitude: Latitude
    longitude: Longitude


class SegmentWind(StrictModel):
    """区間の評価に使った風。

    `forecast_at`はその予報の時刻（JSTのローカル時刻、分まで）。風の時別予報が無く出発時点の
    値を使ったときはNone。`extended`は、予報を追える範囲（レグごとの時刻ビンの本数・予報の期間）の
    先で、最後に追った時刻の予報をそのまま使った区間。
    """

    speed_ms: float
    direction_deg: float
    forecast_at: str | None = None
    extended: bool = False


class RouteSegmentDetail(StrictModel):
    """周回ルートの1区間（サンプル点i→i+1）の詳細。地図上の難易度レイヤー描画に使う。

    符号付き材料（`material_values`に入る`gradient_percent`等）は**符号付き・進行方向
    基準**（登り=正、下り=負）。フロントの勾配色分けはこの符号を前提に「下り」カテゴリを
    持つため、絶対値で返してはならない。

    geometryはこの区間が実際に通る道なり形状（GeoJSON LineString、ルート全体geometryの
    部分列）。フロントはこれがnullの場合のみ始点・終点の直線で代替描画する。
    """

    geometry: LineStringGeometry | None = None
    start_latitude: float
    start_longitude: float
    end_latitude: float
    end_longitude: float
    cumulative_distance_km: float
    distance_km: float
    estimated_arrival_time: str | None = None
    # axis_id→difficulty(0-100)。以降の辞書フィールドはすべて「データ無しはキーを
    # 持たない」規約で、評価できなかった軸・値の無い材料はキー自体を含めない。
    axis_difficulties: dict[str, float] = Field(default_factory=dict)
    # 「重み付き寄与度」＝この区間の合成に使ったのと同じ重み配分でaxis_id別に分解した値。
    # 全軸を合計するとdifficulty（丸め前）と一致するため、フロントは内訳を独自に
    # 再計算せずこれを表示する。
    axis_contributions: dict[str, float] = Field(default_factory=dict)
    # 重み>0の公開軸が参照する材料id→値。評価に使っていない軸の材料は出ない。
    material_values: dict[str, float] = Field(default_factory=dict)
    difficulty: float | None = None
    # この区間の評価に使った風（到達予想の時刻に通るとして引いた予報）。風を持たない生成ではNone。
    wind: SegmentWind | None = None


#: 候補の種類。周回（方位を持つ）・経由地（指定した経由地を順に通る1本。目的地の有無を問わない）・
#: 目的地（経由地の無い目的地への互いに異なる経路）・合成（区間を乗り換えて組み立てた経路）。
RouteKind = Literal["loop", "waypoints", "destination", "spliced"]


class RouteCandidate(StrictModel):
    """1本のルート候補。

    生成の応答は`overall_difficulty`の平均の昇順で候補を並べる。全区間のdifficultyが欠けていればNone。

    辞書フィールドは`RouteSegmentDetail`の同名フィールドを候補の全区間へ距離加重平均で
    集約したもので、「データ無しはキーを持たない」規約も引き継ぐ。
    """

    # 応答の中で一意のid・種類・名前・最速の印は、`services/route_generator.py: _label`だけが付ける。エンジンが
    # 組み立てる時点では並びも種類も決まっておらず、idと種類は既定のまま、名前は周回の方位だけを持つ。
    id: str = ""
    kind: RouteKind = "loop"
    direction_label: str
    # 所要時間だけで探した1本（基準線）。経由地の無い目的地の生成で、比べる相手があるときだけ1本に付く。
    # 画面はこの1本を一覧の「最速」に置き、時間の列の基準にする。
    is_fastest: bool = False
    distance_km: float
    geometry: LineStringGeometry
    elevation_gain_m: float | None = None
    segments: list[RouteSegmentDetail] = Field(default_factory=list)
    overall_difficulty: OverallDifficulty | None = None
    # 所要時間の見積もり（秒）。区間の走行時間（走行モデル: 巡航速度・勾配・風から求めた
    # 速度）＋停止の待ち＋ターンの待ち。経路の選び方には使っておらず、表示のためだけに持つ。
    estimated_duration_seconds: float | None = None
    # 所要時間の見積もりで風を使えなかった（風の予報が読めず、無風として計算した）。画面が利用者へ知らせる。
    wind_unavailable: bool = False
    # 所要時間の見積もりで、勾配か停止要因の件数の値が無く、既定（平地・待ち無し）で数えた区間の距離の割合（0〜1）。
    # 数えるのはビンへ畳む前のEdge単位。画面が「データの無い区間が◯%」と知らせる。区間が無ければNone。
    missing_travel_data_share: float | None = None
    axis_difficulties: dict[str, float] = Field(default_factory=dict)
    # 合計は丸め誤差を除いて`overall_difficulty`と一致する。フロントの「内訳（重み付き
    # 寄与度）」表示はこれをそのまま使い、ルート設定の重みを使った独自再計算はしない。
    axis_contributions: dict[str, float] = Field(default_factory=dict)
    # axis_id→折れ点を通す前の生値。単位が定まる軸だけが持つ。得点（0-100）は目盛りの
    # 引き方に依存する相対評価のため、軸単体で経路を判断するにはこの絶対値が要る。
    # 単位は`GET /api/axis-catalog`の`raw_value_unit`が持ち、「◯◯/km」なら走行距離を
    # 掛けて経路全体の実数（例: 止まる回数）にできる。区間の値は持たない（`route_axis_raw_values`）。
    axis_raw_values: dict[str, float] = Field(default_factory=dict)
    material_values: dict[str, float] = Field(default_factory=dict)
    # categorical材料id→{値: その値が占める延長割合(0〜1)}。平均できない材料の内訳。
    material_category_shares: dict[str, dict[str, float]] = Field(default_factory=dict)
    # 経路を構成するEdge idの列（起点から順）。フロントは候補どうしの共通部分を集合演算で
    # 求め、別の道を通る区間を出すのに使う（区間の乗り換え）。
    # backendはステートレスのため、乗り換え後の経路もこのidの列で受け取って評価し直す。
    # エンジンが経路をEdgeの列として持たない場合は空のまま。
    edge_ids: list[str] = Field(default_factory=list)
    # `geometry.coordinates`におけるEdgeの境界点の位置（`edge_ids`より1件多い）。
    # 隣接Edgeの境界点は重複させずに連結するため、座標列だけからはEdgeの境目を復元
    # できない。Edge単位で決めた区間を地図へ帯として描くのに使う
    # （`coordinates[offsets[i]:offsets[j] + 1]`がEdge i〜j-1の形状）。
    edge_point_offsets: list[int] = Field(default_factory=list)
    # 経路が通るNode idの列（起点から順。`edge_ids`より1件多く、`node_ids[i]`が
    # `edge_ids[i]`の始点、末尾が終点）。フロントは「候補どうしが同じ地点を通るか」を
    # これで判定する——座標の完全一致でも実質は一致するが、乗り換えを鎖で伸ばすほど
    # 「同じ地点」の判定が結果を左右するため、グラフが持つ同一性をそのまま渡す。
    # `edge_ids`が空の候補では空のまま。
    node_ids: list[str] = Field(default_factory=list)


# エンジンが返すsegmentsはEdge単位（交差点間）でAPIペイロード・フロント描画コストが
# 嵩むため、この距離単位へ集約してから返す。
SEGMENT_BIN_DISTANCE_KM = 0.5


def aggregate_segments_into_bins(segments: list[RouteSegmentDetail]) -> list[RouteSegmentDetail]:
    """連続するEdge単位の`RouteSegmentDetail`を、累積距離`SEGMENT_BIN_DISTANCE_KM`単位で
    グルーピングし、1ビン1件の`RouteSegmentDetail`へ集約する。

    値の性質ごとに畳み方が違う: difficulty系と材料値は距離加重平均（値がNoneの区間は
    除外し、残りの距離で再正規化）、位置はビンの始点・終点、距離は合計、geometryは
    隣接区間の境界点を重複させずに連結する。

    最後のビンは`SEGMENT_BIN_DISTANCE_KM`未満でも単独で残す（切り捨てると経路全体の距離が
    合わなくなる）。
    """
    return [_merge_segment_bin(bin_segments) for bin_segments in _split_into_bins(segments, lambda s: s.distance_km)]


_T = TypeVar("_T")


def _split_into_bins(items: list[_T], distance_km: Callable[[_T], float]) -> list[list[_T]]:
    """連続する`items`を、累積距離が`SEGMENT_BIN_DISTANCE_KM`に達するごとに切る。最後の端数も1つのビンにする。"""
    bins: list[list[_T]] = []
    current_bin: list[_T] = []
    current_bin_distance = 0.0
    for item in items:
        current_bin.append(item)
        current_bin_distance += distance_km(item)
        if current_bin_distance >= SEGMENT_BIN_DISTANCE_KM:
            bins.append(current_bin)
            current_bin = []
            current_bin_distance = 0.0
    if current_bin:
        bins.append(current_bin)
    return bins


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


_SIGNIFICANT_DIGITS = 4


def _round_significant(value: float) -> float:
    """有効数字`_SIGNIFICANT_DIGITS`桁へ丸める（値のスケールに依存しない丸め）。

    0〜100のdifficultyと違い、物理量の生値・材料値はスケールが軸ごとに違う
    （事故密度は`件/(km・年)`で有効域0〜0.5、勾配は`%`で0〜15程度）。
    固定の小数桁で丸めると、桁の小さい軸で値がまるごと潰れる。
    """
    if value == 0.0:
        return value
    return round(value, -int(math.floor(math.log10(abs(value)))) + (_SIGNIFICANT_DIGITS - 1))


def _merge_axis_value_dict(
    segments: list[RouteSegmentDetail],
    field_getter: Callable[[RouteSegmentDetail], dict[str, float]],
    round_value: Callable[[float], float] = round_difficulty,
) -> dict[str, float]:
    """複数の`RouteSegmentDetail`が持つキー→float辞書（`field_getter`で指定）を、
    キーごとに距離加重平均へ集約する共通ロジック（`merge_axis_difficulties`/
    `merge_axis_contributions`/`merge_material_values`の共有実装）。
    渡されたsegments群のどの区間にも無いキーは結果にも含めない
    （各フィールド共通の「データ無しはキーを持たない」規約）。

    `round_value`は集約後の丸め方。**0〜100のdifficulty系と、スケールが軸ごとに違う
    物理量（生値・材料値）とで必要な粒度が違う**ため、呼び出し側が指定する。
    """
    return _merge_weighted_dicts([(s.distance_km, field_getter(s)) for s in segments], round_value)


def _merge_weighted_dicts(
    items: list[tuple[float, Mapping[str, float]]], round_value: Callable[[float], float]
) -> dict[str, float]:
    """（距離km, キー→値）の並びを、キーごとに距離加重平均へ畳む。キーの無い項目はそのキーの平均に入れない。"""
    keys = {key for _, values in items for key in values}
    merged: dict[str, float] = {}
    for key in keys:
        value = weighted_mean_by_distance([(values.get(key), distance) for distance, values in items])
        if value is not None:
            merged[key] = round_value(value)
    return merged


def merge_axis_difficulties(segments: list[RouteSegmentDetail]) -> dict[str, float]:
    """`RouteSegmentDetail.axis_difficulties`をaxis_idごとに距離加重平均へ集約する。
    `_merge_segment_bin`がビン単位（500m）の集約に使うほか、
    `RouteCandidate.axis_difficulties`はこの関数を候補の全区間へ1回
    適用するだけで得られる（新しい計算式は不要、`route_generator.py`参照）。
    """
    return _merge_axis_value_dict(segments, lambda s: s.axis_difficulties)


def route_axis_raw_values(edges: list[tuple[float, Mapping[str, float]]]) -> dict[str, float]:
    """Edge単位の（距離km, axis_id→生値）を、候補全体の`RouteCandidate.axis_raw_values`へ畳む。

    区間（`aggregate_segments_into_bins`）と同じ切り方でビンへ畳んでから、ビンを距離加重平均する——
    ほかの候補単位の値（`axis_difficulties`等）がビンへ畳んだ区間から作られるのと、平均の取り方を揃える。
    距離はビンの区間の`distance_km`と同じ丸めた値を渡すこと。
    """
    bins = _split_into_bins(edges, lambda edge: edge[0])
    return _merge_weighted_dicts(
        [
            (round(sum(distance for distance, _ in bin_edges), 2), _merge_weighted_dicts(bin_edges, _round_significant))
            for bin_edges in bins
        ],
        _round_significant,
    )


def merge_axis_contributions(segments: list[RouteSegmentDetail]) -> dict[str, float]:
    """`RouteSegmentDetail.axis_contributions`（「重み付き寄与度」）を
    axis_idごとに距離加重平均へ集約する。`merge_axis_difficulties`と同じ集約方法
    （`_merge_axis_value_dict`共有実装）。`_merge_segment_bin`のビン単位集約、
    `RouteCandidate.axis_contributions`（`route_generator.py`の候補全体の集約）の両方が使う。
    """
    return _merge_axis_value_dict(segments, lambda s: s.axis_contributions)


def merge_material_values(segments: list[RouteSegmentDetail]) -> dict[str, float]:
    """`RouteSegmentDetail.material_values`を材料idごとに距離加重平均へ集約する。
    `merge_axis_difficulties`と同じ集約方法（`_merge_axis_value_dict`共有実装）。
    """
    return _merge_axis_value_dict(segments, lambda s: s.material_values, _round_significant)


def merge_material_category_shares(
    segments: Iterable[tuple[float, Mapping[str, str]]],
) -> dict[str, dict[str, float]]:
    """区間ごとのcategorical材料の値（区間の距離km, 材料id→値）を、材料idごとに
    「値→延長割合」へ畳む。

    数値材料の`merge_material_values`（距離加重平均）に対応するcategorical版。真偽値材料を
    0/1で運んで平均が割合になるのと同じ考え方を、値が3つ以上ある材料へ広げたもの。
    分母はその材料の値を持つ区間の距離合計で、値の無い区間は分母にも入れない
    （「観測できた範囲でどの値が多いか」を表す）。
    """
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for distance_km, categories in segments:
        if distance_km <= 0:
            continue
        for material_id, value in categories.items():
            totals[material_id][value] += distance_km
    shares: dict[str, dict[str, float]] = {}
    for material_id, by_value in totals.items():
        # 距離0以下の区間は上で外しているため、ここでの合計は必ず正になる。
        total = sum(by_value.values())
        shares[material_id] = {
            value: round(distance / total, 4)
            for value, distance in sorted(by_value.items(), key=lambda item: (-item[1], item[0]))
        }
    return shares


#: ビンへ引き継ぐ辞書フィールドと、その畳み方（キーごとの距離加重平均）。
BIN_DICT_FIELD_MERGERS: dict[str, Callable[[list[RouteSegmentDetail]], dict[str, float]]] = {
    "axis_difficulties": merge_axis_difficulties,
    "axis_contributions": merge_axis_contributions,
    "material_values": merge_material_values,
}

#: ビンのフィールドと、ビンに入る区間の並びからその値を作る畳み方。`_merge_segment_bin`は
#: この表だけからビンを組み立てる。
BIN_FIELD_MERGERS: dict[str, Callable[[list[RouteSegmentDetail]], object]] = {
    "geometry": _concat_segment_geometries,
    "start_latitude": lambda segments: segments[0].start_latitude,
    "start_longitude": lambda segments: segments[0].start_longitude,
    "end_latitude": lambda segments: segments[-1].end_latitude,
    "end_longitude": lambda segments: segments[-1].end_longitude,
    "cumulative_distance_km": lambda segments: segments[0].cumulative_distance_km,
    "distance_km": lambda segments: round(sum(s.distance_km for s in segments), 2),
    "estimated_arrival_time": lambda segments: segments[0].estimated_arrival_time,
    # 到達予想と同じく、ビンに入った先頭の区間の値（ビンの中で予報の時刻が変わっても、入るときの風を出す）。
    "wind": lambda segments: segments[0].wind,
    "difficulty": lambda segments: distance_weighted_difficulty([(s.difficulty, s.distance_km) for s in segments]),
    **BIN_DICT_FIELD_MERGERS,
}


def _undeclared_fields() -> list[str]:
    """`RouteSegmentDetail`のフィールドのうち、ビンへの畳み方が宣言されていないもの。"""
    return sorted(set(RouteSegmentDetail.model_fields) - set(BIN_FIELD_MERGERS))


if _undeclared_fields():
    # 宣言し忘れたフィールドはビンで既定値になるだけで、型でも例外でも現れない
    # （区間インスペクタから値が消える）。読み込みの時点で止める。
    raise RuntimeError(
        f"RouteSegmentDetail のフィールド {_undeclared_fields()} は、BIN_FIELD_MERGERS（ビンへの畳み方）で宣言すること"
    )


def _merge_segment_bin(segments: list[RouteSegmentDetail]) -> RouteSegmentDetail:
    return RouteSegmentDetail.model_validate({name: merge(segments) for name, merge in BIN_FIELD_MERGERS.items()})
