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

from app.batch.profile import ImportProfile, load_profile, matching_rule
from app.config import settings
from app.domain.graph import WaySpec
from app.domain.osm_adapter import osm_way_to_way_spec
from app.domain.region import ROAD_GRAPH_TILE_ZOOM, BoundingBox, tiles_covering_bbox
from app.infrastructure.road_graph_repository import create_tables

logger = logging.getLogger("app.batch.import_pbf")

# 1チャンク＝COPY 1回ぶんのway件数。大きいほどラウンドトリップが減るが、
# メモリ使用量とキュー詰まり時の待ちが増える。
CHUNK_WAY_LIMIT = 20_000
_QUEUE_MAX_CHUNKS = 4

_STAGE_WAYS_DDL = (
    "CREATE TEMP TABLE _stage_osm_raw_ways "
    "(osm_way_id bigint, node_ids bigint[], highway text, surface text, direction text, geom_wkb bytea)"
)
_STAGE_NODES_DDL = "CREATE TEMP TABLE _stage_osm_raw_nodes (osm_node_id bigint, lon float8, lat float8)"

_MERGE_WAYS_SQL = """
INSERT INTO osm_raw_ways (osm_way_id, node_ids, highway, surface, direction, geom, updated_at)
SELECT osm_way_id, node_ids, highway, surface, direction,
       CASE WHEN geom_wkb IS NULL THEN NULL ELSE ST_GeomFromWKB(geom_wkb, 4326) END,
       $1
FROM _stage_osm_raw_ways
ON CONFLICT (osm_way_id) DO UPDATE SET
    node_ids = EXCLUDED.node_ids,
    highway = EXCLUDED.highway,
    surface = EXCLUDED.surface,
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


@dataclass
class Chunk:
    ways: list[tuple] = field(default_factory=list)
    nodes: list[tuple] = field(default_factory=list)


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


def build_way_record(spec: WaySpec, coords: dict[int, tuple[float, float]]) -> tuple:
    """WaySpec→ステージング行。geomは座標が判明しているノード2点以上のときのみWKBを持つ
    （save_raw_waysのランタイム経路と同じ意味論）。"""
    points = [coords[n] for n in spec.node_ids if n in coords]
    wkb = LineString([(lon, lat) for lat, lon in points]).wkb if len(points) >= 2 else None
    return (spec.osm_way_id, spec.node_ids, spec.highway, spec.surface, spec.direction, wkb)


def _asyncpg_dsn(sqlalchemy_url: str) -> str:
    """SQLAlchemy用URL（postgresql+asyncpg://...?ssl=require）を、asyncpg.connectが
    受け付けるDSNへ正規化する。`ssl=`クエリはSQLAlchemyのasyncpgダイアレクト固有の
    書き方のため、libpq互換の`sslmode=`へ読み替える（Supabase等のリモートDB用。
    ローカルのssl指定なしURLはドライバ指定の除去のみ）。"""
    dsn = sqlalchemy_url.replace("+asyncpg", "")
    return dsn.replace("?ssl=", "?sslmode=").replace("&ssl=", "&sslmode=")


def _parse_pbf_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _status_count(status: str) -> int:
    # asyncpgのexecuteは"INSERT 0 123"のようなコマンドステータス文字列を返す
    try:
        return int(status.split()[-1])
    except (ValueError, IndexError):
        return 0


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

    def _flush(self) -> None:
        if self._chunk.ways or self._chunk.nodes:
            self.queue.put(self._chunk)
            self._chunk = Chunk()
            self._chunk_node_seen = set()

    def run(self) -> None:
        # 遅延import: pyosmium（requirements-batch.txt）はバッチ実行時のみ必要で、
        # webサービス環境にはインストールされない
        from app.batch import pbf_source

        def tag_filter(tags: dict[str, str]) -> bool:
            return matching_rule(self._profile, "way", tags) is not None

        try:
            pbf_source.stream_ways(self._pbf_path, tag_filter, self._sink)
            self._flush()
        except BaseException as exc:  # noqa: BLE001 スレッド境界を越えて伝搬させるため一旦捕捉
            self.error = exc
        finally:
            self.queue.put(None)


async def _flush_chunk(conn: asyncpg.Connection, chunk: Chunk, updated_at: datetime) -> tuple[int, int]:
    await conn.execute("TRUNCATE _stage_osm_raw_ways, _stage_osm_raw_nodes")
    await conn.copy_records_to_table(
        "_stage_osm_raw_ways",
        records=chunk.ways,
        columns=["osm_way_id", "node_ids", "highway", "surface", "direction", "geom_wkb"],
    )
    await conn.copy_records_to_table(
        "_stage_osm_raw_nodes", records=chunk.nodes, columns=["osm_node_id", "lon", "lat"]
    )
    # wayのgeom算出はステージング側で済んでいるため順序制約は無いが、参照整合の直感に
    # 合わせてノード→wayの順でマージする
    node_status = await conn.execute(_MERGE_NODES_SQL, updated_at)
    way_status = await conn.execute(_MERGE_WAYS_SQL, updated_at)
    return _status_count(way_status), _status_count(node_status)


async def _mark_tiles(conn: asyncpg.Connection, bbox: BoundingBox, fetched_at: datetime) -> int:
    tiles = tiles_covering_bbox(bbox, ROAD_GRAPH_TILE_ZOOM)
    await conn.executemany(
        "INSERT INTO road_graph_tiles (zoom, x, y, fetched_at) VALUES ($1, $2, $3, $4) "
        "ON CONFLICT (zoom, x, y) DO NOTHING",
        [(ROAD_GRAPH_TILE_ZOOM, x, y, fetched_at) for x, y in tiles],
    )
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
            await producer_task
            if producer.error is not None:
                raise producer.error
            logger.info(
                "dry-run完了: matched_ways=%d node_rows=%d elapsed=%.1fs（DB書き込みなし）",
                total_ways, total_nodes, time.perf_counter() - started,
            )
            return 0

        sqlalchemy_url = database_url or settings.database_url
        engine = create_async_engine(sqlalchemy_url)
        try:
            await create_tables(engine)  # 新テーブル（osm_import_runs）・geom列の冪等な作成を含む
        finally:
            await engine.dispose()

        conn = await asyncpg.connect(_asyncpg_dsn(sqlalchemy_url))
        run_id = None
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

            try:
                while (chunk := await asyncio.to_thread(producer.queue.get)) is not None:
                    way_count, node_count = await _flush_chunk(conn, chunk, run_started_at)
                    total_ways += way_count
                    total_nodes += node_count
                    chunk_count += 1
                    logger.info(
                        "chunk %d: ways+%d nodes+%d (累計 ways=%d nodes=%d)",
                        chunk_count, way_count, node_count, total_ways, total_nodes,
                    )
            finally:
                await producer_task
            if producer.error is not None:
                raise producer.error

            marked_tiles = 0
            if bbox is not None:
                marked_tiles = await _mark_tiles(conn, bbox, run_started_at)

            await conn.execute(
                "UPDATE osm_import_runs SET status='succeeded', finished_at=$2, way_count=$3, node_count=$4 "
                "WHERE id=$1",
                run_id, datetime.now(timezone.utc), total_ways, total_nodes,
            )
            # 容量予算の監視（Supabaseフリープラン500MB・プロトタイプ目標300MB、
            # docs/osm-pbf-import.md 10章）。取込のたびに現在のDBサイズをサマリへ出す。
            db_size_bytes = await conn.fetchval("SELECT pg_database_size(current_database())")
            logger.info(
                "取込完了: run_id=%s ways=%d nodes=%d chunks=%d marked_tiles=%d(z%d) "
                "pbf_timestamp=%s db_size_mb=%.0f elapsed=%.1fs",
                run_id, total_ways, total_nodes, chunk_count, marked_tiles, ROAD_GRAPH_TILE_ZOOM,
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
