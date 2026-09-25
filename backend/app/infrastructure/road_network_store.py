"""取込範囲全体の道路網（`domain/road_network.py: RoadNetwork`）をDBから作り、ディスクへ置き、読む。

DBから作ると数分かかる。そのため作るのはバッチ（世代を進めた直後）とデプロイの前処理
（`scripts/build_road_network.py`）だけで、backendは置かれたものを読むだけにする。

置き場は`data/road_network/<形の署名>-r<派生データの世代>/`。中に配列ごとの`.npy`と、
配列でない値（語彙・列の並び・世代）を書いた`manifest.json`を置く。書き終えるまでは一時
ディレクトリに書き、最後に名前を付け替える——途中で落ちても、読む側が書きかけを掴まない。

形の署名は`RoadNetwork`の列と、読み出しのSQL（材料の式を含む）から導く。材料の式を変えた
コードをデプロイすると署名が変わり、古い置き場は選ばれなくなる。
"""

import json
import logging
import os
import re
import shutil
import time
from dataclasses import fields
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.graph import LeanEdge, edge_key
from app.domain.road_network import RoadNetwork
from app.infrastructure.cache_identity import shape_digest
from app.infrastructure.road_graph_repository import NETWORK_SQL_SOURCES, RoadGraphRepository

logger = logging.getLogger("ridecompass.road_network")

ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "road_network"

NETWORK_SHAPE = shape_digest(RoadNetwork, *NETWORK_SQL_SOURCES)

_MANIFEST = "manifest.json"
_DIRECTORY_PATTERN = re.compile(r"^(?P<shape>[0-9a-f]+)-r(?P<revision>\d+|x)$")
# 行を流す単位と、材料を1回で引く区間の数。材料は区間ごとに列の値を作るため、1回ぶんの
# 一時的なメモリがこの数に比例する。
_STREAM_CHUNK = 200_000
_MATERIAL_BATCH = 200_000


def directory_name(revision: int | None) -> str:
    return f"{NETWORK_SHAPE}-r{'x' if revision is None else revision}"


def latest_directory() -> Path | None:
    """形の署名が一致するもののうち、世代が最も新しい置き場。無ければNone。

    世代が読めなかったDBで作ったもの（`-rx`）は、世代のあるものより古いとみなす。
    """
    best: tuple[int, Path] | None = None
    for path in ROOT.glob("*"):
        match = _DIRECTORY_PATTERN.match(path.name)
        if not path.is_dir() or match is None or match["shape"] != NETWORK_SHAPE:
            continue
        revision = -1 if match["revision"] == "x" else int(match["revision"])
        if best is None or revision > best[0]:
            best = (revision, path)
    return None if best is None else best[1]


def save(network: RoadNetwork) -> Path:
    """置き場を作って書く。同じ世代の置き場が既にあれば書かずにそれを返す。"""
    target = ROOT / directory_name(network.revision)
    if target.exists():
        return target
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = ROOT / f".{target.name}.tmp-{os.getpid()}"
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir()
    values: dict[str, object] = {}
    for f in fields(network):
        value = getattr(network, f.name)
        if isinstance(value, np.ndarray):
            np.save(temporary / f"{f.name}.npy", value, allow_pickle=False)
        else:
            values[f.name] = value
    (temporary / _MANIFEST).write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
    try:
        temporary.rename(target)
    except OSError:
        # 同じ世代を別の処理が先に書き終えた。中身は同じなので、こちらの書きかけを捨てる。
        shutil.rmtree(temporary, ignore_errors=True)
        if not target.exists():
            raise
    return target


def load(directory: Path) -> RoadNetwork:
    """置き場を読む。配列はメモリマップで開く——常に要る列だけがメモリに載る。"""
    values = json.loads((directory / _MANIFEST).read_text(encoding="utf-8"))
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
    latest = latest_directory()
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
    """`keep`と同じ形の署名で世代が古い置き場を消す（消したものを返す）。

    形の署名が違う置き場は消さない——デプロイの前処理が新しい署名の置き場を作る間も、
    古いコンテナは古い署名の置き場を読んでいる。
    """
    keep_match = _DIRECTORY_PATTERN.match(keep.name)
    if keep_match is None:
        return []
    removed = []
    for path in ROOT.glob("*"):
        match = _DIRECTORY_PATTERN.match(path.name)
        if path == keep or not path.is_dir() or match is None or match["shape"] != keep_match["shape"]:
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path)
    return removed


