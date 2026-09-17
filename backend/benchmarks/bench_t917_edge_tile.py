"""路面タイルをway単位からedge単位へ移したときの費用を、実データ・実DB接続に対して測る。

今の路面タイル（`_ROAD_SURFACE_TILE_MVT_SQL`）は`osm_raw_ways`のgeometryを焼いており、
地図が塗れる最小の単位はway丸ごとである。backendが計算する単位（`road_edges`）・ルート
確定後にフロントが受け取る単位（`RouteSegmentDetail`）はどちらも区間のため、区間ごとの値
（勾配・向かい風・予想速度）を地図へ出すたびに「ルート前のway近似」と「ルート後の区間実値」
を作り分けることになる。単位を揃えられるかは**タイルがどれだけ重くなるか**で決まるため、
移行を決める前にそこだけを測る。

測るのは3つ。
- **大きさ**: 同じタイルをway版・edge版で焼いたときのバイト数とフィーチャー数。
- **生成時間**: 同じSQLの実行時間（キャッシュを経由しない生の生成）。
- **重複**: `road_edges`はforward/backwardを別行で持つため、そのまま焼くと同じ形状が
  2本入る。除外した場合の数も併せて出す。

edge版のSQLは**このモジュールが計測のために組み立てるもの**で、本番の配信経路はまだway版の
ままである。way単位で意味を持つ材料（`intersection_count_per_km`等、way全体を母数に数えた
値）をedgeへ複製したときの意味のずれは、この計測では扱わない（数字が許容範囲だった場合に
移行タスク側で判断する）。

前提: 対象タイルが`app/batch/import_pbf.py`で取込済みであること（docs/osm-pbf-import.md
参照。カバー範囲外はSKIPする）。

実行方法（backend/ディレクトリから。.envのDATABASE_URLはSupabase向けのため、ローカルDBへ
明示的に上書きする）:
    $env:DATABASE_URL = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass"
    .venv\\Scripts\\python.exe -m benchmarks.bench_t917_edge_tile
"""

from __future__ import annotations

import asyncio
import gzip
import time
from dataclasses import dataclass

from sqlalchemy import text

from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM
from app.infrastructure.database import get_session_factory
from app.infrastructure.response_compression import DEFAULT_COMPRESS_LEVEL
from app.infrastructure.vector_tile import ROAD_SURFACE_LAYER_NAME

MVT_EXTENT = 4096

# 取込済み範囲（docs/osm-pbf-import.md）の中から、道路の密度が異なる地点を選ぶ。
# 密度が費用を決めるため、1タイルだけでは判断しない。座標は各地点の緯度経度から
# 通常のWeb Mercatorのタイル式で求めたもの。
TARGET_TILES: list[tuple[str, int, int, int]] = [
    ("東京駅 z15", 15, 29105, 12903),
    ("板橋区 z15", 15, 29100, 12895),
    ("八王子 z15", 15, 29065, 12906),
    ("東京駅 z14", 14, 14552, 6451),
    ("板橋区 z14", 14, 14550, 6447),
    ("八王子 z14", 14, 14532, 6453),
    ("東京駅 z13", 13, 7276, 3225),
    ("八王子 z13", 13, 7266, 3226),
    ("東京駅 z12", 12, 3638, 1612),
]


def _tile_sql(geometry_source: str) -> str:
    """way版・edge版で**geometryの出どころだけ**が違うMVT生成SQLを組み立てる。

    プロパティは両版で同じ集合にする——比べたいのは「単位を変えると何バイト増えるか」で
    あって、プロパティの多寡ではない。
    """
    return f"""
        SELECT ST_AsMVT(mvt.*, :layer_name, :extent, 'geom') FROM (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(src.geom, 3857), ST_TileEnvelope(:z, :x, :y), :extent, 256, true
                ) AS geom,
                src.osm_way_id AS osm_way_id,
                src.feature_key AS feature_key,
                w.highway AS highway,
                w.surface AS surface
            FROM ({geometry_source}) src
            JOIN osm_raw_ways w ON w.osm_way_id = src.osm_way_id
        ) AS mvt
    """


# **空間フィルタは各sourceの中に置く**。外側に置くと、重複排除のDISTINCT ONが
# road_edges全件に対して走ってから絞られ、タイルの中身に依存しない一定の時間
# （実測8.3〜9.8秒）を測ることになる。同じ物理区間の両方向は同じ形状のため、
# 先に絞ってから重複排除しても結果は変わらない。
_TILE_BBOX = "ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326)"

# way版: 今の配信と同じ単位（osm_raw_ways 1行 = 1フィーチャー）。
_WAY_SOURCE = f"""
    SELECT w.geom AS geom, w.osm_way_id AS osm_way_id, w.osm_way_id::text AS feature_key
    FROM osm_raw_ways w
    WHERE w.geom IS NOT NULL AND ST_Intersects(w.geom, {_TILE_BBOX})
"""

# edge版: road_edges 1行 = 1フィーチャー。forward/backwardの両方を含む。
_EDGE_SOURCE_WITH_DUPLICATES = f"""
    SELECT re.geom AS geom, re.osm_way_id AS osm_way_id, re.edge_id AS feature_key
    FROM road_edges re
    WHERE re.osm_way_id IS NOT NULL AND ST_Intersects(re.geom, {_TILE_BBOX})
"""

