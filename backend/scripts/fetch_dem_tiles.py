"""標高タイルを配信元から手元へ写す（取込とは分ける）。

取込のトランザクションの中でHTTPを叩くと、関東全域（z15で約6万枚）では外部の一時的な
失敗ひとつで1〜2時間ぶんがやり直しになる。ここで先に写しておけば、取込はローカルの
ファイルを読むだけになり、失敗しても**欠けた分だけ**取り直せる。

**何度実行しても安全で、終わる。**

- 手元にあるタイルは叩かない
- どの製品にも無いタイル（区域外）は印を置き、次からは叩かない
- 一時的な失敗は`--attempts`回で打ち切り、件数を報告して終える。無限に粘らない

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\fetch_dem_tiles.py
    .venv\\Scripts\\python.exe scripts\\fetch_dem_tiles.py --profile path/to/profile.yaml
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.dem_tile_store import (  # noqa: E402
    PRODUCT_PRIORITY,
    TILE_ROOT,
    TILE_URL,
    is_absent,
    mark_absent,
    stored_product,
    write_tile,
)
from app.batch._common import (  # noqa: E402
    PROGRESS_INTERVAL_SECONDS,
    format_progress,
)
from app.batch.source_profile import load_source_profile  # noqa: E402
from app.domain.region import BoundingBox, tiles_covering_bbox  # noqa: E402

logger = logging.getLogger("ridecompass.fetch_dem_tiles")

#: 配信元へ並べてよい数の上限。公共サービスなので控えめにする。
_MAX_CONCURRENT = 8

#: 1タイルあたりの試行回数の既定。超えたらそのタイルは諦め、件数として報告する。
_DEFAULT_ATTEMPTS = 3

_REQUEST_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=10.0)


async def _fetch_one(client: httpx.AsyncClient, zoom: int, x: int, y: int,
                     first: str) -> tuple[str, str] | None:
    """(実際に当たった製品, 本文)。どの製品にも無ければNone。"""
    order = [first] + [p for p in PRODUCT_PRIORITY if p != first]
    for product in order:
        response = await client.get(
            TILE_URL.format(product=product, z=zoom, x=x, y=y), timeout=_REQUEST_TIMEOUT)
        if response.status_code == 200:
            return product, response.text
        if response.status_code != 404:
            response.raise_for_status()
    return None


async def _fetch_missing(root: Path, zoom: int, product: str,
                        tiles: list[tuple[int, int]], attempts: int) -> dict[str, int]:
    """手元に無いタイルだけ取りに行く。結果の内訳を返す。"""
    wanted = [
        (x, y) for x, y in tiles
        if stored_product(root, zoom, x, y) is None and not is_absent(root, zoom, x, y)
    ]
    counts = {"既にある": len(tiles) - len(wanted), "取得": 0, "区域外": 0, "諦めた": 0}
    if not wanted:
        return counts

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    started = time.perf_counter()

    async with httpx.AsyncClient() as client:
        async def one(x: int, y: int) -> None:
            for attempt in range(1, attempts + 1):
                try:
                    async with semaphore:
                        result = await _fetch_one(client, zoom, x, y, product)
                except (httpx.HTTPError, httpx.StreamError) as exc:
                    if attempt == attempts:
                        logger.warning("諦めた z%d/%d/%d: %s", zoom, x, y, exc)
                        counts["諦めた"] += 1
                        return
                    await asyncio.sleep(2 ** attempt)
                    continue
                if result is None:
                    mark_absent(root, zoom, x, y)
                    counts["区域外"] += 1
                else:
                    write_tile(root, result[0], zoom, x, y, result[1])
                    counts["取得"] += 1
                return

        last_report = started
        for start in range(0, len(wanted), _MAX_CONCURRENT * 8):
            chunk = wanted[start:start + _MAX_CONCURRENT * 8]
            await asyncio.gather(*(one(x, y) for x, y in chunk))
            now = time.perf_counter()
            done = counts["取得"] + counts["区域外"] + counts["諦めた"]
            if now - last_report < PROGRESS_INTERVAL_SECONDS and done < len(wanted):
                continue
            last_report = now
            logger.info("進捗 %s", format_progress(done, len(wanted), now - started, "枚"))
    return counts


async def run(profile_path: Path | None, attempts: int) -> int:
    profile = load_source_profile(profile_path)
    spec = profile.source("dem")
    grid = spec.grid or {}
    zoom = int(grid["zoom"])
    product = str(grid["product"])
    low_lat, low_lon, high_lat, high_lon = profile.target.bbox
    bbox = BoundingBox(min_latitude=low_lat, min_longitude=low_lon,
                       max_latitude=high_lat, max_longitude=high_lon)
    tiles = list(tiles_covering_bbox(bbox, zoom))
    root = TILE_ROOT
    logger.info("標高タイル: product=%s zoom=%d 対象%d枚 / 置き場 %s",
                product, zoom, len(tiles), root)

    counts = await _fetch_missing(root, zoom, product, tiles, attempts)
    logger.info("完了: %s", " / ".join(f"{k} {v:,}枚" for k, v in counts.items()))
    if counts["諦めた"]:
        logger.warning("諦めたタイルがあります。もう一度実行すると、その分だけ取りに行きます")
        return 1
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="標高タイルを手元へ写す")
    parser.add_argument("--profile", default=None, type=Path)
    parser.add_argument("--attempts", default=_DEFAULT_ATTEMPTS, type=int,
                        help="1タイルあたりの試行回数。超えたら諦めて件数で報告する")
    args = parser.parse_args()
    return asyncio.run(run(args.profile, args.attempts))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
