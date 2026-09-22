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

    符号付き材料（`material_values`に入る`gradient_percent`等）は**符号付き・進行方向
    基準**（登り=正、下り=負）。フロントの勾配色分けはこの符号を前提に「下り」カテゴリを
    持つため、絶対値で返してはならない。

    geometryはこの区間が実際に通る道なり形状（GeoJSON LineString、ルート全体geometryの
    部分列）。フロントはこれがnullの場合のみ始点・終点の直線で代替描画する。
    """

    geometry: dict | None = None
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
    # categorical材料id→この区間の値（例: highway→"residential"）。材料の内訳としては
    # `material_values`と同じものだが、値が文字列で平均できないため器を分ける。
    material_categories: dict[str, str] = Field(default_factory=dict)
    # axis_id→折れ点を通す前の生値。単位が定まる軸だけが持つ。得点（0-100）は目盛りの
    # 引き方に依存する相対評価のため、軸単体で経路を判断するにはこの絶対値が要る。
    axis_raw_values: dict[str, float] = Field(default_factory=dict)
    difficulty: float | None = None


class RouteCandidate(StrictModel):
    """1本のルート候補。

    `overall_difficulty`はsegmentsの`difficulty`（絶対基準0-100）の距離加重平均で、
    重み・条件が違う実験の間でも比較できる。候補タブの並び順はこの値の昇順で決まる。
    segments欠損時・全区間difficulty欠損時はNone。

    辞書フィールドは`RouteSegmentDetail`の同名フィールドを候補の全区間へ距離加重平均で
    集約したもので、「データ無しはキーを持たない」規約も引き継ぐ。
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
    # 難易度の総量（`overall_difficulty` × 距離km）。平均は距離で正規化されるため
    # 遠回りするほど下がるのに対し、総量は距離が伸びればそのまま増える。候補の順位付けには
    # 使わず、「長い分だけ疲れる」を平均と併せて読み取るための判断材料として持つ。
    difficulty_load: float | None = None
    # 所要時間の見積もり（秒）。区間の走行時間（走行モデル: 巡航速度・勾配・風から求めた
    # 速度）＋停止の待ち＋ターンの待ち。経路の選び方には使っておらず、表示のためだけに持つ。
    estimated_duration_seconds: float | None = None
    axis_difficulties: dict[str, float] = Field(default_factory=dict)
    # 合計は丸め誤差を除いて`overall_difficulty`と一致する。フロントの「内訳（重み付き
    # 寄与度）」表示はこれをそのまま使い、ルート設定の重みを使った独自再計算はしない。
    axis_contributions: dict[str, float] = Field(default_factory=dict)
    # 単位は`GET /api/axis-catalog`の`raw_value_unit`が持ち、「◯◯/km」なら走行距離を
    # 掛けて経路全体の実数（例: 止まる回数）にできる。
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
    # 所要時間が最短の経路か＝軸の重みをすべて0にしたときの基準線（目的地モードのみ。
    # 周回は目標距離が距離を決めるため常にFalse）。「backendが基準線として別途探索した
    # 候補」を指す印であり、候補一覧から選んだ所要時間の最小とは意味が違う。
    # Trueは高々1本で、基準線を求められなければ1本も立たない。
    is_fastest: bool = False


# エンジンが返すsegmentsはEdge単位（交差点間）でAPIペイロード・フロント描画コストが
# 嵩むため、この距離単位へ集約してから返す。
_SEGMENT_BIN_DISTANCE_KM = 0.5


def aggregate_segments_into_bins(
    segments: list[RouteSegmentDetail], bin_distance_km: float = _SEGMENT_BIN_DISTANCE_KM
) -> list[RouteSegmentDetail]:
    """連続するEdge単位の`RouteSegmentDetail`を、累積距離`bin_distance_km`単位で
    グルーピングし、1ビン1件の`RouteSegmentDetail`へ集約する。

    値の性質ごとに畳み方が違う: difficulty系と材料値は距離加重平均（値がNoneの区間は
    除外し、残りの距離で再正規化）、位置はビンの始点・終点、距離は合計、geometryは
    隣接区間の境界点を重複させずに連結する。

    最後のビンは`bin_distance_km`未満でも単独で残す（切り捨てると経路全体の距離が
    合わなくなる）。
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
        # 距離0以下の区間は上で外しているため、ここでの合計は必ず正になる。
        total = sum(by_value.values())
        shares[material_id] = {
            value: round(distance / total, 4)
            for value, distance in sorted(by_value.items(), key=lambda item: (-item[1], item[0]))
        }
    return shares


#: ビンへ引き継ぐ辞書フィールドと、その畳み方。
BIN_DICT_FIELD_MERGERS: dict[str, Callable[[list[RouteSegmentDetail]], dict[str, float]]] = {
    "axis_difficulties": merge_axis_difficulties,
    "axis_contributions": merge_axis_contributions,
    "axis_raw_values": merge_axis_raw_values,
    "material_values": merge_material_values,
}

# ビンへ畳むときに引き継がない辞書フィールドと、その理由。
BIN_DROPPED_DICT_FIELDS: dict[str, str] = {
    # categorical材料は平均できず、ビンの代表値を1つ選ぶと延長割合が500m単位へ量子化される。
    # ルート全体の割合（`RouteCandidate.material_category_shares`）はEdge単位のsegmentsから
    # 畳む必要があるため、`road_graph_engine`がビニングの前に計算する。区間単位の値には
    # 消費者がいない。
    "material_categories": "ビン代表値では延長割合が歪むため、ビニング前に候補全体の割合へ畳む",
}


def _undeclared_dict_fields() -> list[str]:
    """`RouteSegmentDetail`の辞書フィールドのうち、ビンへの畳み方も、引き継がない理由も
    宣言されていないもの。"""
    declared = set(BIN_DICT_FIELD_MERGERS) | set(BIN_DROPPED_DICT_FIELDS)
    return sorted(
        name
        for name, model_field in RouteSegmentDetail.model_fields.items()
        if getattr(model_field.annotation, "__origin__", None) is dict and name not in declared
    )


if _undeclared_dict_fields():
    # 宣言し忘れたフィールドはビンで空の辞書になるだけで、型でも例外でも現れない
    # （区間インスペクタから値が消える）。読み込みの時点で止める。
    raise RuntimeError(
        f"RouteSegmentDetail の辞書フィールド {_undeclared_dict_fields()} は、"
        "BIN_DICT_FIELD_MERGERS（ビンへの畳み方）か "
        "BIN_DROPPED_DICT_FIELDS（引き継がない理由）のどちらかで宣言すること"
    )


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
        difficulty=distance_weighted_difficulty([(s.difficulty, s.distance_km) for s in segments]),
        **{name: merge(segments) for name, merge in BIN_DICT_FIELD_MERGERS.items()},
    )
