import httpx

from app.domain.route import Coordinates
from app.infrastructure import cache_db
from app.infrastructure.debug_log import log_external_call

GSI_ELEVATION_URL = "https://cyberjapandata2.gsi.go.jp/general/dem/scripts/getelevation.php"

# 緯度経度を丸める桁数（4桁 ≈ 日本付近で誤差11m程度）。標高はほぼ不変のデータのため、
# 8方位の候補ルートが起点付近で近接するサンプル点を大きく削減できる。
# SQLite（app/infrastructure/cache_db.py）に永続化し、プロセス再起動をまたいで使い回す。
CACHE_PRECISION = 4


class ElevationClient:
    """国土地理院（GSI）標高APIのクライアント。1リクエスト=1地点。

    標高は付随情報のため、取得できなかった場合（守備範囲外・通信エラー等）は
    例外を投げず`None`を返す（呼び出し元でルート自体は生かす）。

    呼び出し元がhttpx.AsyncClientを渡す設計にしている。1ルートあたり十数地点を
    問い合わせるため、リクエストごとに新規クライアント（＝新規TLSハンドシェイク）を
    作ると大幅に遅くなることが実機検証で判明したため、コネクションを使い回す。
    """

    async def get_elevation(self, client: httpx.AsyncClient, point: Coordinates, refresh: bool = False) -> float | None:
        lat = round(point.latitude, CACHE_PRECISION)
        lon = round(point.longitude, CACHE_PRECISION)

        # キャッシュヒット時のelapsedは実質SQLite(cache_db)の所要時間になるため、
        # このログ・統計が標高キャッシュのクエリ時間の観測点を兼ねる。
        with log_external_call("elevation:gsi", lat=lat, lon=lon) as fields:
            if not refresh:
                cached = await cache_db.get_elevation(lat, lon)
                if cached is not cache_db.MISSING:
                    fields["cache"] = "hit"
                    return cached
            fields["cache"] = "miss"

            elevation = await self._fetch(client, point, fields)
            await cache_db.set_elevation(lat, lon, elevation)
            return elevation

    async def _fetch(self, client: httpx.AsyncClient, point: Coordinates, fields: dict) -> float | None:
        params = {"lon": point.longitude, "lat": point.latitude, "outtype": "JSON"}

        try:
            response = await client.get(GSI_ELEVATION_URL, params=params)
            fields["status"] = getattr(response, "status_code", None)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            fields["result"] = "error"
            fields["error"] = repr(exc)
            return None

        elevation = data.get("elevation")
        if not isinstance(elevation, (int, float)):
            # GSIは守備範囲外(海上等)で"-----"を返す。通信エラーとは区別して記録する
            # (エラー扱いにはしない。頻出してもWARNINGでログを埋めない)。
            fields["result"] = "no_elevation"
            return None
        fields["result"] = "ok"
        return float(elevation)
