"""指定路線（route_designations）→road_edgesへのバッファマッチ事前計算バッチ
（外部静的データソース T51、パターンD。docs/external-data-sources-review-2026-08-16.md §4.3）。

線×線の割合計算は評価時導出には重いため、elevation_attributesと同じ「Edge派生の
事前計算」として`designation_attributes`へ書き込む。`import_designations.py`（route_designations
の取込）後、およびOSM再取込（road_edgesが変わりうる）後に再実行する必要がある。

判定式: バッファ内交差長 / Edge全長 >= DESIGNATION_MATCH_MIN_RATIO
（`domain/designation.py`が正準。バッファ幅もそこで定義）。同一(edge_id, kind)に対し
複数のroute_designations行が寄与しうる場合に二重計上しないよう、交差ジオメトリを
ST_Unionしてから長さを測る。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.match_designations --database-url ...

--dry-runで対象件数・matched_ratio分布のログのみ（DB書き込みなし）。
"""

import argparse
import asyncio
import logging
import sys
import time

import asyncpg

from app.batch._common import asyncpg_dsn
from app.config import settings
from app.domain.designation import DESIGNATION_BUFFER_WIDTH_M, DESIGNATION_IMPORT_KINDS, DESIGNATION_MATCH_MIN_RATIO

logger = logging.getLogger("app.batch.match_designations")

_KINDS = DESIGNATION_IMPORT_KINDS

# バッファポリゴンはroute_designations行ごとに決定的（Edgeに依存しない）ため、先にCTEで
# 1行1回だけ計算してからJOINする（MATERIALIZEDでインライン化を禁止し、road_edgesとの
# JOIN内で行ごとに再計算されるのを防ぐ。route_designations側の長い線形をST_Bufferする
# コストは無視できないため、これを対象road_edges件数分だけ繰り返すのが最初の実装で
# 遅かった主因と判定した）。
# JOIN条件はST_Intersects(e.geom, b.buffer_geom)（どちらもgeometry型、::geographyキャスト
# なし）にする。当初は`ST_DWithin(e.geom::geography, b.geom::geography, $1)`だったが、
# geographyキャストを挟むとPostGISのプランナがroad_edges.geomのGiST索引
# （idx_road_edges_geom）を認識できず、Join Filter（全組み合わせを評価してから絞り込み）に
# 落ちてしまい、実データ（road_edges 22,164件×route_designations 5,084件）で
# 30分超無応答になることを実測で確認した（EXPLAIN上のコストが14億→239万まで下がることも
# 確認済み）。buffer_geomは既に20mバッファ済みのgeometryのため、素のST_Intersectsで
# 意味的に等価かつ索引を使える（GiST演算子クラスがST_Intersectsを自動的に`&&`へ展開する）。
# GROUP BYはe.edge_id（road_edgesの主キー）のみにする。e.geomは主キーに関数従属するため
# 含める必要が無く、PostGISジオメトリを含めたGROUP BYはハッシュ・比較コストが高いため避ける。
# ST_Unionでまとめてから測ることで、同一(edge_id, kind)へ複数のroute_designations行
# （例: 隣接するN10区間データが同じEdge近傍を2本通る場合）が寄与しても交差長を二重計上しない。
_MATCH_SQL = """
WITH buffered AS MATERIALIZED (
    SELECT id, kind, ST_Buffer(geom::geography, $1)::geometry AS buffer_geom
    FROM route_designations
    WHERE kind = ANY($2)
),
matched AS (
    SELECT e.edge_id, b.kind,
           ST_Length(e.geom::geography) AS edge_length_m,
           ST_Union(
               ST_CollectionExtract(ST_Intersection(e.geom, b.buffer_geom), 2)
           ) AS unioned
    FROM buffered b
    JOIN road_edges e ON ST_Intersects(e.geom, b.buffer_geom)
    GROUP BY e.edge_id, b.kind
)
SELECT edge_id, kind, ST_Length(unioned::geography) / NULLIF(edge_length_m, 0) AS ratio
FROM matched
"""

