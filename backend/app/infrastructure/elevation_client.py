import asyncio
from collections import OrderedDict

import httpx

from app.domain.region import lonlat_to_tile_pixel
from app.domain.route import Coordinates
from app.infrastructure import tile_cache
from app.infrastructure.debug_log import error_type_label, log_external_call

# 改善計画T10（DEMタイル化＋標高キャッシュ1系統化）。以前はGSI点標高API
# （getelevation.php）を1地点ずつ呼んでいたが、Road Graph全体（数万エッジ）へ標高を
# 付与するには非現実的な回数の外部呼び出しが必要になることが判明した（改善計画T218a、
# 実測: 480エッジに対し2,880回＝1エッジ平均6点）。GSIのDEMタイル（統合`dem`種別、
# テキスト形式）を範囲ごと取得しローカルで双線形補間する方式へ切り替え、外部呼び出し
# 回数をタイル単位（近接点は同一タイルを共有）へ削減する。呼び出し側インターフェース
# （get_elevation(client, point, refresh=False) -> float|None）は変更しない。
#
# 改善計画T576: 複数地点をまとめて取得する`get_elevations`を追加。`get_elevation`
# （1地点版）は内部的に`get_elevations([point])`を呼ぶ薄いラッパーになった
# （結果は完全に同一、地点数が1件のぶんタイル単位バッチ化の恩恵は無い）。
#
# タイル仕様（2026-08-23、GSI公式ページ・実タイル取得で確認済み。**当初は「統合dem種別が
# DEM5A/5B/5C/10Bの優先順位フォールバックをGSIサーバー側で行う」と判断していたが誤りで、
# 2026-08-23の再検証（ユーザー指摘）で実タイル比較により訂正した**）:
# - URL: https://cyberjapandata.gsi.go.jp/xyz/{type}/{z}/{x}/{y}.txt。`type`は"dem"単体ではなく
#   優先順位付きで複数種別（DEM_TYPE_PRIORITY）を順に試す。実測で判明した事実:
#   - `dem`（サフィックス無し）はDEM5A等を統合したものではなく、DEM10B相当の別データセット
#     （z=15で404、DEM10Bの最大ズーム14と一致）。同一タイルで`dem5a`と`dem`が異なる値を返す
#     ことを都心部で確認済み（`dem5a`はより高精度な値、`dem`は明らかに粗い値）。
#   - `dem5a`/`dem5b`/`dem5c`は独立したエンドポイントとして直接クエリでき、非対応エリアでは
#     （タイル丸ごと）404を返す（黙って粗いデータに劣化するのではなく明示的に「無い」ことが
#     わかる）。GSI公式の優先順位（DEM1A→DEM5A→DEM5B/C→DEM10B。DEM1Aは2026-08-16調査により
#     本アプリのサンプリング密度では恩恵が薄いため対象外と判断済み）に沿い、
#     dem5a→dem5b→dem5c→dem の順にタイル単位でフォールバックする（DEM_TYPE_PRIORITY）。
#   - 上記4種別はいずれもz=14で200を返すことを確認済み（DEM5A/5B/5CはGSI仕様上の最大
#     ズームは15だが、z=14でも取得できる。z間で座標系を切り替える複雑さを避けるため、
#     全種別をz=14固定で扱う）。
# - 本文: 256行×256列のカンマ区切り数値（単位m、小数点2桁）。欠測画素は"e"。
# - z=14でのタイル1辺は緯度により変わるが日本付近で概ね1〜2km、1画素あたり数m〜10m程度。
#   OSM形状点間隔（多くは5m超）に対し十分な粒度で、標高評価の本格精査（2026-08-16調査）が
#   「1m格子化の恩恵はほぼ出ない」と結論した内容とも整合する。
#
# キャッシュは2段: 生タイル本文はinfrastructure/tile_cache.py（ファイルキャッシュ、
# TTLなし。DEMは不変データのため）。パース済みグリッド（256x256のfloat|Noneの二次元配列）は
# さらにプロセス内メモリにも保持し（_tile_grid_cache、キー=(type, tile_x, tile_y)）、
# 1リクエスト内で近接する複数のサンプル点が同じタイルを共有する場合に、ファイル読み出し・
# パースを都度繰り返さないようにする。
#
# 上限つきLRU（graph_material_cache.py: _LRUCacheと同じ設計）。
# precompute_elevation_attributes.py（全道路網の一括計算バッチ）はEdgeを地理的に
# 並べ替えず処理するため、上限が無いと対象範囲全体に散らばったタイルを溜め込み続け
# メモリを枯渇させる（経緯はdocs/tasks/T575.md参照）。ディスク側（tile_cache.py）は
# 既にTTL無しで永続化済みのため、ここから追い出されてもネットワーク呼び出し無しの
# ローカル再パースだけで復元できる——上限に達した場合はLRUで最も長く使われていない
# エントリから自然に破棄される。
DEFAULT_MAX_TILE_GRIDS = 500

