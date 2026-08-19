"""way_attribute_counts（Way単位事前集計）を交差点分割セグメント単位へ上げた場合の
走査コスト倍率を見積もる（改善計画T152）。

背景: way_attribute_counts（`domain/route.py`ではなく`road_graph_models.py:
WayAttributeCountsRow`）はWay全体の長さで密度を平均する設計のため、事故・停止・交差点が
Way内で局所的に偏っている場合、地図表示の平均値と実際にそのEdgeを通ったときの
`edge_attribute_counts`（Edge単位、ルート評価用）の値がズレうる。本スクリプトは
「交差点分割後のセグメント単位に上げた場合、行数（≒空間集計SQLの走査コスト）が
何倍に増えるか」を2つのモデルで見積もる。

- モデルA（真値）: `domain/graph.py: build_road_graph`の`_split_points`と完全に同じ分割基準
  （Wayの端点、または全Way中でグローバルに2回以上参照されるノード）。
- モデルB（安価な近似）: 新規の空間計算を追加せず、既に事前計算済みの
  `raw_intersection_nodes`（次数3以上、T145bの`precompute_way_attribute_counts.py`が
  `way_attribute_counts`本体の再計算前に毎回全再構築している）をそのまま分割点に使う。

前提: 対象DBの`osm_raw_ways`にPBF取込済みデータがあり、`raw_intersection_nodes`が
最新であること（`RoadGraphRepository.rebuild_raw_intersection_nodes()`実行済み）。
参照専用（SELECTのみ、書き込みなし）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\measure_way_segment_split.py
    .venv\\Scripts\\python.exe scripts\\measure_way_segment_split.py --database-url <対象DB>
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402

# node_occurrences: build_road_graphのCounter(way.node_ids)と同じグローバル出現回数。
# way_positions: 各Wayの各ノードの位置（ordinality）と、その位置が分割点かどうか。
#   分割点 = 自Wayの先頭/末尾、または全Wayを通じた出現回数が2回以上。
# segments_a: モデルA（真値）のWayごとのセグメント数（分割点の出現位置数 - 1）。
# way_interior_hits / segments_b: モデルB（raw_intersection_nodes近似）のセグメント数。
_ESTIMATE_SQL = text(
    """
    with node_occurrences as (
        select node_id, count(*) as occurrence_count
        from osm_raw_ways w, unnest(w.node_ids) as node_id
        where w.geom is not null and w.highway is not null
        group by node_id
    ),
    way_positions as (
        select
            w.osm_way_id,
            pos.node_id,
            pos.ordinality,
            array_length(w.node_ids, 1) as node_count
        from osm_raw_ways w, unnest(w.node_ids) with ordinality as pos(node_id, ordinality)
        where w.geom is not null and w.highway is not null
    ),
    way_split_positions_a as (
        select
            p.osm_way_id,
            count(*) filter (
                where p.ordinality = 1
                   or p.ordinality = p.node_count
                   or coalesce(o.occurrence_count, 1) >= 2
            ) as split_position_count
        from way_positions p
        left join node_occurrences o on o.node_id = p.node_id
        group by p.osm_way_id
    ),
    segments_a as (
        select osm_way_id, greatest(split_position_count - 1, 1) as segment_count
        from way_split_positions_a
    ),
    way_interior_hits as (
        select
            p.osm_way_id,
            count(*) filter (
                where p.ordinality not in (1, p.node_count)
                  and ri.osm_node_id is not null
            ) as interior_intersection_count
        from way_positions p
        left join raw_intersection_nodes ri on ri.osm_node_id = p.node_id
        group by p.osm_way_id
    ),
    segments_b as (
        select osm_way_id, interior_intersection_count + 1 as segment_count
        from way_interior_hits
    )
    select
        (select count(*) from segments_a) as way_count,
        (select sum(segment_count) from segments_a) as total_segments_model_a,
        (select round(avg(segment_count), 2) from segments_a) as avg_segments_per_way_a,
        (select round(sum(segment_count)::numeric / nullif(count(*), 0), 2) from segments_a)
            as cost_multiplier_a,
        (select sum(segment_count) from segments_b) as total_segments_model_b,
        (select round(avg(segment_count), 2) from segments_b) as avg_segments_per_way_b,
        (select round(sum(segment_count)::numeric / nullif(count(*), 0), 2) from segments_b)
            as cost_multiplier_b,
        (
            select count(*) filter (where a.segment_count > b.segment_count)
            from segments_a a join segments_b b using (osm_way_id)
        ) as ways_where_b_undersplits,
        (
            select round(avg(a.segment_count - b.segment_count), 3)
            from segments_a a join segments_b b using (osm_way_id)
        ) as avg_segment_diff_a_minus_b,
        (select percentile_cont(0.5) within group (order by segment_count) from segments_a) as p50_a,
        (select percentile_cont(0.9) within group (order by segment_count) from segments_a) as p90_a,
        (select percentile_cont(0.99) within group (order by segment_count) from segments_a) as p99_a,
        (select max(segment_count) from segments_a) as max_segments_single_way_a
    """
)


def report_lines(row: dict) -> list[str]:
    lines = [
        f"対象way数: {row['way_count']}件",
        "",
        "モデルA（真値、build_road_graphと同一の分割基準）:",
        f"  総セグメント数: {row['total_segments_model_a']}",
        f"  平均セグメント数/way: {row['avg_segments_per_way_a']}",
        f"  走査コスト倍率（総セグメント数/way数）: {row['cost_multiplier_a']}倍",
        f"  分布: p50={row['p50_a']} p90={row['p90_a']} p99={row['p99_a']} "
        f"max={row['max_segments_single_way_a']}",
        "",
        "モデルB（raw_intersection_nodesを使う安価な近似）:",
        f"  総セグメント数: {row['total_segments_model_b']}",
        f"  平均セグメント数/way: {row['avg_segments_per_way_b']}",
        f"  走査コスト倍率（総セグメント数/way数）: {row['cost_multiplier_b']}倍",
        "",
        "A/Bの乖離（Bで代替した場合に失う精度）:",
        f"  Bが真値より粗い（過小分割）way数: {row['ways_where_b_undersplits']}",
        f"  平均セグメント数差（A-B）: {row['avg_segment_diff_a_minus_b']}",
    ]
    return lines


async def measure(database_url: str | None) -> dict:
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            result = await session.execute(_ESTIMATE_SQL)
            row = result.mappings().one()
            return dict(row)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    args = parser.parse_args(argv)

    row = asyncio.run(measure(args.database_url))
    for line in report_lines(row):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
