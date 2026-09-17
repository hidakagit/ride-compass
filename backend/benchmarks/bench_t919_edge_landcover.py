"""wayの中で土地被覆が区間ごとにどれだけばらつくかを、実データ・実DB接続に対して測る。

[T918](../../docs/tasks/T918.md)で路面タイルの単位は区間（`road_edges`）になり、密度
（事故・交差点・POI）は区間の実測から焼くようになった。土地被覆（`*_pct`）だけが
way全体の平均のまま全区間へ複製されている——`way_landcover`しか無く、区間単位の集計が
存在しないためである。

区間単位で持ち直すには`precompute_way_landcover.py`に相当する重いバッチ（rasterioで
全区間ぶんラスタを読む）をもう1本増やし、テーブル・鮮度台帳・タイルの焼き込みを足すことに
なる。**払う前に、均されて消えている差が実際どれだけあるかを測る。**

**この計測は実装とほぼ同じ計算をする**（区間ごとの土地被覆を知るには区間ごとにラスタを
読むしかない）。違いは行を書かずに、way内のばらつきだけを集計して捨てる点である。
`build_ring`・`count_pixels_in_ring`・`class_percentages`はバッチと同じものを呼ぶ——
ここで別の数え方をすると、測った差が実装で再現しない。

測るのは、配線済みクラス（`WIRED_LANDCOVER_KEYS`）ごとの**way内レンジ**
（そのwayの区間の最大値−最小値、ポイント）。way全体の平均で塗ることによって消えている
差がこれである。判断の目安:

- レンジが小さい（数ポイント）なら、区間単位で持ってもほぼ同じ色になり、このタスクは不要。
- 大きいwayが無視できない割合で存在するなら、そのぶんが今は見えていない。

区間を2本以上持つwayだけを対象にする（1区間のwayはway平均と一致し、定義上ばらつかない）。

前提: 対象範囲が`app/batch/import_pbf.py`で取込済みで、`presplit_road_graph.py`が
`road_edges`を埋めていること。ラスタは`scripts/fetch_lulc_raster.py`が取得する。

**本番VM上では実行しない。** バッチはDBホスト上では走らせない前提で
（docs/tasks/T624.md論点3。本番DBはbackendと同じVMに同居し、重いバッチでVM全体がOOMに
なった実績がある）、これはバッチ本体と同じラスタ処理をする。本番イメージにも入っていない
（`backend/Dockerfile`は`benchmarks/`をコピーせず、`pyproj`は`requirements-batch.txt`側）。

**測る対象は地形の性質**（way内で土地被覆がどれだけばらつくか）のため、同じ地域なら開発DBと
本番で同じ値になる。開発機のDBで回せばよい。

`edge_landcover`が既に埋まっているDBに対しては、この計測器は要らない——同じレンジを
テーブルへのSQL集計だけで出せる（ラスタを読まないぶん桁違いに速い）。この計測器が要るのは、
まだ区間単位の行を作っていないDBで「作る価値があるか」を先に知りたいときである。

実行方法（backend/ディレクトリから。.envのDATABASE_URLはSupabase向けのため、ローカルDBへ
明示的に上書きする）:
    .venv\\Scripts\\python.exe scripts\\fetch_lulc_raster.py
    $env:DATABASE_URL = "postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass"
    .venv\\Scripts\\python.exe -m benchmarks.bench_t919_edge_landcover --raster data\\lulc\\54S_2024.tif
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass, field

import shapely
from shapely.geometry import LineString
from sqlalchemy import text

from app.batch._landcover import RasterSource, measure_ring
from app.batch.precompute_way_landcover import DEFAULT_BUFFER_M, DEFAULT_INNER_M
from app.domain.attributes import WIRED_LANDCOVER_KEYS
from app.infrastructure.database import get_session_factory

# 抽出するway数の既定。全件回すと実装と同じ時間がかかるため、判断に足る規模で止める。
# 並びはway_id順で、地理的な順序では**ない**——地理順に並べてLIMITで切ると、その端から
# 連続した一帯だけを見ることになり、かえって母集団を代表しない。way_id順の2,000件が
# 母集団と同じ範囲へ散ることは実測で確認してある（採取分のbboxが母集団のbboxとほぼ一致し、
# way内レンジ20pt以上の割合も1.5%対1.36%で一致した。docs/tasks/T919.md）。
DEFAULT_SAMPLE_WAYS = 2000

# このレンジ（ポイント）を超えたwayを「way平均では潰れている」と数える。
# 1クラスの割合がこれだけ違えば、タイルの色分けのしきい値を跨ぐ可能性がある。
NOTABLE_RANGE_POINTS = 20.0

# 区間を2本以上持つwayを、そのwayの全区間のジオメトリと一緒に引く。
# 同じ物理区間の逆向き（forward/backward）は`_ROAD_SURFACE_TILE_MVT_SQL`と同じ鍵で
# 1本へ潰す——タイルが1フィーチャーとして出す単位に合わせないと、測った差が地図の差と
# 対応しない。
_SEGMENTED_WAYS_SQL = text(
    """
    WITH deduped AS (
        SELECT DISTINCT ON (
            re.osm_way_id, LEAST(re.from_node_id, re.to_node_id), GREATEST(re.from_node_id, re.to_node_id)
        )
            re.osm_way_id,
            re.edge_id,
            re.geom
        FROM road_edges re
        WHERE re.osm_way_id IS NOT NULL AND re.geom IS NOT NULL
        ORDER BY
            re.osm_way_id,
            LEAST(re.from_node_id, re.to_node_id),
            GREATEST(re.from_node_id, re.to_node_id),
            re.edge_id
    )
    SELECT osm_way_id, array_agg(edge_id) AS edge_ids, array_agg(ST_AsBinary(geom)) AS geoms
    FROM deduped
    GROUP BY osm_way_id
    HAVING count(*) >= 2
    ORDER BY osm_way_id
    LIMIT :limit
    """
)


@dataclass
class _ClassStats:
    """1クラスぶんの、way内レンジの分布。"""

    ranges: list[float] = field(default_factory=list)

    def notable(self) -> int:
        return sum(1 for value in self.ranges if value >= NOTABLE_RANGE_POINTS)

    def percentile(self, fraction: float) -> float:
        if not self.ranges:
            return 0.0
        ordered = sorted(self.ranges)
        index = min(len(ordered) - 1, int(fraction * len(ordered)))
        return ordered[index]


def _segment_percentages(sources: list[RasterSource], line_wgs84: LineString, buffer_m: float, inner_m: float):
    """1区間ぶんの割合。バッチ本体と同じ関数を呼ぶ（別の数え方をすると、測った差が実装で
    再現しない）。"""
    return measure_ring(sources, line_wgs84, inner_m, buffer_m).percentages


async def _collect(raster_paths: list[str], limit: int, buffer_m: float, inner_m: float) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        rows = (await session.execute(_SEGMENTED_WAYS_SQL, {"limit": limit})).all()

    if not rows:
        print("対象wayが0件です（road_edgesが空か、区間を2本以上持つwayがありません）。")
        print("app/batch/presplit_road_graph.py を先に流してください。")
        return

    sources = [RasterSource(path) for path in raster_paths]
    try:
        stats = {key: _ClassStats() for key in WIRED_LANDCOVER_KEYS}
        worst_ranges: list[float] = []
        measured_ways = 0
        skipped_ways = 0
        segment_count = 0
        started = time.perf_counter()

        for row in rows:
            geometries = shapely.from_wkb([bytes(blob) for blob in row.geoms])
            per_segment = [
                _segment_percentages(sources, line, buffer_m, inner_m)
                for line in geometries
                if isinstance(line, LineString)
            ]
            usable = [p for p in per_segment if p is not None]
            # 区間が2本そろわないwayは、レンジそのものが定義できない（値なしの区間が
            # 混じるwayを片側だけで数えると、ばらつきを実際より小さく見せる）。
            if len(usable) < 2:
                skipped_ways += 1
                continue
            measured_ways += 1
            segment_count += len(usable)
            per_way = way_class_ranges(usable)
            for key, value in per_way.items():
                stats[key].ranges.append(value)
            worst_ranges.append(max(per_way.values()))

        elapsed = time.perf_counter() - started
        _report(stats, worst_ranges, measured_ways, skipped_ways, segment_count, elapsed, buffer_m, inner_m)
    finally:
        for source in sources:
            source.close()


def way_class_ranges(segment_percentages) -> dict[str, float]:
    """1wayぶんの、クラスごとのレンジ（区間の最大値−最小値）。

    way全体の平均で塗ることによって消えている差がこれである。exportはテスト専用
    （tests/test_bench_t919.py）。
    """
    ranges = {}
    for key in WIRED_LANDCOVER_KEYS:
        values = [getattr(p, key) for p in segment_percentages]
        ranges[key] = max(values) - min(values)
    return ranges


def _report(stats, worst_ranges, measured_ways, skipped_ways, segment_count, elapsed, buffer_m, inner_m) -> None:
    print()
    print("## way内の土地被覆のばらつき（区間単位で持ち直したときに見えるようになる差）")
    print()
    print(f"対象way={measured_ways}件 / 除外={skipped_ways}件（有効な区間が2本未満）")
    print(f"区間={segment_count}件、リング径 inner={inner_m}m outer={buffer_m}m、所要={elapsed:.1f}s")
    print()
    if measured_ways == 0:
        print("有効なwayが1件もありません（ラスタの範囲が対象wayを覆っていない可能性）。")
        return
    print(f"レンジ=そのwayの区間の最大値−最小値（ポイント）。notable={NOTABLE_RANGE_POINTS}pt以上のway数。")
    print()
    header = f"{'クラス':<22}{'中央値':>8}{'p90':>8}{'p99':>8}{'最大':>8}{'notable':>10}{'notable率':>10}"
    print(header)
    print("-" * len(header))
    for key in WIRED_LANDCOVER_KEYS:
        stat = stats[key]
        notable = stat.notable()
        print(
            f"{key:<22}"
            f"{statistics.median(stat.ranges):>8.1f}"
            f"{stat.percentile(0.90):>8.1f}"
            f"{stat.percentile(0.99):>8.1f}"
            f"{max(stat.ranges):>8.1f}"
            f"{notable:>10}"
            f"{100 * notable / measured_ways:>9.1f}%"
        )
    print()
    any_notable = sum(1 for value in worst_ranges if value >= NOTABLE_RANGE_POINTS)
    print(f"いずれかのクラスでnotableなway: {any_notable}件（{100 * any_notable / measured_ways:.1f}%）")
    print()
    print("読み方: notable率が小さい（数%）なら、区間単位で持ってもほとんどの道で同じ色になり、")
    print("        T919のバッチを増やす価値は無い。無視できない割合なら、そのぶんが今は見えていない。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raster", action="append", required=True, help="LULCラスタのパス（複数可）")
    parser.add_argument("--limit", type=int, default=DEFAULT_SAMPLE_WAYS, help="対象way数の上限")
    parser.add_argument("--buffer-m", type=float, default=DEFAULT_BUFFER_M)
    parser.add_argument("--inner-m", type=float, default=DEFAULT_INNER_M)
    args = parser.parse_args(argv)

    asyncio.run(_collect(args.raster, args.limit, args.buffer_m, args.inner_m))
    return 0


if __name__ == "__main__":
    sys.exit(main())
