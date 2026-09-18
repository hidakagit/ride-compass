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
            WHEN distance_m < 25 THEN '1) 25m未満'
            WHEN distance_m < 50 THEN '2) 25〜50m'
            WHEN distance_m < 100 THEN '3) 50〜100m'
            WHEN distance_m < 250 THEN '4) 100〜250m'
            ELSE '5) 250m以上'
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
        SELECT unnest(ARRAY[8, 10, 12, 15, 20]) AS threshold
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


def _table(title: str, rows: list[dict]) -> list[str]:
    if not rows:
        return [f"## {title}", "  （該当行なし）", ""]
    columns = list(rows[0].keys())
    widths = [max(len(c), *(len(str(r[c])) for r in rows)) for c in columns]
    header = "  " + " | ".join(c.ljust(w) for c, w in zip(columns, widths))
    separator = "  " + "-+-".join("-" * w for w in widths)
    body = ["  " + " | ".join(str(r[c]).ljust(w) for c, w in zip(columns, widths)) for r in rows]
    return [f"## {title}", header, separator, *body, ""]


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
                ("ハードフィルタで落ちる区間（max_average_grade_percent）", _HARD_FILTER_SQL, {}),
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
    args = parser.parse_args(argv)

    for line in asyncio.run(measure(args.database_url, args.top)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
