"""ルート生成の要求が受け付ける値の範囲と、その外れを知らせる文。

範囲は要求の検証（`api/routers/routes.py: RouteGenerateRequest`）と、画面が操作を止める上限
（生成物`route-generate-config.json`）の両方がここから読む。
"""

from pydantic_core import PydanticCustomError

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


def check_point_distance(farthest_km: float) -> None:
    """経由地・目的地のうち出発地から最も遠い点までの距離（km）が上限の中か。"""
    if farthest_km > MAX_ROUTE_DISTANCE_KM:
        raise request_error(f"経由地・目的地は出発地から{MAX_ROUTE_DISTANCE_KM}km以内に置いてください。")
