"""取込範囲全体の道路網（`domain/road_network.py: RoadNetwork`）をDBから作り、ディスクへ置き、読む。

DBから作ると数分かかる。そのため作るのは派生の作り直し（`batch/derive_cli.py`。作り直した表を
入れ替える前に作り、入れ替えた直後に置く）とデプロイの前処理（`scripts/build_road_network.py`）だけで、
backendは置かれたものを読むだけにする。

置き場は`data/road_network/<形の署名>-r<派生データの世代>/`。中に配列ごとの`.npy`と、
配列でない値（語彙・列の並び・世代）と配列を作った入力の指紋を書いた`manifest.json`を置く。書き終えるまでは読み手が
拾わない名前（先頭が`.`）のディレクトリに書き、最後に名前を付け替える——途中で落ちても、読む側が
書きかけを掴まない。

形の署名は`RoadNetwork`の列と、読み出しのSQL（材料の式を含む）から導く。材料の式を変えた
コードをデプロイすると署名が変わり、古い置き場は選ばれなくなる。
"""

import json
import logging
import os
import re
import shutil
import time
from collections.abc import Iterator
from dataclasses import fields
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.attributes import EdgeMaterialArrays
from app.domain.road_network import RoadNetwork
from app.domain.traffic import travel_allowed
from app.infrastructure.cache_identity import shape_digest
from app.infrastructure.data_paths import DATA_DIR
from app.infrastructure.road_graph_repository import NETWORK_SQL_SOURCES, RoadGraphRepository

logger = logging.getLogger("ridecompass.road_network")

#: 本番の読み手はこのファイルだけだが、テストがディスク（プロセス境界）の置き場を一時ディレクトリへ差し替えるために公開する
#: （testing.md「確かめる高さ」の (c)）。
ROOT = DATA_DIR / "road_network"

NETWORK_SHAPE = shape_digest(RoadNetwork, *NETWORK_SQL_SOURCES)

_MANIFEST = "manifest.json"
#: manifestの中の、配列を作った入力の指紋の名前（`RoadNetwork`の列ではないので、`load`は読まない）。
_INPUTS = "inputs"
_DIRECTORY_PATTERN = re.compile(r"^(?P<shape>[0-9a-f]+)-r(?P<revision>\d+|x)$")
# 行を流す単位と、材料を1回で引く区間の数。材料は区間ごとに列の値を作るため、1回ぶんの
# 一時的なメモリがこの数に比例する。
_STREAM_CHUNK = 200_000
_MATERIAL_BATCH = 200_000


def directory_name(revision: int | None) -> str:
    return f"{NETWORK_SHAPE}-r{'x' if revision is None else revision}"


def _directories() -> Iterator[tuple[Path, re.Match[str]]]:
    """置き場の名前の形をしたディレクトリと、名前の照合の結果（書きかけは名前の形に合わないので含まない）。"""
    for path in ROOT.glob("*"):
        match = _DIRECTORY_PATTERN.match(path.name)
        if match is not None and path.is_dir():
            yield path, match


def _latest_directory() -> Path | None:
    """形の署名が一致するもののうち、世代が最も新しい置き場。無ければNone。

    世代が読めなかったDBで作ったもの（`-rx`）は、世代のあるものより古いとみなす。
    """
    best: tuple[int, Path] | None = None
    for path, match in _directories():
        if match["shape"] != NETWORK_SHAPE:
            continue
        revision = -1 if match["revision"] == "x" else int(match["revision"])
        if best is None or revision > best[0]:
            best = (revision, path)
    return None if best is None else best[1]


def save(network: RoadNetwork) -> Path:
    """置き場を作って書き、同じ形で世代の古い置き場を消す。同じ世代の置き場が既にあれば書かずにそれを返す。"""
    target = ROOT / directory_name(network.revision)
    if target.exists():
        return target
    return publish(write_pending(network))


