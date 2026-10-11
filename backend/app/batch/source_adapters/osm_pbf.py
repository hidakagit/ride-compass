"""OSMのPBFのアダプタ（way・node）。

**タグは絞らない**。行（どのwayを取るか）だけをプロファイルが絞る。タグは容量のごく一部
しか占めないうえ、捨てると後から解釈を変えられなくなる——分類（POIの種別・自転車が
通れるか等）は派生の側で行う。

ノードのソースは、採ったwayの頂点に加えて、道と関係なく置かれた補給・休憩の点も採る。
面（way）で描かれた補給・休憩の施設は、面の内側の1点を**wayのidの符号を反転した値**を
キーにしたノードとして採る——OSMのidは正の数で、ノードとwayはidの空間が別なので、
反転すればノードのidと重ならない。

wayの`payload`は参照ノードidをint64で並べた配列。属性として読める値ではないが、区間へ
切るときに「どのwayがどのノードを共有しているか」が要る。

pyosmiumはコールバックで動く同期の仕組みなので、別スレッドで走らせて結果を非同期側へ
渡す。1件ずつスレッドをまたぐと遅く、全件を溜めるとPBF1本ぶんがメモリに載るため、
まとまりができ次第すぐ渡す。
"""

import asyncio
import logging
import queue
import struct
import threading
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry import LineString, Point, Polygon

from app.batch.ingest import AdapterInputs, SourceRecord, file_origin, register_adapter
from app.batch.source_profile import SourceProfile, SourceProfileError, SourceSpec
from app.domain.traffic import has_supply_poi_tag
from app.infrastructure.source_models import WAY_KIND_TAG, SourceFeatureRow

logger = logging.getLogger("ridecompass.ingest.osm_pbf")

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "pbf"

#: スレッド間で受け渡すまとまりの件数と、待ち行列の深さ。深さは読み手が遅れたときに
#: 読み側が先へ行きすぎないための背圧で、メモリの上限を決める。
_HANDOFF_BATCH = 5_000
_QUEUE_DEPTH = 4

_SENTINEL = object()


@dataclass(frozen=True)
class OsmWayRows:
    """`osm_pbf_way`の`rows`。"""

    #: 採るwayの条件。どれか1つに合えば採る。1つの条件はタグ名→許容値（`*`は値を問わない）のAND。
    #: どの条件も道の種別（`WAY_KIND_TAG`）を含む——含まない条件は種別の無い道を採りうる。
    any_of: list[dict[str, Any]] = field(default_factory=list)
    #: 読むPBF（`data/pbf/`の下）。
    file: str = "kanto-latest.osm.pbf"

    def __post_init__(self) -> None:
        lacking = [rule for rule in self.any_of if WAY_KIND_TAG not in rule]
        if lacking:
            raise SourceProfileError(
                f"rows.any_of の条件はどれも {WAY_KIND_TAG} を含む必要があります（含まない条件: {lacking}）")

    def matches(self, tags: dict[str, str]) -> bool:
        """wayを採るか。"""
        return any(_matches(tags, rule) for rule in self.any_of)


@dataclass(frozen=True)
class OsmNodeRows:
    """`osm_pbf_node`の`rows`。"""

    #: 頂点を採るwayのソース。そのソースの条件とPBFを受け継ぐ。
    referenced_by: str
    #: 道の頂点でない補給・休憩の点（点と面）も採るか。どのタグが補給・休憩かは
    #: `domain/traffic.py: SUPPLY_POI_TAGS`が決める。
    standalone_supply_poi: bool = False


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


def _pbf_path(rows: OsmWayRows) -> Path:
    """PBFの場所。**pyosmiumへ渡すのは、可能なら現在位置からの相対パス**。

    非ASCIIを含む絶対パスを渡すとpyosmiumがファイルを開けない。
    """
    path = DATA_DIR / rows.file
    if not path.exists():
        raise FileNotFoundError(f"PBFがありません: {path}")
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


def way_payload(node_ids: Sequence[int]) -> bytes:
    """wayの`payload`。参照ノードidを、リトルエンディアンの符号付き64bit整数で並べる。"""
    return struct.pack(f"<{len(node_ids)}q", *node_ids)


def _area_point(node_ids: Sequence[int], coords: dict[int, tuple[float, float]]) -> Point | None:
    """面で描かれた施設を代表する点（面の内側の1点）。閉じていないwayは線の上の1点にする。"""
    points = [(coords[n][1], coords[n][0]) for n in node_ids if n in coords]
    if not points:
        return None
    if len(points) >= 4 and node_ids[0] == node_ids[-1] and len(points) == len(node_ids):
        shape = shapely.make_valid(Polygon(points))
    elif len(points) >= 2:
        shape = LineString(points)
    else:
        return Point(points[0])
    return shape.point_on_surface()


class _Handoff:
    """別スレッドが積んだまとまりを、非同期側へ流す受け渡し。"""

    def __init__(self) -> None:
        self.queue: queue.Queue = queue.Queue(maxsize=_QUEUE_DEPTH)
        self._batch: list[SourceRecord] = []
        self.error: BaseException | None = None

    def put(self, record: SourceRecord) -> None:
        self._batch.append(record)
        if len(self._batch) >= _HANDOFF_BATCH:
            self.queue.put(self._batch)
            self._batch = []

    def flush(self) -> None:
        if self._batch:
            self.queue.put(self._batch)
            self._batch = []

    async def stream(self, work) -> AsyncIterator[SourceRecord]:
        """`work`を別スレッドで流し、積まれたものを順に返す。"""

        def body() -> None:
            try:
                work(self)
                self.flush()
            except BaseException as exc:  # スレッドの例外を本流へ運ぶ
                self.error = exc
            finally:
                self.queue.put(_SENTINEL)

        thread = threading.Thread(target=body, daemon=True)
        thread.start()
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
        from app.batch.pbf_source import replication_timestamp

        stamp = replication_timestamp(path)
        if stamp:
            origin["replication_timestamp"] = stamp
    except Exception:  # 出所の付帯情報が取れないだけで取込は続ける
        pass
    return origin


