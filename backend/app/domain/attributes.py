from dataclasses import dataclass

import numpy as np

from app.domain.strict_model import StrictModel


class ElevationAttribute(StrictModel):
    """Edgeへ紐付ける標高属性。Edge本体（domain/graph.py）とは独立して保持する。

    average_grade/max_grade/min_gradeは符号付き（登り=正、下り=負）。
    有効な標高が2点未満の場合は全フィールドNoneのまま返す。
    """

    edge_id: str
    start_elevation_m: float | None = None
    end_elevation_m: float | None = None
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    average_grade: float | None = None
    max_grade: float | None = None
    min_grade: float | None = None


# 舗装された公道としてありうる平均勾配の上限（%）。世界でも最急の公道が35%前後のため、
# これを超える値は道の起伏ではなくDEMの読み違い（両端が路面でない地物を指した等）である。
# 超えた区間は値を持たせず「データなし」にする——0次ハードフィルタは値の無い区間を
# 除外しない（`domain/hard_filters.py`）ので、誤った値で黙って経路から外すより安全側になる。
MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT = 40.0


@dataclass(frozen=True, slots=True)
class EdgeMaterialArrays:
    """区間の材料を、**dtypeごとに1つの2次元配列**で保持する表現。

    値はDBが導出したものをそのまま受ける（`MaterialSpec.value_sql`）。
    区間ごとのPythonオブジェクトを経由しない。

    材料ごとに別々の配列を持たず、`StaticEdgeScoreMatrix`と同じ「値の行列＋idの並び」の形に
    する。材料が増えてもフィールドは増えず、列の追加は`*_ids`が1つ伸びるだけになる。
    dtypeで3つに分かれるのは、真偽とカテゴリを数値の行列へ混ぜられないため（分け方は
    `MaterialSpec.dtype`と`bool_default`が決める。`material_array_group`が唯一の判定）。

    0次ハードフィルタの生フラグを同じ1回のクエリで求めてここへ持たせるのは、別に引くと
    区間の束ごとにもう1往復増えるため。

    標高の列は**材料ではない表示用の値**で、経路が確定したあとの区間について
    `domain/road_network.py: elevation_attribute`が`ElevationAttribute`を組み立てる。勾配そのものは材料
    `gradient_percent`にあるため、ここでは重複して持たない。
    """

    numeric_ids: tuple[str, ...]
    numeric_values: np.ndarray  # shape=(n, len(numeric_ids)), float64, NaN=欠損
    boolean_ids: tuple[str, ...]
    boolean_values: np.ndarray  # shape=(n, len(boolean_ids)), bool
    categorical_ids: tuple[str, ...]
    categorical_values: np.ndarray  # shape=(n, len(categorical_ids)), object
    # 0次ハードフィルタの生フラグ。フィルタ名がそのまま列で、`domain/hard_filters.py:
    # HARD_FILTER_VALUE_SQL`から生成する。**フィルタごとに専用のフィールドを作らない**。
    hard_filter_ids: tuple[str, ...]
    hard_filter_flags: np.ndarray  # shape=(n, len(hard_filter_ids)), bool
    # 区間そのものの値。グラフのオブジェクトから組み直さず、材料と同じクエリで受ける。
    distance_m: np.ndarray  # dtype=float64
    bearing_deg: np.ndarray  # dtype=float64, NaN=方位が決まらない
    mid_lat: np.ndarray  # dtype=float64
    mid_lon: np.ndarray  # dtype=float64
    elevation_present: np.ndarray  # dtype=bool
    elevation_start_m: np.ndarray  # dtype=float64, NaN=欠損
    elevation_end_m: np.ndarray
    elevation_gain_m: np.ndarray
    elevation_loss_m: np.ndarray
    elevation_max_grade: np.ndarray
    elevation_min_grade: np.ndarray

    def __len__(self) -> int:
        return len(self.distance_m)

    def columns(self) -> dict[str, np.ndarray]:
        """材料id→その列。行列の列はビューのためコピーしない。"""
        return {
            **{m: self.numeric_values[:, i] for i, m in enumerate(self.numeric_ids)},
            **{m: self.boolean_values[:, i] for i, m in enumerate(self.boolean_ids)},
            **{m: self.categorical_values[:, i] for i, m in enumerate(self.categorical_ids)},
        }

    def hard_filter_columns(self) -> dict[str, np.ndarray]:
        """0次フィルタ名→該当フラグ。行列の列はビューのためコピーしない。"""
        return {name: self.hard_filter_flags[:, i] for i, name in enumerate(self.hard_filter_ids)}