def write_pending(network: RoadNetwork, inputs: str | None = None) -> Path:
    """読み手（`_latest_directory`）が拾わない名前で書き、そのディレクトリを返す。`publish`で世代の名前にする。

    `inputs`は配列を作った入力の指紋（作り手が決める）。次の作り直しが`reuse_pending`で同じ入力の置き場を探す。
    """
    temporary = _new_pending(network.revision)
    values: dict[str, object] = {_INPUTS: inputs}
    for f in fields(network):
        value = getattr(network, f.name)
        if isinstance(value, np.ndarray):
            np.save(temporary / f"{f.name}.npy", value, allow_pickle=False)
        else:
            values[f.name] = value
    _write_manifest(temporary, values)
    return temporary


def reuse_pending(inputs: str, revision: int) -> Path | None:
    """今の形で世代が最も新しい置き場が`inputs`から作ったものなら、その配列を`revision`の世代として読み手が拾わない名前に
    出し直し、そのディレクトリを返す（`publish`で世代の名前にする）。無ければNone。

    配列はハードリンクで置く——書き直さず、前の世代の置き場が`publish`で消えても中身は残る。
    """
    latest = _latest_directory()
    if latest is None:
        return None
    values = _read_manifest(latest)
    if values.get(_INPUTS) != inputs:
        return None
    temporary = _new_pending(revision)
    for path in latest.glob("*.npy"):
        os.link(path, temporary / path.name)
    _write_manifest(temporary, {**values, "revision": revision})
    return temporary


def _new_pending(revision: int | None) -> Path:
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = ROOT / f".{directory_name(revision)}.tmp-{os.getpid()}"
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir()
    return temporary


def _write_manifest(directory: Path, values: dict[str, object]) -> None:
    (directory / _MANIFEST).write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")


def _read_manifest(directory: Path) -> dict[str, Any]:
    return json.loads((directory / _MANIFEST).read_text(encoding="utf-8"))


def publish(pending: Path) -> Path:
    """`write_pending`が書いたものを世代の名前へ付け替え、同じ形で世代の古い置き場を消す。"""
    revision = _read_manifest(pending)["revision"]
    target = ROOT / directory_name(revision)
    try:
        pending.rename(target)
    except OSError:
        # 同じ世代を別の処理が先に書き終えた。中身は同じなので、こちらの書きかけを捨てる。
        shutil.rmtree(pending, ignore_errors=True)
        if not target.exists():
            raise
    for removed in prune(target):
        logger.info("古い道路網の置き場を消しました %s", removed.name)
    logger.info("道路網の置き場を作りました %s", target.name)
    return target


def load(directory: Path) -> RoadNetwork:
    """置き場を読む。配列はメモリマップで開く——常に要る列だけがメモリに載る。"""
    values = _read_manifest(directory)
    arguments: dict[str, object] = {}
    for f in fields(RoadNetwork):
        if f.name in values:
            arguments[f.name] = _as_tuples(values[f.name])
        else:
            arguments[f.name] = np.load(directory / f"{f.name}.npy", mmap_mode="r", allow_pickle=False)
    return RoadNetwork(**arguments)  # type: ignore[arg-type]


class RoadNetworkUnavailableError(RuntimeError):
    """今のコードの形の置き場が1つも無い（デプロイの前処理かバッチが作っていない）。"""


#: 読み込み済みの置き場とその中身。プロセスの中で全リクエストが共有する（読み取り専用）。
_loaded: tuple[Path, RoadNetwork] | None = None


def current() -> RoadNetwork:
    """今の形の署名で世代が最も新しい置き場の中身。

    呼ぶたびに置き場を見て、読み込み済みより新しいもの（バッチが作り直した）があれば読み直す。
    読むのはメモリマップを開くだけなので、見るたびの費用はディレクトリの一覧程度に収まる。
    """
    global _loaded
    latest = _latest_directory()
    if latest is None:
        raise RoadNetworkUnavailableError(
            f"道路網の置き場がありません（{ROOT}、形の署名 {NETWORK_SHAPE}）。scripts/build_road_network.py で作る")
    if _loaded is None or _loaded[0] != latest:
        _loaded = (latest, load(latest))
        logger.info("道路網を読みました %s 有向の区間=%d", latest.name, _loaded[1].edge_count)
    return _loaded[1]


