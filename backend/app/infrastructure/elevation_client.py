import asyncio
from collections import OrderedDict

import httpx

from app.domain.region import lonlat_to_tile_pixel
from app.domain.route import Coordinates
from app.infrastructure import tile_cache
from app.infrastructure.debug_log import error_type_label, log_external_call

# DEMタイル方式の詳細（URL・キャッシュ2段・タイル仕様）はdocs/modules/backend/elevation.md参照。
DEFAULT_MAX_TILE_GRIDS = 500

MAX_CONCURRENT_REQUESTS = 5
DEM_TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/{type}/{z}/{x}/{y}.txt"
DEM_TYPE_PRIORITY = ("dem5a", "dem5b", "dem5c", "dem")
DEM_ZOOM = 14
DEM_TILE_SIZE = 256
DEM_MISSING_MARKER = "e"
DEM_TILE_CONTENT_TYPE = "text/plain; charset=utf-8"

_tile_grid_cache: "OrderedDict[tuple[str, int, int], list[list[float | None]] | None]" = OrderedDict()

# 異なるリクエスト（本番backendの並行route生成）が同時に同じ未取得タイルへ到達しても
# 重複GET・重複パースにならないよう、同一タイルへの同時フェッチを1回へ束ねる（single-flight）。
_in_flight_tile_fetches: "dict[tuple[str, int, int], asyncio.Future[None]]" = {}


def _remember_tile_grid(cache_key: tuple[str, int, int], grid: list[list[float | None]] | None) -> None:
    """`_tile_grid_cache`への書き込み＋上限超過分の追い出しを一箇所へ集約する
    （`graph_material_cache.py: _LRUCache.set`と同じ定型処理）。"""
    _tile_grid_cache[cache_key] = grid
    _tile_grid_cache.move_to_end(cache_key)
    if len(_tile_grid_cache) > DEFAULT_MAX_TILE_GRIDS:
        _tile_grid_cache.popitem(last=False)


class _CoverageGap:
    """DEMタイルがそのdem_typeの整備区域外であること（GSIが404を返す）を表すセンチネル。

    一時的な通信エラー（タイムアウト・5xx等）と整備区域外（404、恒久的）はどちらも
    `_fetch_tile`が`None`を返す点で見分けがつかないため、このセンチネルで区別する。
    区別しないと`_get_tile_grid`が一時的な障害まで`_tile_grid_cache`へ恒久キャッシュ
    してしまい、プロセスが再起動するまで標高がNone固定になる。
    """


_COVERAGE_GAP = _CoverageGap()


def _parse_dem_tile_text(text: str) -> list[list[float | None]]:
    """DEMタイルのテキスト本文（256行×256列のカンマ区切り、欠測は"e"）をパースする。"""
    return [
        [None if cell == DEM_MISSING_MARKER else float(cell) for cell in line.split(",")]
        for line in text.strip("\n").split("\n")
        if line
    ]


def _bilinear_interpolate(grid: list[list[float | None]], px: float, py: float) -> float | None:
    """グリッド内の連続位置(px, py)を周囲4画素の双線形補間で求める。境界（最終行・列）は
    クランプする。周囲4点のいずれかが欠測(None)なら補間せず、最も近い画素の値
    （欠測ならNone）にフォールバックする（データが疎な海岸線・タイル境界付近を除けば
    通常発生しない）。
    """
    size = len(grid)
    x0 = min(int(px), size - 1)
    y0 = min(int(py), size - 1)
    x1 = min(x0 + 1, size - 1)
    y1 = min(y0 + 1, size - 1)
    fx = px - x0
    fy = py - y0

    v00, v10, v01, v11 = grid[y0][x0], grid[y0][x1], grid[y1][x0], grid[y1][x1]
    if v00 is None or v10 is None or v01 is None or v11 is None:
        nearest_x = x0 if fx < 0.5 else x1
        nearest_y = y0 if fy < 0.5 else y1
        return grid[nearest_y][nearest_x]

    top = v00 + (v10 - v00) * fx
    bottom = v01 + (v11 - v01) * fx
    return top + (bottom - top) * fy