# GSIへの同時リクエスト数（改善計画T576。旧`ElevationAttributeService.
# MAX_CONCURRENT_REQUESTS`から移設——点単位ではなくタイル単位のフェッチへ
# 制限を掛ける方が「同時に問い合わせている実リクエスト数」の実態に合う）。
MAX_CONCURRENT_REQUESTS = 5
DEM_TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/{type}/{z}/{x}/{y}.txt"
DEM_TYPE_PRIORITY = ("dem5a", "dem5b", "dem5c", "dem")
DEM_ZOOM = 14
DEM_TILE_SIZE = 256
DEM_MISSING_MARKER = "e"
DEM_TILE_CONTENT_TYPE = "text/plain; charset=utf-8"

_tile_grid_cache: "OrderedDict[tuple[str, int, int], list[list[float | None]] | None]" = OrderedDict()

# 改善計画T576: 同一タイルへの同時フェッチを1回へ束ねる（single-flight）。
# `get_elevations`が多数の点を1回のタイル取得へまとめても、複数の未取得タイルを
# 並行フェッチする際に同じタイルが重複して選ばれることはあり得るほか、異なる
# リクエスト（本番backendの並行route生成）が同時に同じ未取得タイルへ到達する
# ケースはこの束ねが無いと重複GET・重複パースになる（docs/tasks/T576.md参照）。
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

    改善計画T425: `_fetch_tile`が一時的な通信エラー（タイムアウト・5xx等）でも同じく
    `None`を返していたため、`_get_tile_grid`がその場限りの障害まで`_tile_grid_cache`へ
    「このタイルにはデータが無い」として恒久キャッシュしてしまい、プロセスが再起動する
    まで標高が永久にNone固定になるバグがあった。整備区域外（404、恒久的に正しい）と
    通信エラー（一時的、次回リトライすべき）を区別するためのセンチネル。
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
    任意地点の標高はタイル内を双線形補間して求める（改善計画T10）。

    標高は付随情報のため、取得できなかった場合（守備範囲外・通信エラー等）は
    例外を投げず`None`を返す（呼び出し元でルート自体は生かす）。

    呼び出し元がhttpx.AsyncClientを渡す設計にしている。1ルートあたり十数地点を
    問い合わせるため、リクエストごとに新規クライアント（＝新規TLSハンドシェイク）を
    作ると大幅に遅くなることが実機検証で判明したため、コネクションを使い回す
    （T10移行前と同じ理由・同じ設計をタイル取得にも引き継ぐ）。

    実際のGSIへの同時リクエスト数は`MAX_CONCURRENT_REQUESTS`で絞る（インスタンス
    単位、`ElevationAttributeService`と同じ流儀）。改善計画T576でタイル単位の
    バッチ取得（`get_elevations`）を追加した際、点単位ではなくタイル単位の
    フェッチへこの制限を移した。
    """

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def get_elevation(self, client: httpx.AsyncClient, point: Coordinates, refresh: bool = False) -> float | None:
        results = await self.get_elevations(client, [point], refresh=refresh)
        return results[0]

    async def get_elevations(
        self, client: httpx.AsyncClient, points: list[Coordinates], refresh: bool = False
    ) -> list[float | None]:
        """複数地点の標高を、地点ごとのasyncioタスクではなくタイル単位でまとめて取得する
        （改善計画T576）。1地点ずつ`get_elevation`する場合と結果は同一（同じ
        `DEM_TYPE_PRIORITY`優先順位・同じ双線形補間）だが、地点数ぶんのasyncioタスク
        生成・`log_external_call`呼び出しが無く、未取得のタイルだけをまとめて非同期
        取得するためキャッシュヒット時のコストが大幅に小さい（docs/tasks/T576.md参照）。

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

        同一タイルへの同時呼び出しは1回のフェッチへ束ねる（single-flight、
        改善計画T576）。フェッチが一時的な通信エラーで失敗した場合は何もキャッシュ
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
                # 無い」として扱い、呼び出し元が次の優先順位へフォールバックする
                # （旧GSI点APIの「守備範囲外は"-----"」と同じ位置づけ）。恒久的に正しい
                # 事実のため、呼び出し元は_tile_grid_cacheへNoneとして恒久キャッシュしてよい。
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
