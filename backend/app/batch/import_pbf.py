"""OSM PBF→PostGIS取込バッチ（docs/osm-pbf-import.md 5章）。

Geofabrik/BBBike等のPBF抽出ファイルから、取込プロファイル（import_profile.yaml）に
マッチする要素を既存の生OSM層（osm_raw_ways/osm_raw_nodes）へバルクロードする。
タグ解釈（oneway→direction等）はランタイムのOverpass経路と同じdomain/osm_adapter.pyを
通すため、どちらのデータソース由来でも同じ意味論の行になる。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe -m app.batch.import_pbf \\
        --pbf data/pbf/Tokyo.osm.pbf \\
        --bbox 35.60,139.65,35.75,139.85 \\
        --database-url postgresql+asyncpg://ridecompass:ridecompass@localhost:5432/ridecompass

- --bboxは「bbox内に1つ以上のノードを持つway」を取込対象とする（ランタイムの
  get_way_specs_with_closureの主対象判定と同じ意味論）。省略時はPBF全体を取り込む
- 取込成功時、--bboxを覆うROAD_GRAPH_TILE_ZOOMのタイルをroad_graph_tilesへ取得済み
  マークする。これによりGraphServiceは（repository注入時）その範囲でOverpassへ行かなく
  なるため、**--bboxは必ずPBF抽出ファイルが実際にカバーする範囲の内側を指定する**こと。
  --bbox省略時はマークしない（PBFヘッダのbboxは抽出ポリゴンの外接矩形にすぎず、
  データが無い領域を「取得済み」と誤マークする恐れがあるため）
- 書き込みは行単位ORMではなく、TEMPステージングテーブルへのCOPY→INSERT ... ON CONFLICT
  のバルクマージ（数百万行規模を想定。docs/osm-pbf-import.md 5.3節）
"""

import argparse
import asyncio
import json
import logging
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from shapely.geometry import LineString
from sqlalchemy.ext.asyncio import create_async_engine

from app.batch._common import asyncpg_dsn, reap_stale_running_import_runs, status_count
from app.batch.profile import ImportProfile, load_profile, matching_rule
from app.config import settings
from app.domain.graph import WaySpec
from app.domain.osm_adapter import POISpec, osm_node_to_poi_spec, osm_way_to_way_spec
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tiles_covering_bbox
from app.infrastructure.migrate import apply_pending_migrations
from app.infrastructure.road_graph_repository import create_tables
from app.infrastructure.road_graph_tile_cache import (
    invalidate_split_fresh as invalidate_split_fresh_in_cache,
    mark_fetched as mark_tiles_fetched_in_cache,
)

logger = logging.getLogger("app.batch.import_pbf")

# 1チャンク＝COPY 1回ぶんのway件数。大きいほどラウンドトリップが減るが、
# メモリ使用量とキュー詰まり時の待ちが増える。
CHUNK_WAY_LIMIT = 20_000
_QUEUE_MAX_CHUNKS = 4

_STAGE_WAYS_DDL = (
    "CREATE TEMP TABLE _stage_osm_raw_ways "
    "(osm_way_id bigint, node_ids bigint[], highway text, surface text, tags_json text, "
    "direction text, geom_wkb bytea)"
)
_STAGE_NODES_DDL = "CREATE TEMP TABLE _stage_osm_raw_nodes (osm_node_id bigint, lon float8, lat float8)"
_STAGE_POIS_DDL = (
    "CREATE TEMP TABLE _stage_osm_raw_pois (osm_node_id bigint, kind text, tags_json text, lon float8, lat float8)"
)