def _as_tuples(value: object) -> object:
    """JSONの配列をtupleへ戻す（`RoadNetwork`の語彙・列の並びはtupleで持つ）。"""
    if isinstance(value, list):
        return tuple(_as_tuples(item) for item in value)
    return value


def prune(keep: Path) -> list[Path]:
    """今の形の署名で、`keep`でない世代の置き場を消す（消したものを返す）。

    形の署名が違う置き場は消さない——デプロイの前処理が新しい署名の置き場を作る間も、
    古いコンテナは古い署名の置き場を読んでいる。
    """
    removed = []
    for path, match in _directories():
        if path == keep or match["shape"] != NETWORK_SHAPE:
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path)
    return removed


def prune_other_shapes() -> int:
    """今のコードの形の署名でない置き場を消し、解放したバイト数を返す。

    backendの起動後に呼ぶ——デプロイで入れ替わるまでは、旧コンテナが古い署名の置き場を読んでいる。
    """
    freed = 0
    for path, match in _directories():
        if match["shape"] == NETWORK_SHAPE:
            continue
        freed += sum(f.stat().st_size for f in path.iterdir() if f.is_file())
        shutil.rmtree(path, ignore_errors=True)
        logger.info("古い形の道路網の置き場を消しました %s", path.name)
    return freed


async def ensure_current(session_factory: async_sessionmaker[AsyncSession]) -> Path:
    """今の派生データの世代・今の形の置き場を用意する。既にあれば作らない。"""
    async with session_factory() as session:
        repository = RoadGraphRepository(session)
        revision = (await repository.get_data_revisions()).derived
        target = ROOT / directory_name(revision)
        if target.exists():
            logger.info("道路網の置き場は作成済みです %s", target.name)
            return target
        network = await build(repository, revision)
    return save(network)


async def build(repository: RoadGraphRepository, revision: int | None) -> RoadNetwork:
    """DBから道路網全体を読み、`revision`の世代の`RoadNetwork`を組む。"""
    started = time.monotonic()
    node_columns = await _read_nodes(repository)
    node_osm_id = node_columns["osm_node_id"]
    edges = await _read_directed_edges(repository, node_osm_id)
    topology_s = time.monotonic() - started
    logger.info(
        "道路網のつながりを読みました ノード=%d 有向の区間=%d 端点のノードが無く落とした有向の区間=%d %.0f秒",
        len(node_osm_id), len(edges["way"]), edges["dropped_without_endpoint"], topology_s,
    )

    materials = await _read_materials(repository, edges["way"], edges["segment"], edges["forward"])
    logger.info("道路網の材料を読みました 有向の区間=%d %.0f秒", len(edges["way"]), time.monotonic() - started - topology_s)
    return RoadNetwork(
        revision=revision,
        node_osm_id=node_osm_id,
        node_lat=node_columns["latitude"],
        node_lon=node_columns["longitude"],
        node_has_signals=node_columns["has_traffic_signals"],
        node_max_rank=node_columns["max_highway_rank"],
        edge_way_id=edges["way"],
        edge_segment=edges["segment"],
        edge_forward=edges["forward"],
        edge_from=edges["from"],
        edge_to=edges["to"],
        edge_highway=edges["highway"],
        highway_vocab=edges["highway_vocab"],
        edge_min_lon=edges["min_lon"],
        edge_min_lat=edges["min_lat"],
        edge_max_lon=edges["max_lon"],
        edge_max_lat=edges["max_lat"],
        **materials,
    )


_NODE_DTYPES = {"osm_node_id": np.int64, "latitude": np.float64, "longitude": np.float64,
                "has_traffic_signals": np.bool_, "max_highway_rank": np.int64}
