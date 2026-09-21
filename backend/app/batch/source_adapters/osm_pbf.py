"""OSMのPBFのアダプタ（way・node）。

**タグは絞らない**。行（どのwayを取るか）だけをプロファイルが絞る。タグは容量のごく一部
しか占めないうえ、捨てると後から解釈を変えられなくなる——分類（POIの種別・自転車が
通れるか等）は派生の側で行う。

wayの`payload`は参照ノードidをint64で並べた配列。属性として読める値ではないが、区間へ
切るときに「どのwayがどのノードを共有しているか」が要る。

pyosmiumはコールバックで動く同期の仕組みなので、別スレッドで走らせて結果を非同期側へ
渡す。1件ずつスレッドをまたぐと遅いため、まとまりで渡す。全件を溜めてから渡すと
1,300,000wayぶんがメモリに載るため、まとまりができ次第すぐ渡す。
"""

import asyncio
import logging
import queue
import struct
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry import LineString, Point

from app.batch.ingest import SourceRecord, file_origin, register_adapter
from app.batch.source_profile import SourceProfile, SourceSpec

logger = logging.getLogger("ridecompass.ingest.osm_pbf")

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "pbf"

#: スレッド間で受け渡すまとまりの件数と、待ち行列の深さ。深さは読み手が遅れたときに
#: 読み側が先へ行きすぎないための背圧で、メモリの上限を決める。
HANDOFF_BATCH = 5_000
QUEUE_DEPTH = 4

_SENTINEL = object()


def _matches(tags: dict[str, str], rule: dict[str, Any]) -> bool:
    """1つのルール（タグ名→許容値）に対するANDマッチ。"""
    for key, allowed in rule.items():
        value = tags.get(key)
        if value is None:
            return False
        if allowed == "*":
            continue
        if isinstance(allowed, str):
            allowed = [allowed]
        if value not in allowed:
            return False
    return True


def _way_matcher(rows: dict[str, Any]):
    """`rows`から、wayを採るかどうかの判定を組み立てる。

    `any_of`は「上の条件に入らないが拾いたいもの」を並べる枝で、どれか1つに合えば採る。
    """
    primary = {k: v for k, v in rows.items() if k not in ("any_of", "referenced_by", "file")}
    alternatives = list(rows.get("any_of") or [])

    def matches(tags: dict[str, str]) -> bool:
        if primary and _matches(tags, primary):
            return True
        return any(_matches(tags, alt) for alt in alternatives)

    return matches


def _pbf_path(spec: SourceSpec) -> Path:
    """PBFの場所。**pyosmiumへ渡すのは、可能なら現在位置からの相対パス**。

    非ASCIIを含む絶対パスを渡すとpyosmiumがファイルを開けない。
    """
    path = DATA_DIR / str(spec.rows.get("file") or "kanto-latest.osm.pbf")
    if not path.exists():
        raise FileNotFoundError(f"PBFがありません: {path}")
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


def _in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    min_lat, min_lon, max_lat, max_lon = bbox
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


class _Handoff:
    """別スレッドが積んだまとまりを、非同期側へ流す受け渡し。"""

    def __init__(self) -> None:
        self.queue: queue.Queue = queue.Queue(maxsize=QUEUE_DEPTH)
        self._batch: list[SourceRecord] = []
        self.error: BaseException | None = None

    def put(self, record: SourceRecord) -> None:
        self._batch.append(record)
        if len(self._batch) >= HANDOFF_BATCH:
            self.queue.put(self._batch)
            self._batch = []

    def flush(self) -> None:
        if self._batch:
            self.queue.put(self._batch)
            self._batch = []

    def run(self, work) -> threading.Thread:
        def body() -> None:
            try:
                work(self)
                self.flush()
            except BaseException as exc:  # noqa: BLE001  スレッドの例外を本流へ運ぶ
                self.error = exc
            finally:
                self.queue.put(_SENTINEL)

        thread = threading.Thread(target=body, daemon=True)
        thread.start()
        return thread

    async def drain(self, thread: threading.Thread) -> AsyncIterator[SourceRecord]:
        loop = asyncio.get_running_loop()
        try:
            while True:
                batch = await loop.run_in_executor(None, self.queue.get)
                if batch is _SENTINEL:
                    break
                for record in batch:
                    yield record
        finally:
            thread.join()
        if self.error is not None:
            raise self.error