_DELETE_SQL = "DELETE FROM designation_attributes WHERE kind = ANY($1)"
_INSERT_SQL = """
INSERT INTO designation_attributes (edge_id, kind, matched_ratio, data_version, calculated_at)
VALUES ($1, $2, $3, $4, now())
"""


async def _write_matches(
    conn: asyncpg.Connection,
    candidates: list[tuple[str, str, float]],
    matched: list[tuple[str, str, float]],
    data_version: str,
) -> float:
    """DELETE→executemany INSERTを1トランザクションに括り、candidatesが0件のときは
    DELETEごとスキップする（改善計画T73）。戻り値はinsert所要秒（スキップ時は0.0）。

    route_designationsが空（import未実行・取込失敗後）やバッファ閾値不整合でcandidatesが
    0件のとき、従来はDELETEだけ実行され既存designation_attributesが0件INSERTで
    静かに全消しされていた。
    """
    if not candidates:
        logger.warning(
            "マッチ候補が0件のため更新をスキップします（既存データは保持） candidates=0 matched=0"
        )
        return 0.0

    data_version_local = data_version
    insert_started = time.perf_counter()
    async with conn.transaction():
        await conn.execute(_DELETE_SQL, list(_KINDS))
        # 改善計画T67: 1行ずつconn.executeするとRTT×行数がそのまま実行時間に乗る
        # （本番はOracle遠隔DBのため特に顕著）。executemanyで1ラウンドトリップにバッチ化する。
        await conn.executemany(
            _INSERT_SQL,
            [(edge_id, kind, ratio, data_version_local) for edge_id, kind, ratio in matched],
        )
    return time.perf_counter() - insert_started


async def run_match(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    sqlalchemy_url = database_url or settings.database_url
    conn = await asyncpg.connect(asyncpg_dsn(sqlalchemy_url))
    try:
        logger.info("マッチング開始: buffer_width_m=%.1f kinds=%s", DESIGNATION_BUFFER_WIDTH_M, list(_KINDS))
        rows = await conn.fetch(_MATCH_SQL, DESIGNATION_BUFFER_WIDTH_M, list(_KINDS))
        candidates = [(r["edge_id"], r["kind"], r["ratio"]) for r in rows if r["ratio"] is not None]
        matched = [c for c in candidates if c[2] >= DESIGNATION_MATCH_MIN_RATIO]

        if dry_run:
            logger.info(
                "dry-run完了: candidates=%d matched(ratio>=%.2f)=%d elapsed=%.1fs（DB書き込みなし）",
                len(candidates), DESIGNATION_MATCH_MIN_RATIO, len(matched), time.perf_counter() - started,
            )
            for kind in _KINDS:
                kind_matched = [c for c in matched if c[1] == kind]
                logger.info("dry-run kind=%s: matched=%d", kind, len(kind_matched))
            return 0

        data_version = f"buffer{DESIGNATION_BUFFER_WIDTH_M:.0f}m"
        insert_elapsed = await _write_matches(conn, candidates, matched, data_version)

        # 改善計画T73: candidates=0（_write_matches内でWARNING済み）はここでは重複ログしない。
        # candidatesはあってもmatched=0（全てratio閾値未満）はWARNING（docs/logging.mdの
        # 「候補0件はWARNING以上・原因内訳を同行に」規約）。
        if candidates:
            log = logger.warning if not matched else logger.info
            log(
                "マッチング完了: candidates=%d matched=%d insert_elapsed=%.1fs elapsed=%.1fs",
                len(candidates), len(matched), insert_elapsed, time.perf_counter() - started,
            )
        return 0
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="指定路線→road_edgesバッファマッチ事前計算バッチ（外部静的データソース T51）"
    )
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="件数・分布集計のみでDBへ書き込まない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run_match(args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
