"""取込範囲全体の道路網を、有向の区間とノードの**番号**で引ける列の配列として持つ。

生成のたびに範囲を切り出して使う（`RoadGraphEngine`）。区間ごとのオブジェクトも、区間の
文字列の鍵を引く辞書も持たない——範囲ごとに作るとメモリが範囲の数だけ積み上がり、1回の
生成でもコンテナの上限に届くため。区間の文字列の鍵は、API・経路の境目で番号から作る。

行の並び:
- ノードは`osm_node_id`の昇順。区間の両端はこの行番号で持つ。
- 有向の区間は`(osm_way_id, segment_index)`の昇順、同じ区間では順方向が先。一方通行は
  走れる向きの行だけを持つ。材料の列もこの行順。

分類の材料は文字列のまま持たず、列ごとの語彙への番号で持つ（番号0は値なし）。
"""

from dataclasses import dataclass, fields

import numpy as np

from app.domain.attributes import EdgeMaterialArrays, ElevationAttribute
from app.domain.material_catalog import GRADIENT_PERCENT


@dataclass(frozen=True, eq=False)
class RoadNetwork:
    """`revision`は作った時点の派生データの世代（`derived_data_meta.revision`）。"""

    revision: int | None

    node_osm_id: np.ndarray  # int64, 昇順
    node_lat: np.ndarray  # float64
    node_lon: np.ndarray  # float64
    node_has_signals: np.ndarray  # bool
    node_max_rank: np.ndarray  # int64

    edge_way_id: np.ndarray  # int64
    edge_segment: np.ndarray  # int32
    edge_forward: np.ndarray  # bool
    edge_from: np.ndarray  # int32（ノードの行）
    edge_to: np.ndarray  # int32
    # 道路の種別（`highway`タグ）の語彙への番号。
    edge_highway: np.ndarray  # int16
    highway_vocab: tuple[str | None, ...]
    # 区間の形の外接矩形。範囲の切り出しに使う。
    edge_min_lon: np.ndarray  # float64
    edge_min_lat: np.ndarray
    edge_max_lon: np.ndarray
    edge_max_lat: np.ndarray

    # 材料（`EdgeMaterialArrays`と同じ列。区間と同じ行順）。
    numeric_ids: tuple[str, ...]
    numeric_values: np.ndarray  # (区間, 列) float64, NaN=欠損
    boolean_ids: tuple[str, ...]
    boolean_values: np.ndarray  # (区間, 列) bool
    categorical_ids: tuple[str, ...]
    categorical_codes: np.ndarray  # (区間, 列) int16。0は値なし
    categorical_vocab: tuple[tuple[str | None, ...], ...]  # 列ごとの語彙。先頭は必ずNone
    hard_filter_ids: tuple[str, ...]
    hard_filter_flags: np.ndarray  # (区間, 列) bool
    distance_m: np.ndarray  # float64
    bearing_deg: np.ndarray  # float64, NaN=方位が決まらない
    mid_lat: np.ndarray
    mid_lon: np.ndarray
    elevation_present: np.ndarray  # bool
    elevation_start_m: np.ndarray  # float64, NaN=欠損
    elevation_end_m: np.ndarray
    elevation_gain_m: np.ndarray
    elevation_loss_m: np.ndarray
    elevation_max_grade: np.ndarray
    elevation_min_grade: np.ndarray

    def __post_init__(self) -> None:
        """行数と列数が揃っていることを、組み立てた場所で確かめる。

        揃わないまま使うと、別の区間の材料・別のノードの座標を黙って読む。
        """
        node_count = len(self.node_osm_id)
        edge_count = len(self.edge_way_id)
        wrong = {
            f.name: len(value)
            for f in fields(self)
            if isinstance(value := getattr(self, f.name), np.ndarray)
            and len(value) != (node_count if f.name.startswith("node_") else edge_count)
        }
        wrong_columns = {
            name: (matrix.shape[1], len(ids))
            for name, matrix, ids in (
                ("numeric_values", self.numeric_values, self.numeric_ids),
                ("boolean_values", self.boolean_values, self.boolean_ids),
                ("categorical_codes", self.categorical_codes, self.categorical_ids),
                ("hard_filter_flags", self.hard_filter_flags, self.hard_filter_ids),
            )
            if matrix.shape[1] != len(ids)
        }
        if len(self.categorical_vocab) != len(self.categorical_ids):
            wrong_columns["categorical_vocab"] = (len(self.categorical_vocab), len(self.categorical_ids))
        if wrong or wrong_columns:
            raise ValueError(
                f"道路網の配列の形が揃っていません ノード={node_count} 区間={edge_count} "
                f"行数={wrong} 列数={wrong_columns}"
            )

    @property
    def node_count(self) -> int:
        return len(self.node_osm_id)

    @property
    def edge_count(self) -> int:
        return len(self.edge_way_id)


