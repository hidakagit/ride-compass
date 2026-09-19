from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping

import numpy as np

from app.domain.geo import haversine_distance_km
from app.domain.graph import RoadGraph, RoadGraphLike
from app.domain.material_sql import MATERIAL_ID_GRADIENT_PERCENT
from app.domain.route import Coordinates
from app.domain.strict_model import StrictModel


# 材料へ数値を届けるための基本型。`edge_id → {キー: 値}`という1つの形へ揃え、
# 材料の種類が増えてもMaterialExtractionContextのフィールドを増やさない
# （`way_tags`が「文字列の束」1フィールドから任意個の材料を生やしているのと同じ形を、
# 数値の束にも用意する。docs/modules/backend/evaluation-scoring.md「材料へ値を届ける」参照）。
EdgeKeyedMetrics = Mapping[str, Mapping[str, float]]

# 群（group）名。保存形式（JSONB1列／実カラム複数）が違っても、材料から見た形は同じ。
METRIC_GROUP_COUNTS = "counts"
METRIC_GROUP_LANDCOVER = "landcover"
# 停止要因POIの種別別カウント。キーは`domain/traffic.py: POI_COUNT_KINDS`が単一ソースで、
# 群の中身が増えてもこの定数は増えない。
METRIC_GROUP_POI = "poi"

# `METRIC_GROUP_COUNTS`のキー。`EdgeAttributeCounts`のカウント列に対応する。
METRIC_KEY_ACCIDENT = "accident"
METRIC_KEY_INTERSECTION = "intersection"

# `METRIC_GROUP_LANDCOVER`のキー。`way_landcover`の割合列の名前と同じにする
# （SQLの読み出し列をこの並びから導くため）。
METRIC_KEY_TREES_PERCENT = "trees_percent"
METRIC_KEY_BUILT_PERCENT = "built_percent"
METRIC_KEY_CROPS_PERCENT = "crops_percent"
METRIC_KEY_RANGELAND_PERCENT = "rangeland_percent"
METRIC_KEY_WATER_PERCENT = "water_percent"
METRIC_KEY_BARE_PERCENT = "bare_percent"
METRIC_KEY_FLOODED_VEG_PERCENT = "flooded_veg_percent"
METRIC_KEY_SNOW_ICE_PERCENT = "snow_ice_percent"

# 評価パイプラインへ配線する土地被覆のクラス。**ここへ1つ足せば、Edge束・列指向
# テーブル・SQLの読み出し・タイルの焼き込み列・カバレッジ台帳が揃って増える**
# （下流はこの並びから導き、クラス名を個別に並べない）。
# `way_landcover`の割合列と1対1にする——どのクラスを材料にするかを人が選ぶ形にすると、
# 「なぜこのクラスだけ無いのか」を後から何度も判断し直すことになる。
WIRED_LANDCOVER_KEYS: tuple[str, ...] = (
    METRIC_KEY_TREES_PERCENT,
    METRIC_KEY_BUILT_PERCENT,
    METRIC_KEY_CROPS_PERCENT,
    METRIC_KEY_RANGELAND_PERCENT,
    METRIC_KEY_WATER_PERCENT,
    METRIC_KEY_BARE_PERCENT,
    METRIC_KEY_FLOODED_VEG_PERCENT,
    METRIC_KEY_SNOW_ICE_PERCENT,
)


class ElevationAttribute(StrictModel):
    """Edgeへ紐付ける標高属性（仕様書15章）。Edge本体（domain/graph.py）とは独立して保持する。

    average_grade/max_grade/min_gradeは符号付き（登り=正、下り=負）。
    有効な標高が2点未満の場合は全フィールドNoneのまま返す（Road Graph移行前のルート単位評価と同じ
    「取得失敗は握りつぶしてnull」方針、docs/architecture.md「標高計算のアルゴリズムと
    既知の制約」参照）。
    """

    edge_id: str
    start_elevation_m: float | None = None
    end_elevation_m: float | None = None
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    average_grade: float | None = None
    max_grade: float | None = None
    min_grade: float | None = None
    data_source: str
    data_version: str | None = None
    calculated_at: str