# tagsはasyncpgのCOPYバイナリプロトコルがjsonb型を直接受け付けないため、text列で
# 一旦受けてからマージSQL側で::jsonbキャストする（geom_wkb→ST_GeomFromWKBと同じ考え方）。
_MERGE_WAYS_SQL = """
INSERT INTO osm_raw_ways (osm_way_id, node_ids, highway, surface, tags, direction, geom, updated_at)
SELECT osm_way_id, node_ids, highway, surface, tags_json::jsonb, direction,
       CASE WHEN geom_wkb IS NULL THEN NULL ELSE ST_GeomFromWKB(geom_wkb, 4326) END,
       $1
FROM _stage_osm_raw_ways
ON CONFLICT (osm_way_id) DO UPDATE SET
    node_ids = EXCLUDED.node_ids,
    highway = EXCLUDED.highway,
    surface = EXCLUDED.surface,
    tags = EXCLUDED.tags,
    direction = EXCLUDED.direction,
    geom = EXCLUDED.geom,
    updated_at = EXCLUDED.updated_at
"""

# ノード位置の更新（移動）は追わない簡略化（DO NOTHING）。完全再取込で回収する
# （docs/osm-pbf-import.md 10章）。
_MERGE_NODES_SQL = """
INSERT INTO osm_raw_nodes (osm_node_id, geom, updated_at)
SELECT osm_node_id, ST_SetSRID(ST_MakePoint(lon, lat), 4326), $1
FROM _stage_osm_raw_nodes
ON CONFLICT (osm_node_id) DO NOTHING
"""

# 静的道路属性P1（信号・横断歩道・一時停止・踏切のnode取込）。tagsのjsonbキャスト理由は
# _MERGE_WAYS_SQLと同じ（asyncpg COPYバイナリプロトコルがjsonbを直接受け付けないため）。
_MERGE_POIS_SQL = """
INSERT INTO osm_raw_pois (osm_node_id, kind, tags, geom, updated_at)
SELECT osm_node_id, kind, tags_json::jsonb, ST_SetSRID(ST_MakePoint(lon, lat), 4326), $1
FROM _stage_osm_raw_pois
ON CONFLICT (osm_node_id) DO UPDATE SET
    kind = EXCLUDED.kind,
    tags = EXCLUDED.tags,
    geom = EXCLUDED.geom,
    updated_at = EXCLUDED.updated_at
"""


@dataclass
class Chunk:
    ways: list[tuple] = field(default_factory=list)
    nodes: list[tuple] = field(default_factory=list)
    pois: list[tuple] = field(default_factory=list)


