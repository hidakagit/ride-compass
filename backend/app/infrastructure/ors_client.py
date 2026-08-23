import httpx

from app.domain.errors import RoutingError
from app.domain.route import Coordinates
from app.infrastructure.debug_log import log_external_call

DIRECTIONS_URL = "https://api.openrouteservice.org/v2/directions/cycling-road/geojson"

# openrouteserviceが返す無料枠の残量ヘッダ(日次2000リクエスト)。ルート生成1回で
# 最大8方位分を消費するため、枯渇が近いかどうかをログ・統計から追えるようにする。
QUOTA_REMAINING_HEADER = "x-ratelimit-remaining"


class ORSClient:
    """openrouteservice Directions APIのクライアント。

    `http_client`は呼び出し元（DI）が生成・クローズを管理する共有コネクション。
    以前は呼び出しごとに新規`httpx.AsyncClient`を生成しており、8方位の周回生成では
    TLSハンドシェイクを8回やり直していた（ElevationClientで実測57秒→7秒の差を生んだ
    のと同じパターン）ため、他のクライアントと同様にコンストラクタ注入へ統一した。
    """

    def __init__(self, api_key: str, http_client: httpx.AsyncClient):
        self._api_key = api_key
        self._http_client = http_client

    async def get_directions(self, waypoints: list[Coordinates]) -> dict:
        # extra_info=surface（ORS路面種別ID）は改善計画T21で廃止: 路面評価は自前DBの
        # Edgeへの空間マッチ（OSMタグ語彙）へ統一済みのため、この付随情報は不要。
        payload = {
            "coordinates": [[point.longitude, point.latitude] for point in waypoints],
        }
        headers = {
            "Authorization": self._api_key,
            "Content-Type": "application/json",
        }

        with log_external_call("routing:openrouteservice", waypoint_count=len(waypoints)) as fields:
            try:
                response = await self._http_client.post(DIRECTIONS_URL, json=payload, headers=headers)
                fields["status"] = response.status_code
                fields["quota_remaining"] = response.headers.get(QUOTA_REMAINING_HEADER)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RoutingError(
                    f"openrouteservice returned {exc.response.status_code}: {exc.response.text}"
                ) from exc
            except httpx.RequestError as exc:
                # 改善計画T228: str(exc)が空文字になるhttpx例外があり
                # （例: 一部の接続エラー）、その場合`RoutingError`のメッセージが
                # 診断情報ゼロになっていた（2026-08-23の実機確認で原因切り分けができず
                # 発覚）。例外種別名を必ず含める。
                raise RoutingError(
                    f"openrouteservice request failed: {type(exc).__name__}: {exc}"
                ) from exc

            try:
                data = response.json()
                features = data.get("features")
            except (ValueError, AttributeError) as exc:
                raise RoutingError(f"openrouteservice returned unparseable response: {exc}") from exc
            if not features:
                raise RoutingError("openrouteservice returned no route")

            fields["result"] = "ok"
            return features[0]
