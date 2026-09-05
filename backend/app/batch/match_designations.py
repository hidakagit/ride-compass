"""指定路線（route_designations）→osm_raw_waysへのバッファマッチ事前計算バッチ
（外部静的データソース T51、パターンD。docs/external-data-sources-review-2026-08-16.md §4.3）。

線×線の割合計算は評価時導出には重いため、elevation_attributesと同じ「派生データの
事前計算」として`designation_attributes`へ書き込む。`import_designations.py`（route_designations
の取込）後、およびOSM再取込（osm_raw_waysが変わりうる）後に再実行する必要がある。

マッチング対象はosm_raw_ways（関東全域自己完結）基準で、road_edges（ルート生成済みエリア
のみ）には依存しない（docs/modules/backend/static-road-attributes.md「暗黙の前提」参照）。

判定式: バッファ内交差長 / Way全長 >= DESIGNATION_MATCH_MIN_RATIO
（`domain/designation.py`が正準。バッファ幅もそこで定義）。同一(osm_way_id, kind)に対し
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

# バッファポリゴンはroute_designations行ごとに決定的（Wayに依存しない）ため、先にCTEで
# 1行1回だけ計算してからJOINする（MATERIALIZEDでインライン化を禁止し、osm_raw_waysとの
# JOIN内で行ごとに再計算されるのを防ぐ。route_designations側の長い線形をST_Bufferする
# コストは無視できないため、対象osm_raw_ways件数分だけ繰り返すのを避ける）。
# JOIN条件はST_Intersects(w.geom, b.buffer_geom)（どちらもgeometry型、::geographyキャスト
# なし）にする。geographyキャストを挟むとPostGISのプランナがGiST索引を認識できず、
# Join Filter（全組み合わせを評価してから絞り込み）に落ちてしまい、実データでは長時間
# 無応答になりうる。buffer_geomは既に20mバッファ済みのgeometryのため、素のST_Intersectsで
# 意味的に等価かつ索引（osm_raw_ways.geomのGiST索引、spatial_index=True）を使える。
# WHERE w.geom IS NOT NULLガード: osm_raw_ways.geomは座標既知ノードが2点未満のWay
# （抽出ファイル境界等）でNULLになりうる（road_edges.geomと異なりNOT NULL制約が無い）。
# GROUP BYはw.osm_way_id（osm_raw_waysの主キー）のみにする。w.geomは主キーに関数従属するため
# 含める必要が無く、PostGISジオメトリを含めたGROUP BYはハッシュ・比較コストが高いため避ける。
# ST_Unionでまとめてから測ることで、同一(osm_way_id, kind)へ複数のroute_designations行
# （例: 隣接するN10区間データが同じWay近傍を2本通る場合）が寄与しても交差長を二重計上しない。
# ST_Intersectionの第3引数（gridSize=1e-7度、OSM座標精度と同じ桁）は必須: ST_Intersects=true
# なのにST_Intersection（gridSize省略のデフォルト経路）がLINESTRING EMPTYを返すことがある
# （GEOS OverlayNGの数値ロバストネス不具合、線がバッファポリゴンの中心軸と完全に平行・
# 同一直線上の場合に発生。ST_Buffer(...,0)による正規化では解消せず、gridSize指定で
# snap-rounding noding経路に切り替えることで解消する）。
_MATCH_SQL = """
WITH buffered AS MATERIALIZED (
    SELECT id, kind, ST_Buffer(geom::geography, $1)::geometry AS buffer_geom
    FROM route_designations
    WHERE kind = ANY($2)
),
matched AS (
    SELECT w.osm_way_id, b.kind,
           ST_Length(w.geom::geography) AS way_length_m,
           ST_Union(
               ST_CollectionExtract(ST_Intersection(w.geom, b.buffer_geom, 1e-7), 2)
           ) AS unioned,
           -- 派生データの系譜追跡: この(osm_way_id, kind)のmatched_ratioへ実際に寄与した
           -- 全route_designations.id（複数のroute_designations行が同じWayへ寄与しうる
           -- ため配列で保持する）。
           array_agg(DISTINCT b.id) AS route_designation_ids
    FROM buffered b
    JOIN osm_raw_ways w ON w.geom IS NOT NULL AND ST_Intersects(w.geom, b.buffer_geom)
    GROUP BY w.osm_way_id, b.kind
)
SELECT osm_way_id, kind, ST_Length(unioned::geography) / NULLIF(way_length_m, 0) AS ratio,
       route_designation_ids