def parse_bbox(text: str) -> BoundingBox:
    """CLIの--bbox（"min_lat,min_lon,max_lat,max_lon"）をBoundingBoxへ変換する。"""
    parts = [float(p) for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError("--bboxは min_lat,min_lon,max_lat,max_lon の4値が必要です")
    min_lat, min_lon, max_lat, max_lon = parts
    if min_lat >= max_lat or min_lon >= max_lon:
        raise ValueError("--bboxはmin < maxとなる範囲が必要です")
    return BoundingBox(
        min_latitude=min_lat, min_longitude=min_lon, max_latitude=max_lat, max_longitude=max_lon
    )


def way_in_bbox(coords: dict[int, tuple[float, float]], bbox: BoundingBox | None) -> bool:
    """wayが取込対象か（bbox内に1つ以上のノードを持つか）。bbox未指定なら常に対象。"""
    if bbox is None:
        return True
    return any(
        bbox.min_latitude <= lat <= bbox.max_latitude and bbox.min_longitude <= lon <= bbox.max_longitude
        for lat, lon in coords.values()
    )


def poi_in_bbox(spec: POISpec, bbox: BoundingBox | None) -> bool:
    """POI（信号等の単独node）が取込対象か。wayと違い参照ノード集合を持たないため、
    自身の座標がbbox内かどうかで直接判定する（bbox未指定なら常に対象）。"""
    if bbox is None:
        return True
    return bbox.min_latitude <= spec.latitude <= bbox.max_latitude and (
        bbox.min_longitude <= spec.longitude <= bbox.max_longitude
    )


def build_poi_record(spec: POISpec) -> tuple:
    """POISpec→ステージング行。tagsはway側と同じ理由でJSON文字列化する。"""
    tags_json = json.dumps(spec.tags, ensure_ascii=False)
    return (spec.osm_node_id, spec.kind, tags_json, spec.longitude, spec.latitude)


def build_way_record(spec: WaySpec, coords: dict[int, tuple[float, float]]) -> tuple:
    """WaySpec→ステージング行。geomは座標が判明しているノード2点以上のときのみWKBを持つ
    （save_raw_waysのランタイム経路と同じ意味論）。tagsは許可リスト適用済み
    （osm_adapter.py: ALLOWED_WAY_TAGS）のためそのままJSON文字列化する。"""
    points = [coords[n] for n in spec.node_ids if n in coords]
    wkb = LineString([(lon, lat) for lat, lon in points]).wkb if len(points) >= 2 else None
    tags_json = json.dumps(spec.tags, ensure_ascii=False)
    return (spec.osm_way_id, spec.node_ids, spec.highway, spec.surface, tags_json, spec.direction, wkb)


def _parse_pbf_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class _Producer:
    """osmiumのストリーム読み取り（ブロッキング）を別スレッドで回し、チャンクをキューへ送る。"""

    def __init__(self, pbf_path: Path, profile: ImportProfile, bbox: BoundingBox | None):
        self._pbf_path = pbf_path
        self._profile = profile
        self._bbox = bbox
        self.queue: queue.Queue[Chunk | None] = queue.Queue(maxsize=_QUEUE_MAX_CHUNKS)
        self.abort = threading.Event()
        self.error: BaseException | None = None
        self._chunk = Chunk()
        self._chunk_node_seen: set[int] = set()

    def _sink(self, raw_way: dict, coords: dict[int, tuple[float, float]]) -> None:
        if self.abort.is_set():
            raise RuntimeError("import aborted by consumer failure")
        if not way_in_bbox(coords, self._bbox):
            return
        spec = osm_way_to_way_spec(raw_way)
        if spec is None or spec.osm_way_id is None:
            return
        self._chunk.ways.append(build_way_record(spec, coords))
        for node_id, (lat, lon) in coords.items():
            # チャンク内の重複のみここで除去し、チャンク間・既存行との重複は
            # ON CONFLICT DO NOTHINGに任せる（グローバルなseen集合は数千万ノード規模で
            # メモリを食い潰すため持たない）。
            if node_id not in self._chunk_node_seen:
                self._chunk_node_seen.add(node_id)
                self._chunk.nodes.append((node_id, lon, lat))
        if len(self._chunk.ways) >= CHUNK_WAY_LIMIT:
            self._flush()

    def _node_sink(self, raw_node: dict) -> None:
        # 静的道路属性P1。標準的なPBFはnode→way→relationの順でブロックが並ぶため、
        # このコールバックはway処理が始まる前にほぼ全件完了する（POIは都市部でも
        # 数万件オーダーで軽量、計画書§5.3）。チャンク分割は__way__件数基準のままでよく、
        # 最初にflushされるチャンクへ多くのPOIがまとまって乗る形になるが、
        # COPY→ON CONFLICTマージは冪等なため正しさに影響しない。
        if self.abort.is_set():
            raise RuntimeError("import aborted by consumer failure")
        spec = osm_node_to_poi_spec(raw_node)
        if spec is None or not poi_in_bbox(spec, self._bbox):
            return
        self._chunk.pois.append(build_poi_record(spec))

    def _flush(self) -> None:
        if self._chunk.ways or self._chunk.nodes or self._chunk.pois:
            self.queue.put(self._chunk)
            self._chunk = Chunk()
            self._chunk_node_seen = set()

    def run(self) -> None:
        # 遅延import: pyosmium（requirements-batch.txt）はバッチ実行時のみ必要で、
        # webサービス環境にはインストールされない
        from app.batch import pbf_source

        def tag_filter(tags: dict[str, str]) -> bool:
            return matching_rule(self._profile, "way", tags) is not None

        def node_tag_filter(tags: dict[str, str]) -> bool:
            return matching_rule(self._profile, "node", tags) is not None

        try:
            pbf_source.stream_ways(
                self._pbf_path, tag_filter, self._sink, node_tag_filter, self._node_sink
            )
            self._flush()
        except BaseException as exc:  # noqa: BLE001 スレッド境界を越えて伝搬させるため一旦捕捉
            self.error = exc
        finally:
            self.queue.put(None)


async def _flush_chunk(conn: asyncpg.Connection, chunk: Chunk, updated_at: datetime) -> tuple[int, int, int]:
    await conn.execute("TRUNCATE _stage_osm_raw_ways, _stage_osm_raw_nodes, _stage_osm_raw_pois")
    await conn.copy_records_to_table(
        "_stage_osm_raw_ways",
        records=chunk.ways,
        columns=["osm_way_id", "node_ids", "highway", "surface", "tags_json", "direction", "geom_wkb"],
    )
    await conn.copy_records_to_table(
        "_stage_osm_raw_nodes", records=chunk.nodes, columns=["osm_node_id", "lon", "lat"]
    )
    await conn.copy_records_to_table(
        "_stage_osm_raw_pois", records=chunk.pois, columns=["osm_node_id", "kind", "tags_json", "lon", "lat"]
    )
    # wayのgeom算出はステージング側で済んでいるため順序制約は無いが、参照整合の直感に
    # 合わせてノード→way→POIの順でマージする
    node_status = await conn.execute(_MERGE_NODES_SQL, updated_at)
    way_status = await conn.execute(_MERGE_WAYS_SQL, updated_at)
    poi_status = await conn.execute(_MERGE_POIS_SQL, updated_at)
    return status_count(way_status), status_count(node_status), status_count(poi_status)


async def _mark_tiles(conn: asyncpg.Connection, bbox: BoundingBox, fetched_at: datetime) -> int:
    tiles = tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM)
    await conn.executemany(
        "INSERT INTO road_graph_tiles (zoom, x, y, fetched_at) VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (zoom, x, y) DO NOTHING",
        [(ROAD_GRAPH_TILE_ZOOM, x, y, fetched_at) for x, y in tiles],
    )
    # PostGIS（正本）への書き込み直後にRedis（cache-aside、road_graph_tile_cache.py）も
    # 温めておく。次回のルート生成リクエストがcold cacheでPostGISへ問い合わせ直す1回分を
    # 省ける（失敗してもPostGIS側の正本は既に確定済みのため取込結果自体には影響しない）。
    await mark_tiles_fetched_in_cache(ROAD_GRAPH_TILE_ZOOM, tiles)
    # 同じタイルの再import（osm_raw_ways.updated_atが進む）でroad_edgesが生データより
    # 古くなりうるため、is_split_up_to_dateのcache-aside（split鮮度マーカー）を無効化する。
    # 初回import（マーカー自体がまだ無い）でも無害（存在しないキーのDELETEは単なるno-op）。
    await invalidate_split_fresh_in_cache(ROAD_GRAPH_TILE_ZOOM, tiles)
    return len(tiles)