def prune_other_shapes() -> int:
    """今のコードの形の署名でない置き場を消し、解放したバイト数を返す。

    backendの起動後に呼ぶ——デプロイで入れ替わるまでは、旧コンテナが古い署名の置き場を読んでいる。
    """
    freed = 0
    for path in ROOT.glob("*"):
        match = _DIRECTORY_PATTERN.match(path.name)
        if not path.is_dir() or match is None or match["shape"] == NETWORK_SHAPE:
            continue
        freed += sum(f.stat().st_size for f in path.iterdir() if f.is_file())
        shutil.rmtree(path, ignore_errors=True)
        logger.info("古い形の道路網の置き場を消しました %s", path.name)
    return freed


async def ensure_current(session_factory: async_sessionmaker[AsyncSession]) -> Path:
    """今の派生データの世代・今の形の置き場を用意する。既にあれば作らない。

    作ったときは、同じ形で世代の古い置き場を消す。
    """
    async with session_factory() as session:
        repository = RoadGraphRepository(session)
        target = ROOT / directory_name(await repository.get_derived_data_revision())
        if target.exists():
            logger.info("道路網の置き場は作成済みです %s", target.name)
            return target
        network = await build(repository)
    path = save(network)
    for removed in prune(path):
        logger.info("古い道路網の置き場を消しました %s", removed.name)
    logger.info("道路網の置き場を作りました %s", path.name)
    return path


async def build(repository: RoadGraphRepository) -> RoadNetwork:
    """DBから道路網全体を読み、`RoadNetwork`を組む。"""
    started = time.monotonic()
    revision = await repository.get_derived_data_revision()
    node_columns = await _read_nodes(repository)
    node_osm_id = node_columns["osm_node_id"]
    edges = await _read_directed_edges(repository, node_osm_id)
    topology_s = time.monotonic() - started
    logger.info("道路網のつながりを読みました ノード=%d 有向の区間=%d %.0f秒", len(node_osm_id), len(edges["way"]), topology_s)

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


async def _read_nodes(repository: RoadGraphRepository) -> dict[str, np.ndarray]:
    chunks: dict[str, list[np.ndarray]] = {
        "osm_node_id": [], "latitude": [], "longitude": [], "has_traffic_signals": [], "max_highway_rank": [],
    }
    dtypes = {"osm_node_id": np.int64, "latitude": np.float64, "longitude": np.float64,
              "has_traffic_signals": np.bool_, "max_highway_rank": np.int64}
    async for rows in repository.stream_network_nodes(_STREAM_CHUNK):
        for name, dtype in dtypes.items():
            chunks[name].append(np.fromiter((getattr(r, name) for r in rows), dtype=dtype, count=len(rows)))
    return {name: _concatenate(parts, dtypes[name]) for name, parts in chunks.items()}