class ElevationClient:
    """国土地理院（GSI）標高DEMタイルのクライアント。タイル単位で取得・キャッシュし、
    任意地点の標高はタイル内を双線形補間して求める。

    標高は付随情報のため、取得できなかった場合（守備範囲外・通信エラー等）は
    例外を投げず`None`を返す（呼び出し元でルート自体は生かす）。

    呼び出し元がhttpx.AsyncClientを渡す設計にしている——1ルートあたり十数地点を
    問い合わせるため、リクエストごとに新規クライアント（＝新規TLSハンドシェイク）を
    作ると遅い。

    実際のGSIへの同時リクエスト数は`MAX_CONCURRENT_REQUESTS`で絞る（インスタンス単位）。
    """

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def get_elevation(self, client: httpx.AsyncClient, point: Coordinates, refresh: bool = False) -> float | None:
        results = await self.get_elevations(client, [point], refresh=refresh)
        return results[0]

    async def get_elevations(
        self, client: httpx.AsyncClient, points: list[Coordinates], refresh: bool = False
    ) -> list[float | None]:
        """複数地点の標高を、地点ごとのasyncioタスクではなくタイル単位でまとめて取得する。
        1地点ずつ`get_elevation`する場合と結果は同一（同じ`DEM_TYPE_PRIORITY`優先順位・
        同じ双線形補間）。

        `DEM_TYPE_PRIORITY`を1ラウンドずつ進める（最大4ラウンド）: そのラウンドで
        まだ結果が決まっていない地点が必要とするタイルをまとめて1回のフェッチへ
        （`_load_tile_grid`のsingle-flightで重複排除）束ね、フェッチ後にまとめて
        判定し直す。1ラウンドで解決しなかった地点だけが次のdem_typeへ進む。
        """
        n = len(points)
        if n == 0:
            return []
        tile_coords = [lonlat_to_tile_pixel(p.longitude, p.latitude, DEM_ZOOM, DEM_TILE_SIZE) for p in points]
        results: list[float | None] = [None] * n
        dem_type_index = [0] * n
        pending = list(range(n))

        for _ in DEM_TYPE_PRIORITY:
            if not pending:
                break
            needed: set[tuple[str, int, int]] = set()
            for i in pending:
                cache_key = (DEM_TYPE_PRIORITY[dem_type_index[i]], tile_coords[i][0], tile_coords[i][1])
                if refresh or cache_key not in _tile_grid_cache:
                    needed.add(cache_key)
            if needed:
                with log_external_call("elevation:gsi-dem", tile_count=len(needed)) as fields:
                    await asyncio.gather(
                        *(
                            self._load_tile_grid(client, dem_type, tile_x, tile_y, refresh, fields)
                            for dem_type, tile_x, tile_y in needed
                        )
                    )
            still_pending: list[int] = []
            for i in pending:
                dem_type = DEM_TYPE_PRIORITY[dem_type_index[i]]
                tile_x, tile_y, px, py = tile_coords[i]
                cache_key = (dem_type, tile_x, tile_y)
                grid = _tile_grid_cache.get(cache_key)
                if cache_key in _tile_grid_cache:
                    _tile_grid_cache.move_to_end(cache_key)
                elevation = _bilinear_interpolate(grid, px, py) if grid is not None else None
                if elevation is not None:
                    results[i] = elevation
                else:
                    dem_type_index[i] += 1
                    if dem_type_index[i] < len(DEM_TYPE_PRIORITY):
                        still_pending.append(i)
            pending = still_pending

        return results

    async def _load_tile_grid(
        self, client: httpx.AsyncClient, dem_type: str, tile_x: int, tile_y: int, refresh: bool, fields: dict
    ) -> None:
        """指定タイルのグリッドをメモリキャッシュ以外（ディスク→ネットワーク）から
        取得し、`_tile_grid_cache`へ書き込む（戻り値は無く、呼び出し元が改めて
        `_tile_grid_cache`を参照する）。呼び出し元がメモリキャッシュを先にチェック
        していることを前提とする。

        同一タイルへの同時呼び出しは1回のフェッチへ束ねる（single-flight）。
        フェッチが一時的な通信エラーで失敗した場合は何もキャッシュ
        しない（`_CoverageGap`とは区別する既存方針、`_fetch_tile`参照）——呼び出し元は
        `_tile_grid_cache`にキーが無いままなので、次回呼び出しでも未取得として
        再試行される。
        """
        cache_key = (dem_type, tile_x, tile_y)
        path = f"gsi/{dem_type}/{DEM_ZOOM}/{tile_x}/{tile_y}.txt"
        if not refresh:
            cached = tile_cache.get(path)
            if cached is not None:
                fields["cache"] = "hit"
                content, _content_type = cached
                grid = _parse_dem_tile_text(content.decode("utf-8"))
                _remember_tile_grid(cache_key, grid)
                return

        in_flight = _in_flight_tile_fetches.get(cache_key)
        if in_flight is not None:
            fields["cache"] = "in_flight"
            await in_flight
            return

        fields["cache"] = "miss"
        future: "asyncio.Future[None]" = asyncio.get_running_loop().create_future()
        _in_flight_tile_fetches[cache_key] = future
        try:
            async with self._semaphore:
                result = await self._fetch_tile(client, dem_type, tile_x, tile_y, path, fields)
            if result is not None:
                grid = None if isinstance(result, _CoverageGap) else result
                _remember_tile_grid(cache_key, grid)
            future.set_result(None)
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            del _in_flight_tile_fetches[cache_key]

    async def _fetch_tile(
        self, client: httpx.AsyncClient, dem_type: str, tile_x: int, tile_y: int, path: str, fields: dict
    ) -> list[list[float | None]] | _CoverageGap | None:
        url = DEM_TILE_URL.format(type=dem_type, z=DEM_ZOOM, x=tile_x, y=tile_y)
        try:
            response = await client.get(url)
            fields["status"] = getattr(response, "status_code", None)
            if response.status_code == 404:
                # カバレッジ外（そのdem_typeの整備区域外）。エラーではなく「このタイルには
                # 無い」として扱い、呼び出し元が次の優先順位へフォールバックする。恒久的に
                # 正しい事実のため、呼び出し元は_tile_grid_cacheへNoneとして恒久キャッシュしてよい。
                return _COVERAGE_GAP
            response.raise_for_status()
            text = response.text
        except httpx.HTTPError as exc:
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            # 一時的な通信エラー。Noneを返すが、404（_COVERAGE_GAP）とは区別し
            # 呼び出し元に恒久キャッシュさせない。
            return None

        grid = _parse_dem_tile_text(text)
        tile_cache.set(path, text.encode("utf-8"), DEM_TILE_CONTENT_TYPE)
        return grid