async def run_import(
    pbf: str,
    profile_path: str,
    bbox_text: str | None,
    database_url: str | None,
    dry_run: bool,
) -> int:
    started = time.perf_counter()
    run_started_at = datetime.now(timezone.utc)
    profile = load_profile(profile_path)
    pbf_path = Path(pbf)
    if not pbf_path.is_file():
        logger.error("PBFファイルが見つかりません: %s", pbf_path)
        return 1

    # 遅延import（pyosmium。_Producer.runと同じ理由）
    from app.batch import pbf_source

    pbf_timestamp_raw, header_bbox = pbf_source.read_header(pbf_path)
    bbox = parse_bbox(bbox_text) if bbox_text else None
    if bbox is None and header_bbox is not None:
        logger.info(
            "bbox未指定のためPBF全体を取り込みます (header_bbox=%.2f,%.2f,%.2f,%.2f)。"
            "タイルの取得済みマークは行いません（ヘッダbboxは抽出範囲の外接矩形にすぎないため）",
            *header_bbox,
        )

    producer = _Producer(pbf_path, profile, bbox)
    producer_task = asyncio.create_task(asyncio.to_thread(producer.run))
    total_ways = 0
    total_nodes = 0
    total_pois = 0
    chunk_count = 0

    async def _abort_and_join_producer() -> None:
        # 消費側（DB接続・DDL・チャンク処理のいずれか）がproducer_task作成後のどこかで
        # 失敗した場合、producerがqueue.put()（maxsize=4）でブロックしたまま取り残され、
        # スレッドプールの非デーモンスレッドがプロセス終了時に無期限に待たれる
        # （実質ハング）バグがあった。producer_taskを既にawait済みでも安全に再度awaitできる
        # （完了済みTaskへの再awaitは同じ結果を返すだけ）ため、失敗経路をこの1箇所へ集約する。
        producer.abort.set()
        while True:
            try:
                if producer.queue.get_nowait() is None:
                    break
            except queue.Empty:
                break
        await producer_task

    try:
        if dry_run:
            while (chunk := await asyncio.to_thread(producer.queue.get)) is not None:
                total_ways += len(chunk.ways)
                total_nodes += len(chunk.nodes)
                total_pois += len(chunk.pois)
            await producer_task
            if producer.error is not None:
                raise producer.error
            logger.info(
                "dry-run完了: matched_ways=%d node_rows=%d matched_pois=%d elapsed=%.1fs（DB書き込みなし）",
                total_ways, total_nodes, total_pois, time.perf_counter() - started,
            )
            return 0

        sqlalchemy_url = database_url or settings.database_url
        engine = create_async_engine(sqlalchemy_url)
        try:
            await create_tables(engine)  # 新テーブル（osm_import_runs等）の冪等な作成
            await apply_pending_migrations(engine)  # 列追加・インデックス・バックフィル（T17）
        finally:
            await engine.dispose()

        conn = await asyncpg.connect(asyncpg_dsn(sqlalchemy_url))
        # 前回実行がプロセスクラッシュでrunning状態のまま取り残されていないか確認し、
        # あれば自己修復する（_common.py: reap_stale_running_import_runs参照）。
        reaped = await reap_stale_running_import_runs(conn, "osm_import_runs")
        if reaped:
            logger.warning("クラッシュで取り残されたrunning状態のosm_import_runsを%d件failedへ遷移しました", reaped)
        run_id = None
        # 初回（空テーブル）取込時のみ、osm_raw_ways.geomのGiSTを取込完了後まで遅延して
        # 構築する。蓄積量に比例するGiST逐次挿入コスト（＋shared_buffers超過後のランダム
        # I/O）でチャンク処理時間が単調増加するため。月次UPSERT再取込は非空なのでこの
        # 分岐に入らず、既存インデックスをそのまま使い続ける（稼働中DBのインデックスを
        # 落とさない）。
        deferred_ways_index = False
        ways_index_ensured = False
        try:
            run_id = await conn.fetchval(
                "INSERT INTO osm_import_runs (pbf_name, pbf_timestamp, profile_hash, bbox, status, started_at) "
                "VALUES ($1, $2, $3, $4, 'running', $5) RETURNING id",
                pbf_path.name,
                _parse_pbf_timestamp(pbf_timestamp_raw),
                profile.profile_hash,
                bbox_text,
                run_started_at,
            )
            await conn.execute(_STAGE_WAYS_DDL)
            await conn.execute(_STAGE_NODES_DDL)
            await conn.execute(_STAGE_POIS_DDL)

            ways_is_empty = await conn.fetchval("SELECT NOT EXISTS (SELECT 1 FROM osm_raw_ways)")
            deferred_ways_index = bool(ways_is_empty)
            if deferred_ways_index:
                await conn.execute("DROP INDEX IF EXISTS idx_osm_raw_ways_geom")
                logger.info("osm_raw_waysが空のため、geom列のGiSTインデックス構築を取込完了後へ遅延します")

            try:
                while (chunk := await asyncio.to_thread(producer.queue.get)) is not None:
                    way_count, node_count, poi_count = await _flush_chunk(conn, chunk, run_started_at)
                    total_ways += way_count
                    total_nodes += node_count
                    total_pois += poi_count
                    chunk_count += 1
                    logger.info(
                        "chunk %d: ways+%d nodes+%d pois+%d (累計 ways=%d nodes=%d pois=%d)",
                        chunk_count, way_count, node_count, poi_count, total_ways, total_nodes, total_pois,
                    )
            finally:
                await producer_task
            if producer.error is not None:
                raise producer.error

            marked_tiles = 0
            if bbox is not None:
                marked_tiles = await _mark_tiles(conn, bbox, run_started_at)

            if deferred_ways_index:
                index_started = time.perf_counter()
                # ソート済み一括ビルド向けにセッション内だけmaintenance_work_memを引き上げる
                # （このバッチ専用の接続で、完了後すぐcloseするため他セッションへ影響しない）
                await conn.execute("SET maintenance_work_mem = '1GB'")
                await conn.execute("CREATE INDEX IF NOT EXISTS idx_osm_raw_ways_geom ON osm_raw_ways USING gist (geom)")
                ways_index_ensured = True
                logger.info(
                    "osm_raw_ways.geom GiSTインデックスを再作成しました elapsed=%.1fs",
                    time.perf_counter() - index_started,
                )

            await conn.execute(
                "UPDATE osm_import_runs SET status='succeeded', finished_at=$2, way_count=$3, node_count=$4 "
                "WHERE id=$1",
                run_id, datetime.now(timezone.utc), total_ways, total_nodes,
            )
            # 容量予算の監視（Supabaseフリープラン500MB・プロトタイプ目標300MB、
            # docs/osm-pbf-import.md 10章）。取込のたびに現在のDBサイズをサマリへ出す。
            db_size_bytes = await conn.fetchval("SELECT pg_database_size(current_database())")
            logger.info(
                "取込完了: run_id=%s ways=%d nodes=%d pois=%d chunks=%d marked_tiles=%d(z%d) "
                "pbf_timestamp=%s db_size_mb=%.0f elapsed=%.1fs",
                run_id, total_ways, total_nodes, total_pois, chunk_count, marked_tiles, ROAD_GRAPH_TILE_ZOOM,
                pbf_timestamp_raw, db_size_bytes / 1_000_000, time.perf_counter() - started,
            )
            return 0
        except BaseException:
            if run_id is not None:
                try:
                    await conn.execute(
                        "UPDATE osm_import_runs SET status='failed', finished_at=$2 WHERE id=$1",
                        run_id, datetime.now(timezone.utc),
                    )
                except Exception:  # noqa: BLE001 元の例外を失わせない
                    logger.exception("osm_import_runsのfailed更新に失敗")
            raise
        finally:
            # 途中失敗でもインデックス欠落を残さない（正しさは保たれるが遅くなるだけの状態を
            # 放置しない）。CREATE INDEX IF NOT EXISTSは冪等なので再実行しても安全。
            if deferred_ways_index and not ways_index_ensured:
                try:
                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_osm_raw_ways_geom ON osm_raw_ways USING gist (geom)"
                    )
                except Exception:  # noqa: BLE001 元の例外を隠さない
                    logger.exception("geom GiSTインデックスの再作成に失敗しました（次回取込時に再試行される）")
            await conn.close()
    except BaseException:
        await _abort_and_join_producer()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OSM PBF→PostGIS取込バッチ（docs/osm-pbf-import.md）")
    parser.add_argument("--pbf", required=True, help="取込元PBFファイルのパス")
    parser.add_argument(
        "--profile",
        default=str(Path(__file__).parent / "import_profile.yaml"),
        help="取込プロファイル（YAML）のパス",
    )
    parser.add_argument(
        "--bbox",
        default=None,
        help="取込範囲 min_lat,min_lon,max_lat,max_lon（PBFの実カバー範囲の内側を指定すること。"
        "省略時はPBF全体を取り込み、タイルの取得済みマークは行わない）",
    )
    parser.add_argument("--database-url", default=None, help="取込先DB（省略時はsettings.database_url）")
    parser.add_argument("--dry-run", action="store_true", help="件数集計のみでDBへ書き込まない")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return asyncio.run(
        run_import(args.pbf, args.profile, args.bbox, args.database_url, args.dry_run)
    )


if __name__ == "__main__":
    sys.exit(main())
