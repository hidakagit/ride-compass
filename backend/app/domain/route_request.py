"""ルート生成の要求が受け付ける値の範囲と、その外れを知らせる文。

範囲は要求の検証（`api/routers/routes.py: RouteGenerateRequest`。想定速度は地図の入口も）と、画面が操作を
止める上限（生成物`route-generate-config.json`）の両方がここから読む。
"""

import math
from dataclasses import dataclass
from typing import Annotated

from pydantic import Field
from pydantic_core import PydanticCustomError

from app.domain.route import Coordinates

# ルート生成距離の上限（km）。上限が無いと探索の範囲が際限なく広がり、道路網の読み込みが
# 長時間止まりうる。30km規模までの検証実績に余裕を見た値。経由地・目的地は出発地からこの
# 距離の中に置く。
MAX_ROUTE_DISTANCE_KM = 100
# 目標距離からの許容差（km）。画面はこの既定値をそのまま送る——片方だけ変えると、画面の
# 見込みと探索の範囲がずれる。
DEFAULT_DISTANCE_TOLERANCE_KM = 5.0
MAX_DISTANCE_TOLERANCE_KM = 50.0
# 経由地の数の上限。経由地ごとにレグの探索が1本増える。
MAX_WAYPOINTS = 8
# 区間の乗り換えで受け取るEdge idの上限。1本の候補が数百Edgeで、区間を差し替えても
# 2本ぶんの長さを超えることはない。
MAX_SPLICED_EDGES = 5000
# 返す候補数の画面の既定値と、要求の`max_routes`の下限・上限。
DEFAULT_MAX_ROUTES = 8
MIN_ROUTES = 1
MAX_ROUTES = 15
# 仮定巡航速度（km/h）の画面の既定値と、要求が受け付ける下限・上限。区間ごとの推定到達時刻と、風の追加負荷
# （`domain/wind.py: wind_drag_ratio_array`の走行速度）の算出に使う。風・勾配に依存しない一律の定数として扱うことが
# 前提——速度を風で可変にすると「時刻の算出に速度が要り、速度が風（時刻依存）に影響される」循環が生まれる。
ASSUMED_SPEED_KMH = 20.0
MIN_ASSUMED_SPEED_KMH = 5.0
MAX_ASSUMED_SPEED_KMH = 60.0
# 想定速度の値の範囲。速度を受けるどの入口（ルート生成・地図の配信・区間インスペクタ）もこの型で書く。範囲の検査は
# NaN・無限大も断る。
AssumedSpeedKmh = Annotated[float, Field(ge=MIN_ASSUMED_SPEED_KMH, le=MAX_ASSUMED_SPEED_KMH)]
# 経由地を伴う生成が返す候補の数。経由地があるとレグごとの代替が組合せで増えるため、候補数の
# 指定を使わず単一経路にする。
ROUTES_WITH_WAYPOINTS = 1


def applied_max_routes(max_routes: int, *, has_waypoints: bool) -> int:
    """その生成で実際に使う候補数の上限。画面も同じ値を生成物で受け取り、候補数の入力欄に出す。"""
    return ROUTES_WITH_WAYPOINTS if has_waypoints else max_routes


def request_error(message: str) -> PydanticCustomError:
    """要求の誤り。文は画面の結果欄へそのまま出るので、利用者が読める日本語で書く
    （`ValueError`は「Value error, 」の前置きが付いて返る）。"""
    return PydanticCustomError("route_request", message)


def check_waypoint_count(count: int) -> None:
    if count > MAX_WAYPOINTS:
        raise request_error(f"経由地は{MAX_WAYPOINTS}地点までです。")


def check_spliced_edge_count(count: int) -> None:
    if count > MAX_SPLICED_EDGES:
        raise request_error("組み合わせたルートが長すぎるため評価できません。")


def search_distance_km(farthest_km: float) -> int:
    """経由地・目的地を置いたときの探索の範囲（km）。`farthest_km`は出発地から最も遠い点までの距離。

    範囲は最も遠い点より長くする（ただし上限`MAX_ROUTE_DISTANCE_KM`を超えないので、最も遠い点が上限ちょうどなら
    等しい）。上限より遠い点は要求の誤り。
    """
    if farthest_km > MAX_ROUTE_DISTANCE_KM:
        raise request_error(f"経由地・目的地は出発地から{MAX_ROUTE_DISTANCE_KM}km以内に置いてください。")
    return min(MAX_ROUTE_DISTANCE_KM, math.ceil(farthest_km) + 1)


@dataclass(frozen=True)
class FixedPoints:
    """出発地のあとに順に通る、置いた点の並び。経由地を置いた順に通り、目的地（無ければ出発地）で終わる。"""

    waypoints: list[Coordinates]
    destination: Coordinates | None


@dataclass(frozen=True)
class DistanceTarget:
    """全長の目標に合う候補を探す（距離あり）。置いた点はまだ受けず、出発地へ戻る周回だけを作る。"""

    distance_km: float


@dataclass(frozen=True)
class NoDistanceTarget:
    """置いた点を順に通り、終点へ良い道で向かう候補を探す（距離なし）。`distance_km`は置いた点から決めた探索の範囲。"""

    distance_km: float
    points: FixedPoints


@dataclass(frozen=True)
class SplicedTarget:
    """区間を差し替えて組み立てた経路を、探索せずに評価する。目的地ルートだけが対象。"""

    distance_km: float
    destination: Coordinates
    edge_ids: tuple[str, *tuple[str, ...]]


# 検証を通った要求が何を生成するか。距離の有無（仕上げの戦略）は要求の検証がここで1回だけ選び、生成は型だけを見る。
RouteTarget = DistanceTarget | NoDistanceTarget | SplicedTarget
