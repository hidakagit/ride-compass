"""勾配（`elevation_attributes.average_grade`）の異常値がどこから生まれているかを測る
（改善計画T931）。

背景: レンズで15%以上と出た道路が、実地では道に沿って走ってもそんな勾配の無い幹線道路
だった。`average_grade`は`(終点標高 - 始点標高) ÷ 区間長 × 100`（`domain/attributes.py:
compute_elevation_attribute`）で、標高は国土地理院のDEM。疑う経路が2つあり、どちらがどれだけ
効いているかを数える。

1. **区間が短いほどDEMの誤差が大きな%になる**。交差点で切った幹線道路の区間は数十mになり、
   10m標高メッシュの誤差が数mあれば10%を超える。
2. **橋・トンネル・掘割を区別していない**。DEMが返すのは地表面の標高で、路面の高さではない。

あわせて2つを測る。

3. **way単位ズームの代表の選び方**。`_FEATURE_GRADIENT_INPUTS_IN_TILE_SQL`はz14未満で
   wayの「いちばん急な区間」を代表にする。最大と長さ重み付き平均がどれだけ離れるかを数え、
   「異常値1件がway全体を染める」側の弊害を測る（平均にすると崖を下って上り返す道が0%に
   なる、という逆側の弊害は既にSQLのコメントが言っている）。
4. **ルート探索への影響**。同じ値を0次ハードフィルタ（`domain/hard_filters.py:
   max_average_grade_percent`）が読むため、利用者が上限を設定していると異常値の付いた区間は
   黙って経路から外れる。しきい値ごとに何区間・何kmが落ちるかを出す。

前提: 対象DBに`road_edges`・`elevation_attributes`・`osm_raw_ways`がある。
参照専用（SELECTのみ、書き込みなし）。

実行方法（backendディレクトリから）:
    .venv/bin/python scripts/measure_gradient_outliers.py
    .venv/bin/python scripts/measure_gradient_outliers.py --database-url <対象DB>
    .venv/bin/python scripts/measure_gradient_outliers.py --top 50
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402

# 区間長の帯。DEMの誤差は長さで割るため、短い帯ほど|average_grade|が大きく出るなら
# 「短い区間が原因」が裏付けられる。
_LENGTH_BUCKETS_SQL = text(
    """
    WITH edges AS (
        SELECT re.distance_m, abs(ea.average_grade) AS abs_grade
        FROM road_edges re
        JOIN elevation_attributes ea ON ea.edge_id = re.edge_id
        WHERE ea.average_grade IS NOT NULL
    )
    SELECT
        CASE
            WHEN distance_m < 5 THEN '1) 5m未満'
            WHEN distance_m < 10 THEN '2) 5〜10m'
            WHEN distance_m < 15 THEN '3) 10〜15m'
            WHEN distance_m < 25 THEN '4) 15〜25m'
            WHEN distance_m < 50 THEN '5) 25〜50m'
            WHEN distance_m < 100 THEN '6) 50〜100m'
            WHEN distance_m < 250 THEN '7) 100〜250m'
            ELSE '8) 250m以上'
        END AS bucket,
        count(*) AS edges,
        round(avg(abs_grade)::numeric, 2) AS avg_abs_grade,
        round((percentile_cont(0.5) WITHIN GROUP (ORDER BY abs_grade))::numeric, 2) AS p50,
        round((percentile_cont(0.99) WITHIN GROUP (ORDER BY abs_grade))::numeric, 2) AS p99,
        round((100.0 * count(*) FILTER (WHERE abs_grade > 10)) / count(*), 2) AS over_10pct_ratio
    FROM edges
    GROUP BY bucket
    ORDER BY bucket
    """
)

# 橋・トンネルのタグ（`osm_adapter.py: ALLOWED_WAY_TAGS`が保持する）ごとの分布。
_STRUCTURE_SQL = text(
    """
    WITH edges AS (
        SELECT
            abs(ea.average_grade) AS abs_grade,
            CASE
                WHEN coalesce(w.tags ->> 'tunnel', 'no') NOT IN ('no', '') THEN '2) トンネル'
                WHEN coalesce(w.tags ->> 'bridge', 'no') NOT IN ('no', '') THEN '3) 橋'
                ELSE '1) どちらでもない'
            END AS structure
        FROM road_edges re
        JOIN elevation_attributes ea ON ea.edge_id = re.edge_id
        LEFT JOIN osm_raw_ways w ON w.osm_way_id = re.osm_way_id
        WHERE ea.average_grade IS NOT NULL
    )
    SELECT
        structure,
        count(*) AS edges,
        round(avg(abs_grade)::numeric, 2) AS avg_abs_grade,
        round((percentile_cont(0.99) WITHIN GROUP (ORDER BY abs_grade))::numeric, 2) AS p99,
        round((100.0 * count(*) FILTER (WHERE abs_grade > 10)) / count(*), 2) AS over_10pct_ratio
    FROM edges
    GROUP BY structure
    ORDER BY structure
    """
)

# way単位ズームの代表（最大）と、長さ重み付き平均の乖離。
_WAY_REPRESENTATIVE_SQL = text(
    """
    WITH per_way AS (
        SELECT
            re.osm_way_id,
            max(abs(ea.average_grade)) AS max_abs_grade,
            sum(abs(ea.average_grade) * re.distance_m) / nullif(sum(re.distance_m), 0) AS weighted_abs_grade,
            count(*) AS edges
        FROM road_edges re
        JOIN elevation_attributes ea ON ea.edge_id = re.edge_id
        WHERE ea.average_grade IS NOT NULL AND re.osm_way_id IS NOT NULL
        GROUP BY re.osm_way_id
        HAVING count(*) > 1
    )
    SELECT
        count(*) AS ways,
        round(avg(max_abs_grade - weighted_abs_grade)::numeric, 2) AS avg_gap,
        round((percentile_cont(0.99) WITHIN GROUP (ORDER BY max_abs_grade - weighted_abs_grade))::numeric, 2) AS p99_gap,
        count(*) FILTER (WHERE max_abs_grade > 10 AND weighted_abs_grade <= 5) AS ways_max_over10_weighted_under5
    FROM per_way
    """
)

# ハードフィルタのしきい値ごとに落ちる区間数と延長。
_HARD_FILTER_SQL = text(
    """
    WITH edges AS (
        SELECT abs(ea.average_grade) AS abs_grade, re.distance_m
        FROM road_edges re
        JOIN elevation_attributes ea ON ea.edge_id = re.edge_id
        WHERE ea.average_grade IS NOT NULL
    ), thresholds AS (
        SELECT unnest(ARRAY[8, 10, 12, 15, 20, 25, 30, 40, 50, 100]) AS threshold
    )
    SELECT
        t.threshold,
        count(*) FILTER (WHERE e.abs_grade > t.threshold) AS excluded_edges,
        round((100.0 * count(*) FILTER (WHERE e.abs_grade > t.threshold)) / count(*), 3) AS excluded_ratio,
        -- 該当0件のとき sum(...) FILTER は NULL になる。0.0と読めるようにしておく。
        round((coalesce(sum(e.distance_m) FILTER (WHERE e.abs_grade > t.threshold), 0) / 1000)::numeric, 1) AS excluded_km
    FROM thresholds t CROSS JOIN edges e
    GROUP BY t.threshold
    ORDER BY t.threshold
    """
)

# 対処案ごとに「勾配なし」へ落ちる件数と割合。**緩和は影響を測ってから入れる**ため、
# 候補を横に並べて同じ母集団に対する割合で比べられるようにする。
_MITIGATION_IMPACT_SQL = text(
    """
    WITH edges AS (
        SELECT
            abs(ea.average_grade) AS abs_grade,
            re.distance_m,
            coalesce(w.tags ->> 'tunnel', 'no') NOT IN ('no', '') AS is_tunnel,
            coalesce(w.tags ->> 'bridge', 'no') NOT IN ('no', '') AS is_bridge
        FROM road_edges re
        JOIN elevation_attributes ea ON ea.edge_id = re.edge_id
        LEFT JOIN osm_raw_ways w ON w.osm_way_id = re.osm_way_id
        WHERE ea.average_grade IS NOT NULL
    ), total AS (
        SELECT count(*) AS edges, sum(distance_m) AS distance_m FROM edges
    ), candidates AS (
        SELECT '1) 下限長 5m未満'   AS candidate, distance_m <  5 AS hit, distance_m FROM edges
        UNION ALL SELECT '2) 下限長 10m未満',  distance_m < 10, distance_m FROM edges
        UNION ALL SELECT '3) 下限長 15m未満',  distance_m < 15, distance_m FROM edges
        UNION ALL SELECT '4) 下限長 20m未満',  distance_m < 20, distance_m FROM edges
        UNION ALL SELECT '5) 下限長 25m未満',  distance_m < 25, distance_m FROM edges
        UNION ALL SELECT '6) 上限 40%超',      abs_grade > 40, distance_m FROM edges
        UNION ALL SELECT '7) 上限 30%超',      abs_grade > 30, distance_m FROM edges
        UNION ALL SELECT '8) 上限 25%超',      abs_grade > 25, distance_m FROM edges
        UNION ALL SELECT '9) 上限 20%超',      abs_grade > 20, distance_m FROM edges
        UNION ALL SELECT 'A) 橋・トンネル',     is_tunnel OR is_bridge, distance_m FROM edges
    )
    SELECT
        c.candidate,
        count(*) FILTER (WHERE c.hit) AS blanked_edges,
        round((100.0 * count(*) FILTER (WHERE c.hit)) / (SELECT edges FROM total), 3) AS blanked_ratio,
        round((coalesce(sum(c.distance_m) FILTER (WHERE c.hit), 0) / 1000)::numeric, 1) AS blanked_km,
        round(((100.0 * coalesce(sum(c.distance_m) FILTER (WHERE c.hit), 0))
               / (SELECT distance_m FROM total))::numeric, 3) AS blanked_km_ratio
    FROM candidates c
    GROUP BY c.candidate
    ORDER BY c.candidate
    """
)

# 橋・トンネルの急さが、構造物であること自体によるのか、短さと重なっているだけなのか。
_STRUCTURE_BY_LENGTH_SQL = text(
    """
    WITH edges AS (
        SELECT
            abs(ea.average_grade) AS abs_grade,
            re.distance_m,
            CASE
                WHEN coalesce(w.tags ->> 'tunnel', 'no') NOT IN ('no', '') THEN '2) トンネル'
                WHEN coalesce(w.tags ->> 'bridge', 'no') NOT IN ('no', '') THEN '3) 橋'
                ELSE '1) どちらでもない'
            END AS structure
        FROM road_edges re
        JOIN elevation_attributes ea ON ea.edge_id = re.edge_id
        LEFT JOIN osm_raw_ways w ON w.osm_way_id = re.osm_way_id
        WHERE ea.average_grade IS NOT NULL
    )
    SELECT
        structure,
        CASE WHEN distance_m < 25 THEN '短(25m未満)' ELSE '長(25m以上)' END AS length_class,
        count(*) AS edges,
        round(avg(abs_grade)::numeric, 2) AS avg_abs_grade,
        round((100.0 * count(*) FILTER (WHERE abs_grade > 10)) / count(*), 2) AS over_10pct_ratio
    FROM edges
    GROUP BY structure, length_class
    ORDER BY structure, length_class
    """
)


# 最も急な区間の内訳。原因を目で確かめるための一覧。
_TOP_EDGES_SQL = text(
    """
    SELECT
        re.osm_way_id,
        re.highway,
        round(re.distance_m::numeric, 1) AS distance_m,
        round(ea.average_grade::numeric, 1) AS average_grade,
        round(ea.start_elevation_m::numeric, 1) AS start_elevation_m,
        round(ea.end_elevation_m::numeric, 1) AS end_elevation_m,
        coalesce(w.tags ->> 'tunnel', '') AS tunnel,
        coalesce(w.tags ->> 'bridge', '') AS bridge
    FROM road_edges re
    JOIN elevation_attributes ea ON ea.edge_id = re.edge_id
    LEFT JOIN osm_raw_ways w ON w.osm_way_id = re.osm_way_id
    WHERE ea.average_grade IS NOT NULL
    ORDER BY abs(ea.average_grade) DESC
    LIMIT :top
    """
)


# 地図で見えている1本の道を、集計ではなく現物で確かめるための一覧。地図の色が「長く一様」な
# 場合、原因は短い区間のノイズではなく、wayの代表の選び方かedgeの分かれ方にある——それは
# 分布では見えず、その道のedgeを並べて初めて分かる。
_NEAR_EDGES_SQL = text(
    """
    SELECT
        re.edge_id,
        re.osm_way_id,
        re.highway,
        round(re.distance_m::numeric, 1) AS distance_m,
        round(ea.average_grade::numeric, 1) AS average_grade,
        round(ea.start_elevation_m::numeric, 1) AS start_elev,
        round(ea.end_elevation_m::numeric, 1) AS end_elev,
        round(re.bearing_deg::numeric, 0) AS bearing_deg,
        coalesce(w.tags ->> 'tunnel', '') AS tunnel,
        coalesce(w.tags ->> 'bridge', '') AS bridge,
        round(ST_Distance(re.geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)::numeric, 1)
            AS distance_from_point_m
    FROM road_edges re
    LEFT JOIN elevation_attributes ea ON ea.edge_id = re.edge_id
    LEFT JOIN osm_raw_ways w ON w.osm_way_id = re.osm_way_id
    WHERE ST_DWithin(re.geom::geography, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, :radius_m)
    ORDER BY abs(coalesce(ea.average_grade, 0)) DESC, re.edge_id
    LIMIT :limit
    """
)

# 指定した1本のwayの全区間。way単位ズームの代表（最急）が道全体をどう染めるかを現物で見る。
_WAY_EDGES_SQL = text(
    """
    SELECT
        re.edge_id,
        re.highway,
        round(re.distance_m::numeric, 1) AS distance_m,
        round(ea.average_grade::numeric, 1) AS average_grade,
        round(ea.start_elevation_m::numeric, 1) AS start_elev,
        round(ea.end_elevation_m::numeric, 1) AS end_elev,
        round(re.bearing_deg::numeric, 0) AS bearing_deg
    FROM road_edges re
    LEFT JOIN elevation_attributes ea ON ea.edge_id = re.edge_id
    WHERE re.osm_way_id = :osm_way_id
    ORDER BY abs(coalesce(ea.average_grade, 0)) DESC, re.edge_id
    """
)


def _table(title: str, rows: list[dict]) -> list[str]:
    if not rows:
        return [f"## {title}", "  （該当行なし）", ""]
    columns = list(rows[0].keys())
    widths = [max(len(c), *(len(str(r[c])) for r in rows)) for c in columns]
    header = "  " + " | ".join(c.ljust(w) for c, w in zip(columns, widths))
    separator = "  " + "-+-".join("-" * w for w in widths)
    body = ["  " + " | ".join(str(r[c]).ljust(w) for c, w in zip(columns, widths)) for r in rows]
    return [f"## {title}", header, separator, *body, ""]


async def inspect(database_url: str | None, args) -> list[str]:
    """地図で見えている1本を現物で確かめる（--near / --way）。集計は出さない。"""
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            lines: list[str] = []
            if args.near:
                lon, lat = (float(v) for v in args.near.split(","))
                rows = [
                    dict(r)
                    for r in (
                        await session.execute(
                            _NEAR_EDGES_SQL,
                            {"lon": lon, "lat": lat, "radius_m": args.radius_m, "limit": args.top},
                        )
                    ).mappings().all()
                ]
                lines.extend(_table(f"({lat}, {lon}) から{args.radius_m}m以内の区間（|勾配|降順）", rows))
            if args.way:
                rows = [
                    dict(r)
                    for r in (await session.execute(_WAY_EDGES_SQL, {"osm_way_id": args.way})).mappings().all()
                ]
                lines.extend(_table(f"way {args.way} の全区間（|勾配|降順）", rows))
            return lines
    finally:
        await engine.dispose()


async def measure(database_url: str | None, top: int) -> list[str]:
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            lines: list[str] = []
            for title, statement, params in (
                ("区間長の帯ごとの|勾配|（短い帯ほど大きければ、区間長が原因）", _LENGTH_BUCKETS_SQL, {}),
                ("橋・トンネルの別（DEMは路面ではなく地表面を返す）", _STRUCTURE_SQL, {}),
                ("way単位ズームの代表: 最大 - 長さ重み付き平均", _WAY_REPRESENTATIVE_SQL, {}),
                ("橋・トンネル × 区間長（構造物自体か、短さとの重なりか）", _STRUCTURE_BY_LENGTH_SQL, {}),
                ("ハードフィルタで落ちる区間（max_average_grade_percent）", _HARD_FILTER_SQL, {}),
                ("対処案ごとに勾配なしへ落ちる件数（緩和は影響を測ってから入れる）", _MITIGATION_IMPACT_SQL, {}),
                (f"最も急な区間 上位{top}件", _TOP_EDGES_SQL, {"top": top}),
            ):
                rows = [dict(r) for r in (await session.execute(statement, params)).mappings().all()]
                lines.extend(_table(title, rows))
            return lines
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--top", type=int, default=20, help="「最も急な区間」の表示件数")
    parser.add_argument("--near", default=None, help="現物確認: 経度,緯度（例 139.80,35.73）。集計の代わりにこの周辺を出す")
    parser.add_argument("--radius-m", type=float, default=200.0, help="--nearの半径（m）")
    parser.add_argument("--way", type=int, default=None, help="現物確認: このosm_way_idの全区間を出す")
    args = parser.parse_args(argv)

    lines = asyncio.run(inspect(args.database_url, args)) if (args.near or args.way) else asyncio.run(
        measure(args.database_url, args.top)
    )
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