class EdgeAttributeCounts(StrictModel):
    """Edge単位の事前集計カウント（`edge_attribute_counts`）。事故密度・停止密度・
    交差点密度の評価材料（domain/difficulty.py参照）で、事前計算済みの値をそのまま
    読むことで探索フェーズのDBアクセス（PostGIS空間結合）を避ける。

    accident_countはdouble precision（死亡事故の重み付けSUM、domain/accident.py:
    ACCIDENT_FATAL_WEIGHT参照）。bicycle_only=trueで集計済みの値のみ保持する
    （road_graph_models.py: EdgeAttributeCountsRowのdocstring参照）。
    """

    accident_count: float
    intersection_count: int
    # 停止要因POIの種別別カウント（`domain/traffic.py: POI_COUNT_KINDS`がキーの単一ソース）。
    # **Noneは「未集計」**で、種別別の材料はすべて欠損（軸は算出不能）になる。空辞書は
    # 「集計済みで0件」で、材料は0になる。この2つを取り違えると、集計前のDBで全区間が
    # 「停止要因ゼロ＝最も易しい」と評価され、ルート選択が静かに歪む。
    poi_counts: dict[str, int] | None = None


class WayAttributeCounts(StrictModel):
    """区間インスペクタ用のway単位集計（`way_attribute_counts`テーブル）。

    `EdgeAttributeCounts`と同じカウントに、per_km換算へ使う`length_m`を加えたもの。
    """

    length_m: float
    accident_count: float
    intersection_count: int
    # 停止要因POIの種別別カウント（Edge単位版と同じ、Noneは未集計）。
    poi_counts: dict[str, int] | None = None












@dataclass
class SearchMaterials:
    """探索フェーズ（`RoadGraphEngine.prepare`）が必要とするRoad Graphのトポロジ＋
    材料一式。`GraphService.get_search_materials_for_bbox`の戻り値であり、
    `infrastructure/graph_material_cache.py`のタイル単位キャッシュ値（z12タイル1枚ぶんの
    同形の内容）としても使う共通の型。"""

    # RoadGraph（Pydantic、split再構築を伴うuncached経路）またはLeanRoadGraph
    # （dataclass、タイルキャッシュ経路）のいずれかが入る。
    graph: RoadGraphLike
    materials: "EdgeMaterialArrays"