# edge版（重複排除）: 同じ物理区間の逆方向を落とす。**両端ノードの組で見分ける**
# ——geometryの正規化（ST_Normalize）はLINESTRINGの向きを揃えないため、形状では
# forward/backwardを同一と判定できない。どちらを残すかはedge_id昇順で決定論的に固定する。
_EDGE_SOURCE_DEDUPED = f"""
    SELECT DISTINCT ON (
        re.osm_way_id, LEAST(re.from_node_id, re.to_node_id), GREATEST(re.from_node_id, re.to_node_id)
    )
        re.geom AS geom, re.osm_way_id AS osm_way_id, re.edge_id AS feature_key
    FROM road_edges re
    WHERE re.osm_way_id IS NOT NULL AND ST_Intersects(re.geom, {_TILE_BBOX})
    ORDER BY re.osm_way_id, LEAST(re.from_node_id, re.to_node_id), GREATEST(re.from_node_id, re.to_node_id), re.edge_id
"""


_COVERAGE_SQL = text(
    """
    SELECT EXISTS(
        SELECT 1 FROM road_graph_tiles WHERE zoom = :coverage_zoom AND x = :coverage_x AND y = :coverage_y
    ) AS covered
    """
)


@dataclass
class TileMeasurement:
    label: str
    variant: str
    raw_bytes: int
    gzip_bytes: int
    feature_count: int
    elapsed_s: float


def _coverage_ancestor(z: int, x: int, y: int, coverage_zoom: int = 12) -> tuple[int, int, int]:
    """road_graph_tilesがカバレッジを記録しているズーム（z12）の祖先タイルへ畳む。"""
    if z <= coverage_zoom:
        return z, x, y
    shift = z - coverage_zoom
    return coverage_zoom, x >> shift, y >> shift


async def _measure(session, label: str, variant: str, source: str, z: int, x: int, y: int) -> TileMeasurement:
    params = {"layer_name": ROAD_SURFACE_LAYER_NAME, "extent": MVT_EXTENT, "z": z, "x": x, "y": y}
    started = time.perf_counter()
    result = await session.execute(text(_tile_sql(source)), params)
    content = result.scalar_one() or b""
    elapsed = time.perf_counter() - started

    # 本番は`response_compression.py`がベクタタイルをgzipして返す。転送量で判断するため、
    # 同じcompresslevelで縮めた後のバイト数も測る（重複したプロパティ索引はよく縮むため、
    # 生バイトの比率は転送量の比率を過大に見せる）。
    gzipped = gzip.compress(bytes(content), compresslevel=DEFAULT_COMPRESS_LEVEL)

    count_sql = text(f"SELECT count(*) FROM ({source}) src")
    feature_count = (await session.execute(count_sql, {"z": z, "x": x, "y": y})).scalar_one()
    return TileMeasurement(label, variant, len(content), len(gzipped), feature_count, elapsed)


async def main() -> None:
    session_factory = get_session_factory()
    rows: list[TileMeasurement] = []
    skipped: list[str] = []

    async with session_factory() as session:
        for label, z, x, y in TARGET_TILES:
            if not (ROAD_TILE_MIN_ZOOM <= z <= ROAD_TILE_MAX_ZOOM):
                skipped.append(f"{label}: 配信ズーム範囲外")
                continue
            cz, cx, cy = _coverage_ancestor(z, x, y)
            covered = (
                await session.execute(_COVERAGE_SQL, {"coverage_zoom": cz, "coverage_x": cx, "coverage_y": cy})
            ).scalar_one()
            if not covered:
                skipped.append(f"{label}: 取込範囲外（road_graph_tilesにz{cz}/{cx}/{cy}が無い）")
                continue
            for variant, source in (
                ("way（現行の単位）", _WAY_SOURCE),
                ("edge（両方向そのまま）", _EDGE_SOURCE_WITH_DUPLICATES),
                ("edge（重複排除）", _EDGE_SOURCE_DEDUPED),
            ):
                rows.append(await _measure(session, label, variant, source, z, x, y))

    print("## 路面タイル way単位 vs edge単位（実DB・実データ）")
    print()
    print("プロパティは3版とも同じ集合へ揃えてある（比べたいのは単位の違いであって、")
    print("プロパティの多寡ではない）。本番タイルはLEFT JOINでより多くの列を持つため、")
    print("**絶対バイト数は本番と一致しない。way比だけを移行判断に使うこと**。")
    print(f"gzipは本番と同じcompresslevel={DEFAULT_COMPRESS_LEVEL}。**判断はgzip比で行う**")
    print("（本番はベクタタイルを圧縮して配信するため、転送量はこちらが正しい）。")
    print()
    if skipped:
        for line in skipped:
            print(f"SKIP {line}")
        print()
    if not rows:
        print("計測できたタイルが無い。DATABASE_URLと取込範囲を確認すること。")
        return

    header = (
        f"{'タイル':<14}{'単位':<24}{'生バイト':>11}{'gzip':>10}"
        f"{'features':>10}{'生成s':>8}{'gzip比':>8}"
    )
    print(header)
    print("-" * len(header))
    baseline: dict[str, TileMeasurement] = {}
    for row in rows:
        if row.variant.startswith("way"):
            baseline[row.label] = row
        base = baseline.get(row.label)
        ratio = f"{row.gzip_bytes / base.gzip_bytes:.2f}x" if base and base.gzip_bytes else "-"
        print(
            f"{row.label:<14}{row.variant:<24}{row.raw_bytes:>11,}{row.gzip_bytes:>10,}"
            f"{row.feature_count:>10,}{row.elapsed_s:>8.3f}{ratio:>8}"
        )


if __name__ == "__main__":
    asyncio.run(main())
