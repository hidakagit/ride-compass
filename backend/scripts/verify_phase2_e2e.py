"""Phase 2検証: 地域路面レイヤーのタイル生成がPostGISだけで完結することを実DBで確認する。

前提: app/batch/import_pbf.pyで東京都心bbox（35.60,139.65,35.75,139.85）を取込済み。

実行方法（backendディレクトリから）:
    $env:DATABASE_URL = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass"
    .venv\\Scripts\\python.exe scripts\\verify_phase2_e2e.py

検証項目:
1. create_tables()の再実行で旧GINインデックスが削除されDBサイズが縮むこと（容量予算対応）
2. 取込範囲内のタイル: PostGISだけでMVTが生成され、地物が入っており、Overpass呼び出し0回
3. 取込範囲外のタイル（フォールバック無効): 空タイルが返り、Overpass呼び出し0回
4. 取込範囲外のタイル（フォールバック有効): Overpass（スタブ）へフォールバックすること

ファイルキャッシュは一時ディレクトリへ差し替えるため、実運用のタイルキャッシュを汚さない。
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mapbox_vector_tile  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.domain.region import ROAD_TILE_MIN_ZOOM, BoundingBox, tiles_covering_bbox  # noqa: E402
from app.infrastructure import tile_cache  # noqa: E402
from app.infrastructure.database import get_engine, get_session_factory  # noqa: E402
from app.infrastructure.road_graph_repository import RoadGraphRepository, create_tables  # noqa: E402
from app.services.region_service import RegionService  # noqa: E402

VERIFY_ZOOM = 14  # 表示ズーム範囲（12-15）の代表値

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    _results.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}: {name}" + (f" -- {detail}" if detail and not ok else ""))


def tile_at(lat: float, lon: float, z: int) -> tuple[int, int]:
    tiles = tiles_covering_bbox(
        BoundingBox(min_latitude=lat, min_longitude=lon, max_latitude=lat, max_longitude=lon), z
    )
    return tiles[0]


def feature_count(tile_bytes: bytes) -> int:
    if not tile_bytes:
        return 0
    decoded = mapbox_vector_tile.decode(tile_bytes)
    return sum(len(layer["features"]) for layer in decoded.values())


class FailingOverpassClient:
    def __init__(self):
        self.call_count = 0

    async def get_roads(self, client, bbox):
        self.call_count += 1
        return None


async def main() -> int:
    # 実運用のファイルキャッシュ（backend/data/tile_cache）を読まない・汚さない
    tile_cache.CACHE_DIR = Path(tempfile.mkdtemp(prefix="phase2_tile_cache_"))

    engine = get_engine()
    session_factory = get_session_factory()
    try:
        print("== 1. スキーマ更新（GINインデックス削除）と容量 ==")
        async with engine.connect() as conn:
            size_before = (await conn.execute(text("SELECT pg_database_size(current_database())"))).scalar()
        await create_tables(engine)
        async with engine.connect() as conn:
            size_after = (await conn.execute(text("SELECT pg_database_size(current_database())"))).scalar()
            gin_exists = (
                await conn.execute(
                    text("SELECT 1 FROM pg_indexes WHERE indexname = 'ix_osm_raw_ways_node_ids'")
                )
            ).scalar()
        check("旧GINインデックス（ix_osm_raw_ways_node_ids）が削除されている", gin_exists is None)
        print(f"  DBサイズ: {size_before / 1e6:.0f}MB -> {size_after / 1e6:.0f}MB")
        check("DBサイズが300MB予算内", size_after < 300_000_000, f"{size_after / 1e6:.0f}MB")

        print("== 2. 取込範囲内タイル: PostGISのみで生成 ==")
        overpass = FailingOverpassClient()
        x, y = tile_at(35.681, 139.767, VERIFY_ZOOM)  # 東京駅付近（取込bbox内）
        async with session_factory() as session:
            service = RegionService(
                overpass, http_client=None, repository=RoadGraphRepository(session)
            )
            tile_bytes = await service.get_road_surface_tile(VERIFY_ZOOM, x, y)
            count = feature_count(tile_bytes)
            check("MVTに路面地物が含まれる", count > 0, f"features={count}")
            check("Overpassは呼ばれない", overpass.call_count == 0, f"calls={overpass.call_count}")
            print(f"  tile z{VERIFY_ZOOM}/{x}/{y}: {len(tile_bytes)} bytes, {count} features")

            # 2回目はファイルキャッシュから返る（DBへも行かない）ことを軽く確認
            tile_bytes_2 = await service.get_road_surface_tile(VERIFY_ZOOM, x, y)
            check("2回目はキャッシュから同一タイルが返る", tile_bytes_2 == tile_bytes)

        print("== 3. 取込範囲外タイル（フォールバック無効）: 空タイル・Overpassゼロ ==")
        overpass = FailingOverpassClient()
        ox, oy = tile_at(34.70, 137.73, VERIFY_ZOOM)  # 浜松付近（取込範囲外）
        async with session_factory() as session:
            service = RegionService(
                overpass, http_client=None, repository=RoadGraphRepository(session),
                overpass_fallback_enabled=False,
            )
            empty_tile = await service.get_road_surface_tile(VERIFY_ZOOM, ox, oy)
            check("範囲外は空タイル", feature_count(empty_tile) == 0)
            check("範囲外でもOverpassは呼ばれない（フォールバック無効）", overpass.call_count == 0)

        print("== 4. 取込範囲外タイル（フォールバック有効）: Overpassへフォールバック ==")
        overpass = FailingOverpassClient()
        async with session_factory() as session:
            service = RegionService(
                overpass, http_client=None, repository=RoadGraphRepository(session),
                overpass_fallback_enabled=True,
            )
            await service.get_road_surface_tile(VERIFY_ZOOM, ox, oy)
            check("範囲外はOverpassへフォールバックする", overpass.call_count == 1,
                  f"calls={overpass.call_count}")

        # 表示ズーム下限（=カバレッジズームと同一のz12）でも動くことを確認
        print("== 5. z12（カバレッジズームと同一）のタイル ==")
        overpass = FailingOverpassClient()
        zx, zy = tile_at(35.681, 139.767, ROAD_TILE_MIN_ZOOM)
        async with session_factory() as session:
            service = RegionService(
                overpass, http_client=None, repository=RoadGraphRepository(session)
            )
            z12_tile = await service.get_road_surface_tile(ROAD_TILE_MIN_ZOOM, zx, zy)
            check("z12タイルもPostGISのみで生成される",
                  feature_count(z12_tile) > 0 and overpass.call_count == 0)
    finally:
        await engine.dispose()

    failed = [r for r in _results if not r[1]]
    print()
    print(f"結果: {len(_results) - len(failed)}/{len(_results)} PASS")
    for name, _, detail in failed:
        print(f"  FAIL: {name}" + (f" -- {detail}" if detail else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