_EDGE_DTYPES = {"way": np.int64, "segment": np.int32, "forward": np.bool_, "from": np.int32, "to": np.int32,
                "highway": np.int16, "min_lon": np.float64, "min_lat": np.float64, "max_lon": np.float64,
                "max_lat": np.float64}
_BBOX_COLUMNS = ("min_lon", "min_lat", "max_lon", "max_lat")


async def _read_nodes(repository: RoadGraphRepository) -> dict[str, np.ndarray]:
    chunks: dict[str, list[np.ndarray]] = {name: [] for name in _NODE_DTYPES}
    async for rows in repository.stream_network_nodes(_STREAM_CHUNK):
        for name, dtype in _NODE_DTYPES.items():
            chunks[name].append(np.fromiter((getattr(r, name) for r in rows), dtype=dtype, count=len(rows)))
    return {name: _concatenate(parts, _NODE_DTYPES[name]) for name, parts in chunks.items()}


async def _read_directed_edges(repository: RoadGraphRepository, node_osm_id: np.ndarray) -> dict[str, Any]:
    """区間を有向の行へ広げる。一方通行は走れる向きだけ、端点のノードが無い区間は落とし、落とした
    有向の行の数を`dropped_without_endpoint`で返す（道の値の行は、区間が持つ外部キーが保証する）。"""
    highway_vocab: dict[str, int] = {}
    dropped_without_endpoint = 0
    parts: dict[str, list[np.ndarray]] = {name: [] for name in _EDGE_DTYPES}
    async for rows in repository.stream_network_edges(_STREAM_CHUNK):
        n = len(rows)
        way = np.fromiter((r.osm_way_id for r in rows), dtype=np.int64, count=n)
        segment = np.fromiter((r.segment_index for r in rows), dtype=np.int32, count=n)
        from_osm = np.fromiter((r.from_node_id for r in rows), dtype=np.int64, count=n)
        to_osm = np.fromiter((r.to_node_id for r in rows), dtype=np.int64, count=n)
        highway = np.fromiter(
            (highway_vocab.setdefault(r.highway, len(highway_vocab)) for r in rows), dtype=np.int16, count=n)
        bbox = {name: np.fromiter((getattr(r, name) for r in rows), dtype=np.float64, count=n)
                for name in _BBOX_COLUMNS}

        # 区間ごとに順方向・逆方向の2行を並べ、走れない向きを落とす。
        keep = np.fromiter((ok for r in rows for ok in travel_allowed(r.direction)), dtype=bool, count=2 * n)
        is_forward = np.tile([True, False], n)[keep]
        source = np.repeat(np.arange(n), 2)[keep]
        tail = np.where(is_forward, from_osm[source], to_osm[source])
        head = np.where(is_forward, to_osm[source], from_osm[source])
        tail_row, tail_found = _rows_of(node_osm_id, tail)
        head_row, head_found = _rows_of(node_osm_id, head)
        found = tail_found & head_found
        dropped_without_endpoint += int((~found).sum())
        source, is_forward = source[found], is_forward[found]

        parts["way"].append(way[source])
        parts["segment"].append(segment[source])
        parts["forward"].append(is_forward)
        parts["from"].append(tail_row[found].astype(np.int32))
        parts["to"].append(head_row[found].astype(np.int32))
        parts["highway"].append(highway[source])
        for name, values in bbox.items():
            parts[name].append(values[source])

    result: dict[str, Any] = {name: _concatenate(values, _EDGE_DTYPES[name]) for name, values in parts.items()}
    result["highway_vocab"] = tuple(sorted(highway_vocab, key=highway_vocab.__getitem__))
    result["dropped_without_endpoint"] = dropped_without_endpoint
    return result