async def _read_directed_edges(repository: RoadGraphRepository, node_osm_id: np.ndarray) -> dict[str, Any]:
    """区間を有向の行へ広げる。一方通行は走れる向きだけ、端点のノードが無い区間は落とす
    （道の行が無い区間は`_NETWORK_EDGES_SQL`の結合で既に落ちている）。"""
    highway_vocab: dict[str | None, int] = {None: 0}
    parts: dict[str, list[np.ndarray]] = {
        name: [] for name in ("way", "segment", "forward", "from", "to", "highway",
                              "min_lon", "min_lat", "max_lon", "max_lat")
    }
    async for rows in repository.stream_network_edges(_STREAM_CHUNK):
        n = len(rows)
        way = np.fromiter((r.osm_way_id for r in rows), dtype=np.int64, count=n)
        segment = np.fromiter((r.segment_index for r in rows), dtype=np.int32, count=n)
        from_osm = np.fromiter((r.from_node_id for r in rows), dtype=np.int64, count=n)
        to_osm = np.fromiter((r.to_node_id for r in rows), dtype=np.int64, count=n)
        direction = [r.direction for r in rows]
        highway = np.fromiter(
            (highway_vocab.setdefault(r.highway, len(highway_vocab)) for r in rows), dtype=np.int16, count=n)
        bbox = {name: np.fromiter((getattr(r, name) for r in rows), dtype=np.float64, count=n)
                for name in ("min_lon", "min_lat", "max_lon", "max_lat")}

        # 区間ごとに順方向・逆方向の2行を並べ、走れない向きを落とす。
        forward_ok = np.fromiter((d != "backward" for d in direction), dtype=bool, count=n)
        backward_ok = np.fromiter((d != "forward" for d in direction), dtype=bool, count=n)
        keep = np.column_stack([forward_ok, backward_ok]).ravel()
        is_forward = np.tile([True, False], n)[keep]
        source = np.repeat(np.arange(n), 2)[keep]
        tail = np.where(is_forward, from_osm[source], to_osm[source])
        head = np.where(is_forward, to_osm[source], from_osm[source])
        tail_row, tail_found = _rows_of(node_osm_id, tail)
        head_row, head_found = _rows_of(node_osm_id, head)
        found = tail_found & head_found
        source, is_forward = source[found], is_forward[found]

        parts["way"].append(way[source])
        parts["segment"].append(segment[source])
        parts["forward"].append(is_forward)
        parts["from"].append(tail_row[found].astype(np.int32))
        parts["to"].append(head_row[found].astype(np.int32))
        parts["highway"].append(highway[source])
        for name, values in bbox.items():
            parts[name].append(values[source])

    dtypes = {"way": np.int64, "segment": np.int32, "forward": np.bool_, "from": np.int32, "to": np.int32,
              "highway": np.int16, "min_lon": np.float64, "min_lat": np.float64, "max_lon": np.float64,
              "max_lat": np.float64}
    result: dict[str, Any] = {name: _concatenate(values, dtypes[name]) for name, values in parts.items()}
    result["highway_vocab"] = tuple(sorted(highway_vocab, key=highway_vocab.__getitem__))
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
    """材料は範囲指定の読み出しと同じ`get_edge_material_arrays`で引く（材料の式を2か所に持たない）。

    書き込み先の配列を先に確保し、区間の束ごとに埋める——束ごとの配列を最後に連結すると、
    全体ぶんを2度持つ瞬間ができる。
    """
    edge_count = len(way)
    accident_years_covered = await repository.get_accident_years_covered()
    arrays: dict[str, np.ndarray] = {}
    vocab: list[dict[str | None, int]] = []
    ids: dict[str, tuple[str, ...]] = {}
    for start in range(0, edge_count, _MATERIAL_BATCH):
        stop = min(start + _MATERIAL_BATCH, edge_count)
        batch = [
            LeanEdge(edge_id=edge_key(int(w), int(s), bool(f)), from_node_id="", to_node_id="", geometry=[],
                     distance_m=0.0, osm_way_id=int(w), segment_index=int(s), forward=bool(f))
            for w, s, f in zip(way[start:stop], segment[start:stop], forward[start:stop], strict=True)
        ]
        materials = await repository.get_edge_material_arrays(batch, accident_years_covered)
        if not arrays:
            ids = {"numeric_ids": materials.numeric_ids, "boolean_ids": materials.boolean_ids,
                   "categorical_ids": materials.categorical_ids, "hard_filter_ids": materials.hard_filter_ids}
            vocab = [{None: 0} for _ in materials.categorical_ids]
            arrays["categorical_codes"] = np.zeros((edge_count, len(materials.categorical_ids)), dtype=np.int16)
            for name in _MATERIAL_ARRAY_FIELDS:
                value = getattr(materials, name)
                arrays[name] = np.empty((edge_count, *value.shape[1:]), dtype=value.dtype)
        for name in _MATERIAL_ARRAY_FIELDS:
            arrays[name][start:stop] = getattr(materials, name)
        for column, values in enumerate(materials.categorical_values.T):
            codes = vocab[column]
            arrays["categorical_codes"][start:stop, column] = [codes.setdefault(v, len(codes)) for v in values]
        logger.info("材料 %d/%d", stop, edge_count)
    if not arrays:
        raise ValueError("道路網に区間が1本もありません")
    return {
        **ids,
        **arrays,
        "categorical_vocab": tuple(tuple(sorted(codes, key=codes.__getitem__)) for codes in vocab),
    }


#: `EdgeMaterialArrays`から、そのまま行を写す配列の列（分類の値は番号へ直すので含めない）。
_MATERIAL_ARRAY_FIELDS = (
    "numeric_values", "boolean_values", "hard_filter_flags", "distance_m", "bearing_deg", "mid_lat", "mid_lon",
    "elevation_present", "elevation_start_m", "elevation_end_m", "elevation_gain_m", "elevation_loss_m",
    "elevation_max_grade", "elevation_min_grade",
)


def _concatenate(parts: list[np.ndarray], dtype) -> np.ndarray:
    return np.concatenate(parts).astype(dtype, copy=False) if parts else np.zeros(0, dtype=dtype)