def _pbf_origin(path: Path) -> dict[str, Any]:
    """PBFの素性。`osmosis_replication_timestamp`は**配信元がいつの断面を焼いたか**で、
    ファイルのmtime（こちらがいつ落としたか）とは別物。取れないPBFもあるので、
    取れたときだけ入れる。"""
    origin: dict[str, Any] = file_origin(path)
    try:
        import osmium

        header = osmium.io.Reader(str(path)).header()
        stamp = header.get("osmosis_replication_timestamp")
        if stamp:
            origin["replication_timestamp"] = stamp
    except Exception:  # noqa: BLE001 出所の付帯情報が取れないだけで取込は続ける
        pass
    return origin


@register_adapter("osm_pbf_way")
async def read_osm_ways(spec: SourceSpec, profile: SourceProfile,
                        origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    from app.batch.pbf_source import stream_ways

    path = _pbf_path(spec)
    origin.update(_pbf_origin(path))
    matches = _way_matcher(spec.rows)
    bbox = profile.target.bbox
    logger.info("OSM way: %s", path.name)

    incomplete = 0

    def work(handoff: _Handoff) -> None:
        nonlocal incomplete

        def sink(way: dict, coords: dict[int, tuple[float, float]]) -> None:
            nonlocal incomplete
            node_ids = way["nodes"]
            points = [coords[n] for n in node_ids if n in coords]
            # 参照ノードの座標が1つでも欠けたwayは丸ごと落とす。頂点だけ抜いて取り込むと、
            # `payload`のノード列とジオメトリの頂点が1対1で対応しなくなり、区間の位置範囲が
            # 指す頂点がずれる。参照完全な抽出（Geofabrikの地域抽出等）なら0件になる。
            if len(points) != len(node_ids):
                incomplete += 1
                return
            if len(points) < 2 or not any(_in_bbox(lat, lon, bbox) for lat, lon in points):
                return
            handoff.put(SourceRecord(
                natural_key=str(way["id"]),
                geom_wkb=shapely.to_wkb(LineString([(lon, lat) for lat, lon in points])),
                attrs=way["tags"],
                payload=struct.pack(f"<{len(node_ids)}q", *node_ids),
            ))

        stream_ways(path, matches, sink)

    handoff = _Handoff()
    async for record in handoff.drain(handoff.run(work)):
        yield record
    if incomplete:
        logger.warning("参照ノードの座標が欠けて取り込まなかったway: %d件", incomplete)


@register_adapter("osm_pbf_node")
async def read_osm_nodes(spec: SourceSpec, profile: SourceProfile,
                         origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    """採ったwayが参照する頂点を、タグ込みで返す。

    タグの有無で分けない——POIかどうかは派生側の判定で、生データの側では決めない。
    どのwayの頂点を採るかは`referenced_by`が指すソースの絞り込みに従う。
    """
    from app.batch.pbf_source import stream_ways

    bbox = profile.target.bbox
    referenced_by = spec.rows.get("referenced_by")
    # 参照先からは**どのwayを採るかと、どのファイルから採るか**の両方を受け継ぐ。
    # 片方だけ受け継ぐと、既定以外のPBFを指したプロファイルで頂点だけ別のファイルを読む。
    source_spec = profile.source(referenced_by) if referenced_by else spec
    path = _pbf_path(source_spec)
    origin.update(_pbf_origin(path))
    matches = _way_matcher(source_spec.rows) if referenced_by else (lambda _: True)
    logger.info("OSM node: %s（%s の頂点）", path.name, referenced_by or "全way")

    def work(handoff: _Handoff) -> None:
        # PBFはノードがwayより先に来るため、wayを処理する時点でタグは揃っている。
        tagged: dict[int, dict[str, str]] = {}
        seen: set[int] = set()

        def node_sink(node: dict) -> None:
            tagged[node["id"]] = node["tags"]

        def sink(way: dict, coords: dict[int, tuple[float, float]]) -> None:
            for node_id in way["nodes"]:
                location = coords.get(node_id)
                if location is None or node_id in seen:
                    continue
                lat, lon = location
                if not _in_bbox(lat, lon, bbox):
                    continue
                seen.add(node_id)
                handoff.put(SourceRecord(
                    natural_key=str(node_id),
                    geom_wkb=shapely.to_wkb(Point(lon, lat)),
                    attrs=tagged.get(node_id, {}),
                ))

        stream_ways(path, matches, sink,
                    node_tag_filter=lambda _: True, node_sink=node_sink)

    handoff = _Handoff()
    async for record in handoff.drain(handoff.run(work)):
        yield record