def _rows_of(sorted_ids: np.ndarray, ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """`ids`の各要素が昇順の`sorted_ids`の何行目か、と、見つかったか。"""
    if len(sorted_ids) == 0:
        return np.zeros(len(ids), dtype=np.int64), np.zeros(len(ids), dtype=bool)
    rows = np.minimum(np.searchsorted(sorted_ids, ids), len(sorted_ids) - 1)
    return rows, sorted_ids[rows] == ids


async def _read_materials(
    repository: RoadGraphRepository, way: np.ndarray, segment: np.ndarray, forward: np.ndarray
) -> dict[str, Any]:
    """材料は`get_edge_material_arrays`で引く（式はタイル配信・軸スタジオと同じ`material_sql`の断片で、2か所に持たない）。"""
    edge_count = len(way)
    accident_years_covered = await repository.get_accident_years_covered()
    columns = MaterialColumns(edge_count)
    for start in range(0, edge_count, _MATERIAL_BATCH):
        stop = min(start + _MATERIAL_BATCH, edge_count)
        columns.add(await repository.get_edge_material_arrays(
            way[start:stop].tolist(), segment[start:stop].tolist(), forward[start:stop].tolist(), accident_years_covered))
        logger.info("材料 %d/%d", stop, edge_count)
    return columns.result()


class MaterialColumns:
    """区間の束ごとに引いた材料を、道路網全体の配列へ引いた順に詰める。

    書き込み先の配列を最初の束で確保して埋める——束ごとの配列を最後に連結すると、全体ぶんを
    2度持つ瞬間ができる。分類の材料は束ごとに語彙が違うので、道路網全体の語彙の番号へ付け替える。
    """

    def __init__(self, edge_count: int):
        self._edge_count = edge_count
        self._filled = 0
        self._arrays: dict[str, np.ndarray] = {}
        self._vocab: list[dict[str | None, int]] = []
        self._ids: dict[str, tuple[str, ...]] = {}

    def add(self, materials: EdgeMaterialArrays) -> None:
        """次の束を、前の束の続きの行へ詰める。"""
        if not self._arrays:
            self._ids = {"numeric_ids": materials.numeric_ids, "categorical_ids": materials.categorical_ids,
                         "hard_filter_ids": materials.hard_filter_ids}
            self._vocab = [{None: 0} for _ in materials.categorical_ids]
            self._arrays["categorical_codes"] = np.zeros(
                (self._edge_count, len(materials.categorical_ids)), dtype=np.int16)
            for name in _MATERIAL_ARRAY_FIELDS:
                value = getattr(materials, name)
                self._arrays[name] = np.empty((self._edge_count, *value.shape[1:]), dtype=value.dtype)
        start, stop = self._filled, self._filled + len(materials.distance_m)
        for name in _MATERIAL_ARRAY_FIELDS:
            self._arrays[name][start:stop] = getattr(materials, name)
        for column, values in enumerate(materials.categorical_columns):
            codes = self._vocab[column]
            to_network_code = np.array([codes.setdefault(v, len(codes)) for v in values.vocab], dtype=np.int16)
            self._arrays["categorical_codes"][start:stop, column] = to_network_code[values.codes]
        self._filled = stop

    def result(self) -> dict[str, Any]:
        """`RoadNetwork`の材料の欄。束が1つも無ければ断る。"""
        if not self._arrays:
            raise ValueError("道路網に区間が1本もありません")
        return {
            **self._ids,
            **self._arrays,
            "categorical_vocab": tuple(tuple(sorted(codes, key=codes.__getitem__)) for codes in self._vocab),
        }


#: `EdgeMaterialArrays`から、そのまま行を写す配列の列（分類の材料は束ごとの語彙の番号を全体の語彙の番号へ
#: 付け替えるので含めない）。
_MATERIAL_ARRAY_FIELDS = (
    "numeric_values", "hard_filter_flags", "distance_m", "bearing_deg", "mid_lat", "mid_lon",
    "elevation_present", "elevation_gain_m", "elevation_loss_m",
)


def _concatenate(parts: list[np.ndarray], dtype) -> np.ndarray:
    return np.concatenate(parts).astype(dtype, copy=False) if parts else np.zeros(0, dtype=dtype)
