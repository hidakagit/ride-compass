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