def _none_if_nan(value) -> float | None:
    return None if value is None or np.isnan(value) else float(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# 舗装された公道としてありうる平均勾配の上限（%）。世界でも最急の公道が35%前後のため、
# これを超える値は道の起伏ではなくDEMの読み違い（両端が路面でない地物を指した等）である。
# 超えた区間は値を持たせず「データなし」にする——0次ハードフィルタは値の無い区間を
# 除外しない（`domain/hard_filters.py`）ので、誤った値で黙って経路から外すより安全側になる。
MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT = 40.0


def compute_elevation_attribute(
    edge_id: str,
    points: list[Coordinates],
    elevations: list[float | None],
    data_source: str,
    dem_reflects_road_surface: bool = True,
) -> ElevationAttribute:
    """Edgeの形状点列とそれぞれの標高値からElevationAttributeを算出する。

    標高が取得できなかった点（None）は除外して評価する。除外後に隣り合う2点（`valid`上で
    連続）でも、元の点列では間に欠損点を挟んでいる場合がある。そのまま隣接扱いすると、
    欠損区間内の実際の起伏（急な上り下り）が均された平均勾配として計算に混入する。
    distance_m（座標は両点とも既知のため常に正確）とgain/loss/grade（欠損を挟むと
    信頼できない）を分離し、元の点列でも真に隣接していたペアのみgain/loss/gradeへ
    寄与させる。

    `dem_reflects_road_surface=False`（橋・高架・トンネル）では`average_grade`を持たせない。
    DEMが返すのは地表面の標高で、桁や坑道の高さではない——谷を渡る橋なら谷底の起伏を、
    山を抜けるトンネルなら山の起伏を、そのまま道の勾配として受け取ってしまう。これは
    測り間違いではなく別のものを測っており、値を丸める・上限で切るのでは直らない。
    標高そのもの（start/end_elevation_m・gain/loss）は残す。
    """
    valid = [(i, p, e) for i, (p, e) in enumerate(zip(points, elevations)) if e is not None]
    if len(valid) < 2:
        return ElevationAttribute(edge_id=edge_id, data_source=data_source, calculated_at=_now_iso())

    gain = 0.0
    loss = 0.0
    max_grade: float | None = None
    min_grade: float | None = None
    total_distance_m = 0.0

    for (idx1, p1, e1), (idx2, p2, e2) in zip(valid, valid[1:]):
        distance_m = haversine_distance_km(p1, p2) * 1000
        total_distance_m += distance_m

        if idx2 - idx1 != 1:
            continue  # 間に欠損点を挟むペアはgain/loss/gradeへ寄与させない

        diff = e2 - e1
        if diff > 0:
            gain += diff
        else:
            loss += -diff

        if distance_m > 0:
            grade = diff / distance_m * 100
            max_grade = grade if max_grade is None else max(max_grade, grade)
            min_grade = grade if min_grade is None else min(min_grade, grade)

    start_elevation = valid[0][2]
    end_elevation = valid[-1][2]
    average_grade = (end_elevation - start_elevation) / total_distance_m * 100 if total_distance_m > 0 else None
    if average_grade is not None and abs(average_grade) > MAX_PLAUSIBLE_AVERAGE_GRADE_PERCENT:
        average_grade = None
    if not dem_reflects_road_surface:
        average_grade = None

    return ElevationAttribute(
        edge_id=edge_id,
        start_elevation_m=round(start_elevation, 1),
        end_elevation_m=round(end_elevation, 1),
        elevation_gain_m=round(gain, 1),
        elevation_loss_m=round(loss, 1),
        average_grade=round(average_grade, 2) if average_grade is not None else None,
        max_grade=round(max_grade, 2) if max_grade is not None else None,
        min_grade=round(min_grade, 2) if min_grade is not None else None,
        data_source=data_source,
        calculated_at=_now_iso(),
    )


def surface_by_edge_id(graph: RoadGraph, surface_by_way_id: dict[int, str | None]) -> dict[str, str | None]:
    """RoadGraphの各Edgeに、同じOSM取得結果由来のsurfaceタグ（osm_way_id単位）を紐付ける。

    1つのOSM Wayが複数のDirected Edgeに分割されている場合（仕様書9章）、
    それらは同じsurfaceタグ値を共有する（Way単位のタグのため、Way内で路面が変わっても
    OSM上は区別されない。より細かい粒度が必要になった場合は将来の課題とする）。
    """
    return {
        edge_id: surface_by_way_id.get(edge.osm_way_id) if edge.osm_way_id is not None else None
        for edge_id, edge in graph.edges.items()
    }


@dataclass(frozen=True, slots=True)
class EdgeMaterialArrays:
    """タイル1枚ぶんの材料を、**dtypeごとに1つの2次元配列**で保持する表現。

    値はDBが導出したものをそのまま受ける（`MaterialSpec.value_sql`）。
    区間ごとのPythonオブジェクトを経由しないため、構築も復元もEdge数に比例しない。

    材料ごとに別々の配列を持たず、`StaticEdgeScoreMatrix`と同じ「値の行列＋idの並び」の形に
    する。材料が増えてもフィールドは増えず、列の追加は`*_ids`が1つ伸びるだけになる。
    dtypeで3つに分かれるのは、真偽とカテゴリを数値の行列へ混ぜられないため（分け方は
    `MaterialSpec.dtype`と`bool_default`が決める。`material_array_group`が唯一の判定）。

    `*_ids`は列の並びで、**ディスクから復元したときに現在の材料集合と突き合わせるために
    ある**。材料を1つ増やしてもdataclassのフィールドは変わらず
    `cache_identity.shape_digest`が動かないため、鍵だけでは古い表を弾けない
    （`tile_score_matrix_cache`が可変長の列に対して行っているのと同じ、読み出し時の検証）。

    `no_bicycle`は材料ではなく0次ハードフィルタの生フラグ。同じ1回のクエリで求まるため
    ここへ持たせる（別に引くとタイルごとにもう1往復増える）。

    標高の列は**材料ではない表示用の値**（`data_source`・`calculated_at`等）。経路が確定した
    あとの数百区間について`elevation_attribute()`が`ElevationAttribute`を組み立てる
    （`road_graph_engine.py: _fetch_elevation_attributes`）。勾配そのものは材料
    `gradient_percent`にあるため、ここでは重複して持たない。
    """

    edge_ids: list[str]
    numeric_ids: tuple[str, ...]
    numeric_values: np.ndarray  # shape=(n, len(numeric_ids)), float64, NaN=欠損
    boolean_ids: tuple[str, ...]
    boolean_values: np.ndarray  # shape=(n, len(boolean_ids)), bool
    categorical_ids: tuple[str, ...]
    categorical_values: np.ndarray  # shape=(n, len(categorical_ids)), object
    # 0次ハードフィルタの生フラグ。フィルタ名がそのまま列で、`domain/hard_filters.py:
    # HARD_FILTER_VALUE_SQL`から生成する。**フィルタごとに専用のフィールドを作らない**
    # （材料と同じ「値の行列＋idの並び」、設計原則 構造仕様8）。
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
    elevation_data_source: list[str | None]
    elevation_data_version: list[str | None]
    elevation_calculated_at: list[str | None]
    _row_index: dict[str, int] | None = field(default=None)

    def __post_init__(self) -> None:
        if self._row_index is None:
            object.__setattr__(self, "_row_index", {edge_id: i for i, edge_id in enumerate(self.edge_ids)})

    def __len__(self) -> int:
        return len(self.edge_ids)

    @property
    def material_ids(self) -> tuple[str, ...]:
        """持っている材料の全id（復元時に現在の材料集合と突き合わせる用）。"""
        return (*self.numeric_ids, *self.boolean_ids, *self.categorical_ids)

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

    def column(self, material_id: str) -> np.ndarray:
        for ids, matrix in (
            (self.numeric_ids, self.numeric_values),
            (self.boolean_ids, self.boolean_values),
            (self.categorical_ids, self.categorical_values),
        ):
            if material_id in ids:
                return matrix[:, ids.index(material_id)]
        raise KeyError(material_id)

    def elevation_attribute(self, edge_id: str) -> ElevationAttribute | None:
        """行が無い、または標高が未計算ならNone。"""
        i = self._row_index.get(edge_id)
        if i is None or not self.elevation_present[i]:
            return None
        return ElevationAttribute(
            edge_id=edge_id,
            start_elevation_m=_none_if_nan(self.elevation_start_m[i]),
            end_elevation_m=_none_if_nan(self.elevation_end_m[i]),
            elevation_gain_m=_none_if_nan(self.elevation_gain_m[i]),
            elevation_loss_m=_none_if_nan(self.elevation_loss_m[i]),
            average_grade=_none_if_nan(self.column(MATERIAL_ID_GRADIENT_PERCENT)[i]),
            max_grade=_none_if_nan(self.elevation_max_grade[i]),
            min_grade=_none_if_nan(self.elevation_min_grade[i]),
            data_source=self.elevation_data_source[i],
            data_version=self.elevation_data_version[i],
            calculated_at=self.elevation_calculated_at[i],
        )
