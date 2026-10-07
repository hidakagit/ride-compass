from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from app.domain.strict_model import StrictModel


class ElevationAttribute(StrictModel):
    """Edgeへ紐付ける標高属性。Edge本体（domain/graph.py）とは独立して保持する。

    average_gradeは符号付き（登り=正、下り=負）で、値が取れなかった区間はNone。
    獲得・喪失標高は揃って入る（表の制約`edge_materials_elevation_all_or_none`が区間の標高の4列を揃える）。
    """

    edge_id: str
    elevation_gain_m: float
    elevation_loss_m: float
    average_grade: float | None

    def reversed_as(self, reverse_edge_id: str) -> "ElevationAttribute":
        """同じ地形を逆方向に走った区間（`reverse_edge_id`）の値。標高は進行方向に依存しないため
        代数的に厳密に決まる: 獲得標高↔喪失標高の入れ替え、平均勾配の符号反転。
        """
        return ElevationAttribute(
            edge_id=reverse_edge_id,
            elevation_gain_m=self.elevation_loss_m,
            elevation_loss_m=self.elevation_gain_m,
            average_grade=-self.average_grade if self.average_grade is not None else None,
        )


# 舗装された公道としてありうる平均勾配の上限（%）。世界でも最急の公道が35%前後のため、
# これを超える値は道の起伏ではなくDEMの読み違い（両端が路面でない地物を指した等）である。
# 超えた区間は値を持たせず「データなし」にする——0次ハードフィルタは値の無い区間を
# 除外しない（`domain/hard_filters.py`）ので、誤った値で黙って経路から外すより安全側になる。
MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT = 40.0
#: 平均勾配（%）を保存・配信する桁。
AVERAGE_GRADE_DECIMALS = 2


@dataclass(frozen=True, slots=True)
class CategoricalColumn:
    """分類の材料1列を、区間ごとの語彙への番号（`codes`）と語彙（`vocab`）で持つ。番号0は値なしで、
    `vocab[0]`は必ずNone。

    区間ごとに値の文字列を持たない。値から数を引く（軸の対応表・転がり抵抗）のは語彙の大きさの表を
    作って番号で引くだけになり、区間ごとにPythonの辞書を引かずに済む。
    """

    codes: np.ndarray  # 整数（道路網の置き場はint16）
    vocab: tuple[str | None, ...]

    @classmethod
    def encode(cls, values: Iterable[str | None]) -> "CategoricalColumn":
        """値の並び（値なしはNone）を、現れた順に番号を振った列にする。"""
        code_of: dict[str | None, int] = {None: 0}
        codes = np.fromiter((code_of.setdefault(value, len(code_of)) for value in values), dtype=np.int16)
        return cls(codes, tuple(code_of))

    def __len__(self) -> int:
        return len(self.codes)

    def take(self, rows: np.ndarray) -> "CategoricalColumn":
        return CategoricalColumn(self.codes[rows], self.vocab)

    def value_at(self, row: int) -> str | None:
        return self.vocab[int(self.codes[row])]

    def lookup(self, table: Mapping[Any, float]) -> np.ndarray:
        """区間ごとに、値を`table`で引いた数（float64）。値なしと`table`に無い値はNaN。"""
        per_code = np.array([np.nan if value is None else table.get(value, np.nan) for value in self.vocab])
        return per_code[self.codes]

    def equals(self, value: object) -> np.ndarray:
        """区間ごとに、値が`value`と一致するか。値なしはどの`value`にも一致しない。"""
        matching = [code for code, known in enumerate(self.vocab) if known is not None and known == value]
        return np.isin(self.codes, matching)


# 材料1列の配列の形。分類の材料は`CategoricalColumn`、それ以外は数値・真偽のnumpy配列。
MaterialColumn = np.ndarray | CategoricalColumn


@dataclass(frozen=True, slots=True)
class EdgeMaterialArrays:
    """区間の材料を、**数値（真偽を含む）は1つの2次元配列**で保持する表現。

    値はDBが導出したものをそのまま受ける（`MaterialSpec.value_sql`）。
    区間ごとのPythonオブジェクトを経由しない。

    材料ごとに別々の配列を持たず、`StaticEdgeScoreMatrix`と同じ「値の行列＋idの並び」の形に
    する。材料が増えてもフィールドは増えず、列の追加は`*_ids`が1つ伸びるだけになる。
    数値と分類の2つに分かれるのは、カテゴリを数値の行列へ混ぜられないため（真偽の材料は数値の行列に
    1.0/0.0/NaNで載る。分け方は`material_catalog.material_array_columns`が唯一の判定）。
    カテゴリは列ごとに語彙が違うため、行列ではなく列ごとの`CategoricalColumn`で持つ。

    0次ハードフィルタの生フラグを同じ1回のクエリで求めてここへ持たせるのは、別に引くと
    区間の束ごとにもう1往復増えるため。

    標高の列は**材料ではない表示用の値**で、経路が確定したあとの区間について
    `domain/road_network.py: elevation_attribute`が`ElevationAttribute`を組み立てる。勾配そのものは材料
    `gradient_percent`にあるため、ここでは重複して持たない。
    """

    numeric_ids: tuple[str, ...]
    numeric_values: np.ndarray  # shape=(n, len(numeric_ids)), float64, NaN=欠損
    categorical_ids: tuple[str, ...]
    categorical_columns: tuple[CategoricalColumn, ...]  # categorical_idsと同じ並び
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
    elevation_gain_m: np.ndarray  # dtype=float64, NaN=欠損
    elevation_loss_m: np.ndarray

    def __len__(self) -> int:
        return len(self.distance_m)

    def columns(self) -> dict[str, MaterialColumn]:
        """材料id→その列。行列の列はビューのためコピーしない。"""
        return {
            **{m: self.numeric_values[:, i] for i, m in enumerate(self.numeric_ids)},
            **dict(zip(self.categorical_ids, self.categorical_columns, strict=True)),
        }

    def hard_filter_columns(self) -> dict[str, np.ndarray]:
        """0次フィルタ名→該当フラグ。行列の列はビューのためコピーしない。"""
        return {name: self.hard_filter_flags[:, i] for i, name in enumerate(self.hard_filter_ids)}


def elevation_values_sql(vertices: str) -> str:
    """区間の頂点列から、標高と勾配の値を出すSQL。

    `vertices`は`(osm_way_id, segment_index, ord, lon, lat, elev, on_structure)`を返す関係。
    `elev`がNULLの頂点は評価から外す。**外した後に隣り合う2点でも、元の点列では間に欠損を
    挟んでいることがある**——そのまま隣接扱いすると、欠損区間の起伏が均された差として
    混入する。距離（両端の座標は常に既知）と、獲得/消失（欠損を挟むと信頼できない）を
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
           coalesce(sum(greatest(-diff, 0)) FILTER (WHERE adjacent), 0) AS loss
    FROM pairs GROUP BY osm_way_id, segment_index),
raw AS (
    SELECT e.osm_way_id, e.segment_index, e.on_structure, e.start_e, e.end_e,
           a.gain, a.loss,
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
       round(avg_g::numeric, {AVERAGE_GRADE_DECIMALS}) AS average_grade
FROM raw
"""
