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
# タイル仕様（2026-08-23、GSI公式ページ・実タイル取得で確認済み）:
# - URL: https://cyberjapandata.gsi.go.jp/xyz/dem/{z}/{x}/{y}.txt （統合dem種別、z=14固定）。
#   この統合種別はDEM5A/5B/5C/10Bの優先順位フォールバックをGSIサーバー側で既に行うため、
#   アプリ側で独自のフォールバック連鎖（DEM5A→5B→10B等）を実装する必要がない
#   （docs/external-data-sources-review-2026-08-16.md 4.2節の当初案より単純化できた）。
# - 本文: 256行×256列のカンマ区切り数値（単位m、小数点2桁）。欠測画素は"e"。
# - z=14でのタイル1辺は緯度により変わるが日本付近で概ね1〜2km、1画素あたり数m〜10m程度。
#   OSM形状点間隔（多くは5m超）に対し十分な粒度で、標高評価の本格精査（2026-08-16調査）が
#   「1m格子化の恩恵はほぼ出ない」と結論した内容とも整合する。
#
# キャッシュは2段: 生タイル本文はinfrastructure/tile_cache.py（ファイルキャッシュ、
# TTLなし。DEMは不変データのため）。パース済みグリッド（256x256のfloat|Noneの二次元配列）は
# さらにプロセス内メモリにも保持し（_tile_grid_cache）、1リクエスト内で近接する複数の
# サンプル点が同じタイルを共有する場合に、ファイル読み出し・パースを都度繰り返さない
# ようにする（サイズ上限は設けていない。対象範囲が関東圏に留まる現状の運用規模では
# 実害が無いと判断、他のプロセス内メモリキャッシュ[weather_client.py等]と同じ割り切り。
# 将来対象範囲が全国規模まで広がる場合は上限つきLRUへの変更を検討する）。
DEM_TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/dem/{z}/{x}/{y}.txt"
DEM_ZOOM = 14
DEM_TILE_SIZE = 256
DEM_MISSING_MARKER = "e"
DEM_TILE_CONTENT_TYPE = "text/plain; charset=utf-8"

_tile_grid_cache: dict[tuple[int, int], list[list[float | None]] | None] = {}


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
    """

    async def get_elevation(self, client: httpx.AsyncClient, point: Coordinates, refresh: bool = False) -> float | None:
        tile_x, tile_y, px, py = lonlat_to_tile_pixel(point.longitude, point.latitude, DEM_ZOOM, DEM_TILE_SIZE)

        # キャッシュヒット時のelapsedは実質プロセス内グリッドキャッシュ/ファイルキャッシュの
        # 所要時間になるため、このログ・統計が標高キャッシュの効き具合の観測点を兼ねる
        # （旧SQLite点キャッシュ時代のlog_external_call呼び出しと同じ位置づけ）。
        with log_external_call("elevation:gsi-dem", tile_x=tile_x, tile_y=tile_y) as fields:
            grid = await self._get_tile_grid(client, tile_x, tile_y, refresh=refresh, fields=fields)
            if grid is None:
                fields["result"] = "no_elevation"
                return None
            elevation = _bilinear_interpolate(grid, px, py)
            fields["result"] = "ok" if elevation is not None else "no_elevation"
            return elevation

    async def _get_tile_grid(
        self, client: httpx.AsyncClient, tile_x: int, tile_y: int, *, refresh: bool, fields: dict
    ) -> list[list[float | None]] | None:
        cache_key = (tile_x, tile_y)
        if not refresh and cache_key in _tile_grid_cache:
            fields["cache"] = "hit"
            return _tile_grid_cache[cache_key]

        path = f"gsi/dem/{DEM_ZOOM}/{tile_x}/{tile_y}.txt"
        if not refresh:
            cached = tile_cache.get(path)
            if cached is not None:
                fields["cache"] = "hit"
                content, _content_type = cached
                grid = _parse_dem_tile_text(content.decode("utf-8"))
                _tile_grid_cache[cache_key] = grid
                return grid

        fields["cache"] = "miss"
        grid = await self._fetch_tile(client, tile_x, tile_y, path, fields)
        _tile_grid_cache[cache_key] = grid
        return grid

    async def _fetch_tile(
        self, client: httpx.AsyncClient, tile_x: int, tile_y: int, path: str, fields: dict
    ) -> list[list[float | None]] | None:
        url = DEM_TILE_URL.format(z=DEM_ZOOM, x=tile_x, y=tile_y)
        try:
            response = await client.get(url)
            fields["status"] = getattr(response, "status_code", None)
            if response.status_code == 404:
                # カバレッジ外（海上・データ未整備地域）。エラーではなく「標高データなし」
                # として扱う（旧GSI点APIの「守備範囲外は"-----"」と同じ位置づけ）。
                return None
            response.raise_for_status()
            text = response.text
        except httpx.HTTPError as exc:
            fields["error"] = repr(exc)
            fields["error_type"] = error_type_label(exc)
            return None

        grid = _parse_dem_tile_text(text)
        tile_cache.set(path, text.encode("utf-8"), DEM_TILE_CONTENT_TYPE)
        return grid