FROM matched
"""

_DELETE_SQL = "DELETE FROM designation_attributes WHERE kind = ANY($1)"
_INSERT_SQL = """
INSERT INTO designation_attributes
    (osm_way_id, kind, matched_ratio, data_version, calculated_at,
     matched_route_designation_ids, source_osm_import_run_id)
VALUES ($1, $2, $3, $4, now(), $5, $6)
"""
_LATEST_SUCCEEDED_OSM_RUN_ID_SQL = "SELECT MAX(id) FROM osm_import_runs WHERE status = 'succeeded'"


async def _write_matches(
    conn: asyncpg.Connection,
    candidates: list[tuple[int, str, float, list[int]]],
    matched: list[tuple[int, str, float, list[int]]],
    data_version: str,
    source_osm_import_run_id: int | None = None,
) -> float:
    """DELETE→executemany INSERTを1トランザクションに括り、candidatesが0件のときは
    DELETEごとスキップする（route_designationsが空[import未実行・取込失敗後]やバッファ
    閾値不整合でcandidatesが0件のとき、既存designation_attributesを誤って全消しする
    事故を防ぐため）。戻り値はinsert所要秒（スキップ時は0.0）。

    source_osm_import_run_idは派生データの系譜追跡用、呼び出し元（run_match）が
    実行時点の最新成功osm_import_runs.idを一度だけ取得し渡す。
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
        # 1行ずつconn.executeするとRTT×行数がそのまま実行時間に乗る（本番は遠隔DBのため
        # 特に顕著）。executemanyで1ラウンドトリップにバッチ化する。
        await conn.executemany(
            _INSERT_SQL,
            [
                (osm_way_id, kind, ratio, data_version_local, route_designation_ids, source_osm_import_run_id)
                for osm_way_id, kind, ratio, route_designation_ids in matched
            ],
        )
    return time.perf_counter() - insert_started


async def run_match(database_url: str | None, dry_run: bool) -> int:
    started = time.perf_counter()
    sqlalchemy_url = database_url or settings.database_url
    conn = await asyncpg.connect(asyncpg_dsn(sqlalchemy_url))
    try:
        logger.info("マッチング開始: buffer_width_m=%.1f kinds=%s", DESIGNATION_BUFFER_WIDTH_M, list(_KINDS))
        # 派生データの系譜追跡: このマッチングが実際に読むosm_raw_waysのデータに対応する
        # osm_import_runsの最新成功run id（高水位マーク、migration 0024のコメント参照）。
        # _MATCH_SQL直前で取得することで、別プロセスのimport_pbf.pyが並行完了して
        # osm_import_runsの最新成功runが進んだ場合でも、記録されるrun idと実際に読んだ
        # データの対応がずれる窓を狭める（precompute_edge_attribute_counts.py:
        # _get_latest_run_idsと同じ「読み取り直前に取得する」パターン）。dry-runでは
        # 書き込まないため取得しない。
        source_osm_import_run_id = None if dry_run else await conn.fetchval(_LATEST_SUCCEEDED_OSM_RUN_ID_SQL)
        rows = await conn.fetch(_MATCH_SQL, DESIGNATION_BUFFER_WIDTH_M, list(_KINDS))
        candidates = [
            (r["osm_way_id"], r["kind"], r["ratio"], r["route_designation_ids"])
            for r in rows
            if r["ratio"] is not None
        ]
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
        insert_elapsed = await _write_matches(conn, candidates, matched, data_version, source_osm_import_run_id)

        # candidates=0（_write_matches内でWARNING済み）はここでは重複ログしない。
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
        description="指定路線→osm_raw_waysバッファマッチ事前計算バッチ（外部静的データソース T51）"
    )
    parser.add_argument("--database-url", default=None, help="対象DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="件数・分布集計のみでDBへ書き込まない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(run_match(args.database_url, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