def elevation_values_sql(vertices: str) -> str:
    """区間の頂点列から、標高と勾配の値を出すSQL。

    `vertices`は`(osm_way_id, segment_index, ord, lon, lat, elev, on_structure)`を返す関係。
    `elev`がNULLの頂点は評価から外す。**外した後に隣り合う2点でも、元の点列では間に欠損を
    挟んでいることがある**——そのまま隣接扱いすると、欠損区間の起伏が均された勾配として
    混入する。距離（両端の座標は常に既知）と、獲得/消失/勾配（欠損を挟むと信頼できない）を
    分け、元の点列でも真に隣接していたペアだけを後者へ寄与させる。

    `on_structure`（橋・高架・トンネル）は**両端だけ**を使う。配信元のDEMは地表面の値で
    構造物の高さを反映しないため（https://maps.gsi.go.jp/development/hyokochi.html に明記）、
    中間の点は桁や坑道ではなく下の地形を指す。谷を渡る平らな橋で、谷底の起伏がそのまま
    獲得標高へ積まれてしまう。橋台・坑口は道が地面と接する位置なので、両端の標高は使える。

    値が出せない区間（有効な標高が2点未満）は返らない。
    """
    return f"""
WITH v AS ({vertices}),
known AS (SELECT * FROM v WHERE elev IS NOT NULL),
ends AS (
    SELECT osm_way_id, segment_index, bool_or(on_structure) AS on_structure,
           count(*) AS n,
           (array_agg(elev ORDER BY ord))[1] AS start_e,
           (array_agg(elev ORDER BY ord DESC))[1] AS end_e
    FROM known GROUP BY osm_way_id, segment_index),
stepped AS (
    SELECT osm_way_id, segment_index, ord, elev,
           lag(ord)  OVER w AS prev_ord,
           lag(elev) OVER w AS prev_elev,
           lag(lon)  OVER w AS prev_lon,
           lag(lat)  OVER w AS prev_lat,
           lon, lat
    FROM known WINDOW w AS (PARTITION BY osm_way_id, segment_index ORDER BY ord)),
pairs AS (
    SELECT osm_way_id, segment_index, elev - prev_elev AS diff,
           ord - prev_ord = 1 AS adjacent,
           ST_Distance(ST_MakePoint(prev_lon, prev_lat)::geography,
                       ST_MakePoint(lon, lat)::geography) AS d
    FROM stepped WHERE prev_ord IS NOT NULL),
agg AS (
    SELECT osm_way_id, segment_index, sum(d) AS total_d,
           coalesce(sum(greatest(diff, 0))  FILTER (WHERE adjacent), 0) AS gain,
           coalesce(sum(greatest(-diff, 0)) FILTER (WHERE adjacent), 0) AS loss,
           max(diff / d * 100) FILTER (WHERE adjacent AND d > 0) AS max_g,
           min(diff / d * 100) FILTER (WHERE adjacent AND d > 0) AS min_g
    FROM pairs GROUP BY osm_way_id, segment_index),
raw AS (
    SELECT e.osm_way_id, e.segment_index, e.on_structure, e.start_e, e.end_e,
           a.gain, a.loss, a.max_g, a.min_g,
           CASE WHEN a.total_d > 0
                 AND abs((e.end_e - e.start_e) / a.total_d * 100)
                     <= {MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT}
                THEN (e.end_e - e.start_e) / a.total_d * 100 END AS avg_g
    FROM ends e JOIN agg a USING (osm_way_id, segment_index)
    WHERE e.n >= 2)
SELECT osm_way_id, segment_index,
       round(start_e::numeric, 1) AS start_elevation_m,
       round(end_e::numeric, 1)   AS end_elevation_m,
       round((CASE WHEN on_structure THEN greatest(end_e - start_e, 0)
                   ELSE gain END)::numeric, 1)  AS elevation_gain_m,
       round((CASE WHEN on_structure THEN greatest(start_e - end_e, 0)
                   ELSE loss END)::numeric, 1)  AS elevation_loss_m,
       round(avg_g::numeric, 2) AS average_grade,
       round((CASE WHEN on_structure THEN avg_g ELSE max_g END)::numeric, 2) AS max_grade,
       round((CASE WHEN on_structure THEN avg_g ELSE min_g END)::numeric, 2) AS min_grade
FROM raw
"""