@dataclass(frozen=True, eq=False)
class RoadSlice:
    """範囲に掛かる区間だけを取り出したもの（1回の生成が使う単位）。

    区間は全体の行番号の昇順で持ち、材料・スコア行列の行もこの順に揃える。ノードは使うものだけを
    全体の行番号の昇順に並べ直し、その位置（切り出しの中のノード番号）で区間の両端を持つ。
    """

    network: RoadNetwork
    rows: np.ndarray  # int64, 全体の区間の行
    nodes: np.ndarray  # int64, 全体のノードの行
    edge_from: np.ndarray  # int64, 切り出しの中のノード番号
    edge_to: np.ndarray

    @property
    def edge_count(self) -> int:
        return len(self.rows)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def node_lat(self) -> np.ndarray:
        return np.asarray(self.network.node_lat[self.nodes], dtype=np.float64)

    @property
    def node_lon(self) -> np.ndarray:
        return np.asarray(self.network.node_lon[self.nodes], dtype=np.float64)


def slice_network(
    network: RoadNetwork, min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> RoadSlice:
    """区間の形の外接矩形が範囲に重なる区間を取り出す。範囲の外へはみ出す区間も、端点ごと含む。"""
    overlaps = (
        (np.asarray(network.edge_max_lon) >= min_lon) & (np.asarray(network.edge_min_lon) <= max_lon)
        & (np.asarray(network.edge_max_lat) >= min_lat) & (np.asarray(network.edge_min_lat) <= max_lat)
    )
    rows = np.flatnonzero(overlaps)
    tail = np.asarray(network.edge_from[rows], dtype=np.int64)
    head = np.asarray(network.edge_to[rows], dtype=np.int64)
    nodes, inverse = np.unique(np.concatenate([tail, head]), return_inverse=True)
    return RoadSlice(
        network=network, rows=rows, nodes=nodes,
        edge_from=inverse[: len(rows)].astype(np.int64), edge_to=inverse[len(rows):].astype(np.int64),
    )


def material_arrays_of(road: RoadSlice) -> EdgeMaterialArrays:
    """切り出した区間の材料（行は`road.rows`の順）。分類の材料は語彙の値へ戻す。"""
    network, rows = road.network, road.rows
    categorical = np.empty((len(rows), len(network.categorical_ids)), dtype=object)
    for column, vocab in enumerate(network.categorical_vocab):
        categorical[:, column] = np.array(vocab, dtype=object)[network.categorical_codes[rows, column]]

    def take(values: np.ndarray) -> np.ndarray:
        return np.asarray(values[rows])

    return EdgeMaterialArrays(
        numeric_ids=network.numeric_ids, numeric_values=take(network.numeric_values),
        boolean_ids=network.boolean_ids, boolean_values=take(network.boolean_values),
        categorical_ids=network.categorical_ids, categorical_values=categorical,
        hard_filter_ids=network.hard_filter_ids, hard_filter_flags=take(network.hard_filter_flags),
        distance_m=take(network.distance_m), bearing_deg=take(network.bearing_deg),
        mid_lat=take(network.mid_lat), mid_lon=take(network.mid_lon),
        elevation_present=take(network.elevation_present),
        elevation_start_m=take(network.elevation_start_m), elevation_end_m=take(network.elevation_end_m),
        elevation_gain_m=take(network.elevation_gain_m), elevation_loss_m=take(network.elevation_loss_m),
        elevation_max_grade=take(network.elevation_max_grade),
        elevation_min_grade=take(network.elevation_min_grade),
    )


def elevation_attribute(network: RoadNetwork, row: int, edge_id: str) -> ElevationAttribute | None:
    """全体の行`row`の区間の標高属性。標高が未計算ならNone。平均勾配は材料`gradient_percent`の値
    （表示用の標高列と重複して持たないため、勾配だけは材料の列から読む）。"""
    if not network.elevation_present[row]:
        return None
    grade_column = network.numeric_ids.index(GRADIENT_PERCENT)
    return ElevationAttribute(
        edge_id=edge_id,
        start_elevation_m=_none_if_nan(network.elevation_start_m[row]),
        end_elevation_m=_none_if_nan(network.elevation_end_m[row]),
        elevation_gain_m=_none_if_nan(network.elevation_gain_m[row]),
        elevation_loss_m=_none_if_nan(network.elevation_loss_m[row]),
        average_grade=_none_if_nan(network.numeric_values[row, grade_column]),
        max_grade=_none_if_nan(network.elevation_max_grade[row]),
        min_grade=_none_if_nan(network.elevation_min_grade[row]),
    )


def _none_if_nan(value) -> float | None:
    return None if value is None or np.isnan(value) else float(value)


def edge_row_of(network: RoadNetwork, osm_way_id: int, segment_index: int, forward: bool) -> int | None:
    """`(道, 区間番号, 向き)`の区間の全体の行。無ければNone（一方通行の逆向き・取込範囲の外）。

    区間は道のidの昇順に並ぶため、道の行の範囲を二分探索で絞ってから探す。
    """
    ways = network.edge_way_id
    start = int(np.searchsorted(ways, osm_way_id, side="left"))
    stop = int(np.searchsorted(ways, osm_way_id, side="right"))
    for row in range(start, stop):
        if int(network.edge_segment[row]) == segment_index and bool(network.edge_forward[row]) == forward:
            return row
    return None