def osm_way_inputs(spec: SourceSpec, profile: SourceProfile) -> AdapterInputs:
    return AdapterInputs(files=(_pbf_path(spec.rows),))


@register_adapter("osm_pbf_way", rows=OsmWayRows, required=(SourceFeatureRow.payload,), inputs=osm_way_inputs)
async def read_osm_ways(spec: SourceSpec, profile: SourceProfile,
                        origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    from app.batch.pbf_source import stream_ways

    path = _pbf_path(spec.rows)
    origin.update(_pbf_origin(path))
    target = profile.target
    logger.info("OSM way: %s", path.name)

    incomplete = 0

    def work(handoff: _Handoff) -> None:
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
            if len(points) < 2 or not any(target.contains(lat, lon) for lat, lon in points):
                return
            handoff.put(SourceRecord(
                natural_key=str(way["id"]),
                geom_wkb=shapely.to_wkb(LineString([(lon, lat) for lat, lon in points])),
                attrs=way["tags"],
                payload=way_payload(node_ids),
            ))

        stream_ways(path, spec.rows.matches, sink)

    async for record in _Handoff().stream(work):
        yield record
    if incomplete:
        logger.warning("参照ノードの座標が欠けて取り込まなかったway: %d件", incomplete)


def _referenced_way_rows(spec: SourceSpec, profile: SourceProfile) -> OsmWayRows:
    """頂点を採るwayのソースの宣言。そこからは**どのwayを採るかと、どのファイルから採るか**の両方を受け継ぐ。
    片方だけ受け継ぐと、既定以外のPBFを指したプロファイルで頂点だけ別のファイルを読む。"""
    referenced_by = spec.rows.referenced_by
    way_rows = profile.source(referenced_by).rows
    if not isinstance(way_rows, OsmWayRows):
        raise ValueError(f"{spec.name} の rows.referenced_by は osm_pbf_way のソースを指してください"
                         f"（指しているもの: {referenced_by}）")
    return way_rows


def osm_node_inputs(spec: SourceSpec, profile: SourceProfile) -> AdapterInputs:
    return AdapterInputs(files=(_pbf_path(_referenced_way_rows(spec, profile)),),
                         sources=(spec.rows.referenced_by,))


@register_adapter("osm_pbf_node", rows=OsmNodeRows, inputs=osm_node_inputs)
async def read_osm_nodes(spec: SourceSpec, profile: SourceProfile,
                         origin: dict[str, Any]) -> AsyncIterator[SourceRecord]:
    """採ったwayが参照する頂点と、`standalone_supply_poi`なら補給・休憩の点を、タグ込みで返す。

    頂点はタグの有無で分けない——POIかどうかは派生側の判定で、生データの側では決めない。
    どのwayの頂点を採るかは`referenced_by`が指すソースの絞り込みに従う。
    """
    from app.batch.pbf_source import stream_ways

    target = profile.target
    referenced_by = spec.rows.referenced_by
    standalone = spec.rows.standalone_supply_poi
    way_rows = _referenced_way_rows(spec, profile)
    path = _pbf_path(way_rows)
    origin.update(_pbf_origin(path))
    road_matches = way_rows.matches
    logger.info("OSM node: %s（%s の頂点%s）", path.name, referenced_by,
                "と補給・休憩の点" if standalone else "")

    def way_matches(tags: dict[str, str]) -> bool:
        return road_matches(tags) or (standalone and has_supply_poi_tag(tags))

    def work(handoff: _Handoff) -> None:
        # PBFはノードがwayより先に来るため、wayを処理する時点でタグは揃っている。
        tagged: dict[int, dict[str, str]] = {}
        seen: set[int] = set()

        def node_sink(node: dict) -> None:
            node_id = node["id"]
            tagged[node_id] = node["tags"]
            if standalone and has_supply_poi_tag(node["tags"]) and target.contains(node["lat"], node["lon"]):
                seen.add(node_id)
                handoff.put(SourceRecord(
                    natural_key=str(node_id),
                    geom_wkb=shapely.to_wkb(Point(node["lon"], node["lat"])),
                    attrs=node["tags"],
                ))

        def sink(way: dict, coords: dict[int, tuple[float, float]]) -> None:
            if standalone and has_supply_poi_tag(way["tags"]):
                point = _area_point(way["nodes"], coords)
                if point is not None and target.contains(point.y, point.x):
                    handoff.put(SourceRecord(
                        natural_key=str(-way["id"]),
                        geom_wkb=shapely.to_wkb(point),
                        attrs=way["tags"],
                    ))
            if not road_matches(way["tags"]):
                return
            for node_id in way["nodes"]:
                location = coords.get(node_id)
                if location is None or node_id in seen:
                    continue
                lat, lon = location
                if not target.contains(lat, lon):
                    continue
                seen.add(node_id)
                handoff.put(SourceRecord(
                    natural_key=str(node_id),
                    geom_wkb=shapely.to_wkb(Point(lon, lat)),
                    attrs=tagged.get(node_id, {}),
                ))

        stream_ways(path, way_matches, sink, node_sink=node_sink)

    async for record in _Handoff().stream(work):
        yield record
