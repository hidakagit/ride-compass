import asyncio

import httpx

from app.domain.geo import haversine_distance_km
from app.domain.route import Coordinates
from app.infrastructure.elevation_client import ElevationClient
from app.services.elevation_aggregation import max_or_none, min_or_none, sum_or_none

MAX_CONCURRENT_REQUESTS = 5

EMPTY_PROFILE = {
    "elevation_gain_m": None,
    "min_elevation_m": None,
    "max_elevation_m": None,
    "max_gradient_percent": None,
}


class ElevationService:
    """指定された点列から標高プロファイル（獲得標高・最高/最低標高・最大勾配）を算出する。

    サンプル点は呼び出し元（`RouteGenerator`）が渡す。標高・風・路面を同じ点集合・同じ並びで
    評価し、区間ごとの詳細（`RouteCandidate.segments`）としてインデックス整合させるため。
    国土地理院APIは1地点ずつのリクエストしかできないため、点ごとに個別に問い合わせる。
    `http_client`は呼び出し元（DI）が生成・クローズを管理する共有コネクションで、
    複数ルート・複数地点のリクエストで使い回すことでTLSハンドシェイクの重複を避ける。
    `semaphore`はコンストラクタで1つだけ生成し、このインスタンスへの全`get_profile`呼び出しで
    共有することで、無料の公共サービスへの同時リクエスト数を確実に制限する。
    """

    def __init__(self, client: ElevationClient, http_client: httpx.AsyncClient):
        self._client = client
        self._http_client = http_client
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def get_profile(self, points: list[Coordinates]) -> dict:
        async def fetch(point):
            async with self._semaphore:
                return await self._client.get_elevation(self._http_client, point)

        elevations = await asyncio.gather(*(fetch(p) for p in points))

        valid = [(p, e) for p, e in zip(points, elevations) if e is not None]
        if len(valid) < 2:
            return {**EMPTY_PROFILE, "elevations": elevations}

        gain = 0.0
        max_gradient = 0.0
        for (p1, e1), (p2, e2) in zip(valid, valid[1:]):
            diff = e2 - e1
            if diff > 0:
                gain += diff

            distance_m = haversine_distance_km(p1, p2) * 1000
            if distance_m > 0:
                gradient = abs(diff) / distance_m * 100
                max_gradient = max(max_gradient, gradient)

        elevations_only = [e for _, e in valid]

        # 最終集約（sum/min/max・空ならNone・小数1桁丸め）はRoadGraphEngine._aggregate_elevationと
        # 共有する（elevation_aggregation.pyのdocstring参照。標高値自体の算出方法は別実装のまま）。
        # ここではlen(valid)>=2が確定済み（上のガード）のためelevations_onlyは非空、
        # gain/max_gradientは単一のスカラーとして`sum_or_none([...])`へ渡す。
        return {
            "elevation_gain_m": sum_or_none([gain]),
            "min_elevation_m": min_or_none(elevations_only),
            "max_elevation_m": max_or_none(elevations_only),
            "max_gradient_percent": max_or_none([max_gradient]),
            "elevations": elevations,
        }
