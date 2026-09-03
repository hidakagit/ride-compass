import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator, Mapping

import numpy as np
from pydantic import BaseModel

from app.domain.geo import haversine_distance_km
from app.domain.graph import RoadGraph, RoadGraphLike
from app.domain.route import Coordinates


class ElevationAttribute(BaseModel):
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


class EdgeAttributeCounts(BaseModel):
    """Edge単位の事前集計カウント（改善計画T144: edge_attribute_counts、T218で読み取り経路に
    配線）。事故密度・停止密度・交差点密度の評価材料（domain/difficulty.py参照）で、
    以前はリクエストの都度PostGIS空間結合（ST_DWithin）で算出していたが、事前計算済みの
    値をそのまま読むことで探索フェーズのDBアクセスを削減する。

    accident_countはdouble precision（死亡事故の重み付けSUM、domain/accident.py:
    ACCIDENT_FATAL_WEIGHT参照）。bicycle_only=trueで集計済みの値のみ保持する
    （road_graph_models.py: EdgeAttributeCountsRowのdocstring参照）。
    """

    accident_count: float
    stop_count: int
    intersection_count: int


class WayAttributeCounts(BaseModel):
    """区間インスペクタ用のway単位集計（改善計画T146・T543、`way_attribute_counts`テーブル）。

    `EdgeAttributeCounts`と同じ3カウントに、per_km換算へ使う`length_m`を加えたもの。
    """

    length_m: float
    accident_count: float
    stop_count: int
    intersection_count: int


@dataclass(frozen=True, slots=True)
class EdgeMaterialBundle:
    """Edge 1本ぶんの材料（surface・way_tags・件数・標高・指定路線）を1オブジェクトへ
    束ねたもの（改善計画T533派生）。

    `get_edge_materials_batch`は元々1回のJOINクエリで全材料を1行取得していた
    （改善計画T248）が、戻り値だけは`surface_attributes`/`edge_attribute_counts`/
    `way_tags`/`elevation_attributes`の4つの辞書へ再分割していた。当時の探索コストの
    ホットパス（旧`RoadGraphEngine._build_edge_cost_fn`のcost_fn、訪れたEdgeごとに
    最大24回＝8方位×3レグ呼ばれていた。改善計画T536でタイル単位の静的スコア行列＋
    ベクトル計算方式へ置き換え済み）はその4辞書＋designated_edge_idsへ個別に
    `.get(edge_id)`していたため、実データ計測（渋谷相当bbox・24.7万Edge）で
    「統合済み1辞書への1回アクセス」が「4辞書への個別アクセス」の3.5倍速いことを
    確認した上で、Edge単位でこの1オブジェクトへ統合した
    （`@dataclass(frozen=True, slots=True)`はLeanEdge等と同じ実績パターン、素の辞書
    比で受け渡しが速い）。統合形式自体は`build_static_edge_score_matrix`（T536、
    タイル読込時1回だけの分解）・`_build_segment_details`（区間表示）が引き続き使う。

    `way_tags`は該当Wayにタグが無い場合も`{}`（空辞書、Noneにしない）——
    元の`way_tags`辞書がLEFT JOINで「key自体は必ず存在、値は`row.tags or {}`」
    だった仕様をそのまま踏襲する（`domain/evaluation.py: is_edge_allowed`等が
    `way_tags is not None`で「タグ取得済みか」を判定するため、空タグとNone
    [未取得]の区別を保つ必要がある）。`attribute_counts`/`elevation_attribute`は
    対象テーブルへの行が無ければNone（NOT NULL列を「行の有無」の判定に使っていた
    元の仕様を保つ）。
    """

    surface: str | None
    way_tags: dict[str, str]
    attribute_counts: EdgeAttributeCounts | None
    elevation_attribute: ElevationAttribute | None
    is_designated: bool


@dataclass(frozen=True, slots=True)
class LegacyEdgeMaterialDicts:
    """`EdgeMaterialTable.to_legacy_dicts()`の戻り値（改善計画T546）。

    `_evaluate_axes_bulk`（`build_static_edge_score_matrix`が呼ぶ抽出フェーズ）が要求する
    個別辞書引数の形そのもの。タイル読込時に1回だけ発生する変換であり、探索のホットパスには
    乗らない（`domain/evaluation.py: build_static_edge_score_matrix`のdocstring参照）。
    """

    elevation_attributes: dict[str, ElevationAttribute]
    surface_attributes: dict[str, str | None]
    way_tags: dict[str, dict[str, str]]
    stop_counts: dict[str, int]
    intersection_counts: dict[str, int]
    accident_counts: dict[str, float]
    designated_edge_ids: set[str]


def _none_if_nan(value: float) -> float | None:
    return None if math.isnan(value) else value


@dataclass(frozen=True, slots=True)
class EdgeMaterialTable:
    """タイル1枚ぶんの`EdgeMaterialBundle`群を列指向（numpy配列＋リスト）で保持する
    表現（改善計画T546、T538の再検討案C1）。

    背景: T538でタイル材料キャッシュをディスク永続化したが、本番実測で「デプロイ直後の
    復元」が20.7秒（完了条件5秒未満に未達）だった。cProfileで、ボトルネックはディスク
    I/Oでもpickle自体でもなく「Edge1本ごとに`EdgeMaterialBundle`
    （Pydantic`ElevationAttribute`/`EdgeAttributeCounts`＋frozen dataclass混在）を
    Pythonオブジェクトとして再構築するコスト」（Edge1本あたり約36µs、Python 3.12の
    `dataclasses._dataclass_setstate`・Pydantic`BaseModel.__setstate__`が支配的）と
    判明した（詳細はdocs/tasks/T546.md参照）。本クラスは、タイル単位でキャッシュへ
    入れる材料をEdgeごとのオブジェクトの辞書ではなく列（numpy配列・リスト）として持つ
    ことで、pickle復元をEdge数に依存しない列単位の操作へ変える（1タイルあたりの
    復元コストが約36µs×Edge数から約20ms＋オブジェクト再構築約118ms/タイルへ短縮する
    見込み、T546.md参照）。

    **正準定義は引き続き`EdgeMaterialBundle`1箇所**（設計原則4）。本クラスは軸定義
    （`AXIS_DEFINITIONS`）も材料カタログ（`MATERIAL_CATALOG`）も一切知らない、
    `EdgeMaterialBundle`と1対1の列指向ビューに過ぎない（設計原則3・8には触れない）。

    列の設計（`from_bundles`/`get`が対称に扱う）:
    - `surface`: `str | None`をそのまま格納するobject配列（Noneは値として区別、
      「行の有無」の概念は無い＝`EdgeMaterialBundle.surface`自体が常にNoneを許容する
      ため）。
    - `way_tags`: `dict[str, str]`のリスト（`EdgeMaterialBundle.way_tags`は該当Wayに
      タグが無くても`{}`を持つため、Noneにはならない。`{}`とNone[bundle自体が無い]の
      区別は、後者を`get()`がNoneを返すことで表現する——本テーブルの行自体が存在しない
      edge_idは`_row_index`に含めない）。
    - 標高7列（`elevation_start_m`等）: `float64`配列、欠損値は`NaN`（元の
      `ElevationAttribute`のフィールドはそもそも実データでNaNを取らないため、NaNを
      「その1フィールドがNone」の印として安全に使える）。加えて`elevation_present`
      （bool配列）が「`ElevationAttribute`オブジェクト自体が無い」（＝bundleの
      `elevation_attribute is None`）を独立して表す——標高7列すべてがNaNでも
      `elevation_present=True`（=len(valid)<2でオブジェクトは存在しフィールドのみ
      Noneの場合）と、`elevation_present=False`（=標高が未計算でオブジェクトが
      存在しない場合）を区別する。data_source/data_version/calculated_atは文字列列
      （Noneを含みうる`list`）で個別に保持する。
    - 件数3列（`accident_count`等）＋`counts_present`（bool配列）: 標高と同じ設計。
      `EdgeAttributeCounts`のフィールド自体は必須（Optionalではない）ため、
      `counts_present`だけで「行の有無」を判定できる。
    - `is_designated`: bool配列（常に値を持つ、Optionalではない）。

    `get(edge_id)`は`_row_index`（edge_id→行index）を1回引いた後、対応する列から
    `EdgeMaterialBundle`をその場で組み立てて返す（探索フェーズが経路上のEdge[数百本]
    だけを引く用途、`road_graph_engine.py: context.materials.get(edge.edge_id)`）。
    `to_legacy_dicts()`は全行を一括で`_evaluate_axes_bulk`向けの個別辞書へ変換する
    （`build_static_edge_score_matrix`がタイル読込時に1回だけ呼ぶ、ホットパスではない）。
    """

    edge_ids: list[str]
    surface: np.ndarray  # dtype=object, str | None
    way_tags: list[dict[str, str]]
    elevation_present: np.ndarray  # dtype=bool
    elevation_start_m: np.ndarray  # dtype=float64, NaN=欠損
    elevation_end_m: np.ndarray
    elevation_gain_m: np.ndarray
    elevation_loss_m: np.ndarray
    elevation_average_grade: np.ndarray
    elevation_max_grade: np.ndarray
    elevation_min_grade: np.ndarray
    elevation_data_source: list[str | None]
    elevation_data_version: list[str | None]
    elevation_calculated_at: list[str | None]
    counts_present: np.ndarray  # dtype=bool
    accident_count: np.ndarray  # dtype=float64
    stop_count: np.ndarray  # dtype=float64（int相当、NaN=欠損）
    intersection_count: np.ndarray  # dtype=float64
    is_designated: np.ndarray  # dtype=bool
    # Noneは「未指定」を表し、__post_init__がedge_ids全件を行indexとして自動算出する
    # （直接構築するテスト向けの便宜）。`from_bundles`はbundleが無いedge_idの行を
    # 意図的に含めない辞書を明示的に渡すため、空dict({})と「未指定」を区別する必要がある
    # （空dictをそのまま「未指定」扱いすると、全Edgeがbundleを持たないタイルという
    # 稀なケースでedge_ids全件を誤って行indexへ復元してしまう）。
    _row_index: dict[str, int] | None = field(default=None)

    def __post_init__(self) -> None:
        if self._row_index is None:
            object.__setattr__(self, "_row_index", {edge_id: i for i, edge_id in enumerate(self.edge_ids)})

    @staticmethod
    def from_bundles(edge_ids: list[str], materials: Mapping[str, "EdgeMaterialBundle"]) -> "EdgeMaterialTable":
        """`edge_ids`の行順で`materials`（edge_id→`EdgeMaterialBundle`）を列指向へ変換する。

        `materials`に対応するbundleが無いedge_id（現行の呼び出し元では発生しない——
        `AttributeRepository.get_edge_materials_batch`は`edge_ids`に含まれる全Edgeぶん
        必ずbundleを持つ、`EdgeMaterialBundle`のdocstring参照）は行を持たず、`get()`が
        Noneを返す（元の`materials.get(edge_id)`がNoneを返すのと同じ意味論）。
        """
        n = len(edge_ids)
        surface = np.empty(n, dtype=object)
        way_tags: list[dict[str, str]] = [{} for _ in range(n)]
        elevation_present = np.zeros(n, dtype=bool)
        elevation_start_m = np.full(n, np.nan)
        elevation_end_m = np.full(n, np.nan)
        elevation_gain_m = np.full(n, np.nan)
        elevation_loss_m = np.full(n, np.nan)
        elevation_average_grade = np.full(n, np.nan)
        elevation_max_grade = np.full(n, np.nan)
        elevation_min_grade = np.full(n, np.nan)
        elevation_data_source: list[str | None] = [None] * n
        elevation_data_version: list[str | None] = [None] * n
        elevation_calculated_at: list[str | None] = [None] * n
        counts_present = np.zeros(n, dtype=bool)
        accident_count = np.full(n, np.nan)
        stop_count = np.full(n, np.nan)
        intersection_count = np.full(n, np.nan)
        is_designated = np.zeros(n, dtype=bool)

        row_index: dict[str, int] = {}
        for i, edge_id in enumerate(edge_ids):
            bundle = materials.get(edge_id)
            if bundle is None:
                continue  # bundle自体が無いedge_id: 行を持たせず、get()がNoneを返すようにする
            row_index[edge_id] = i

            surface[i] = bundle.surface
            way_tags[i] = bundle.way_tags
            is_designated[i] = bundle.is_designated

            counts = bundle.attribute_counts
            if counts is not None:
                counts_present[i] = True
                accident_count[i] = counts.accident_count
                stop_count[i] = counts.stop_count
                intersection_count[i] = counts.intersection_count

            elevation = bundle.elevation_attribute
            if elevation is not None:
                elevation_present[i] = True
                if elevation.start_elevation_m is not None:
                    elevation_start_m[i] = elevation.start_elevation_m
                if elevation.end_elevation_m is not None:
                    elevation_end_m[i] = elevation.end_elevation_m
                if elevation.elevation_gain_m is not None:
                    elevation_gain_m[i] = elevation.elevation_gain_m
                if elevation.elevation_loss_m is not None:
                    elevation_loss_m[i] = elevation.elevation_loss_m
                if elevation.average_grade is not None:
                    elevation_average_grade[i] = elevation.average_grade
                if elevation.max_grade is not None:
                    elevation_max_grade[i] = elevation.max_grade
                if elevation.min_grade is not None:
                    elevation_min_grade[i] = elevation.min_grade
                elevation_data_source[i] = elevation.data_source
                elevation_data_version[i] = elevation.data_version
                elevation_calculated_at[i] = elevation.calculated_at

        return EdgeMaterialTable(
            edge_ids=edge_ids,
            surface=surface,
            way_tags=way_tags,
            elevation_present=elevation_present,
            elevation_start_m=elevation_start_m,
            elevation_end_m=elevation_end_m,
            elevation_gain_m=elevation_gain_m,
            elevation_loss_m=elevation_loss_m,
            elevation_average_grade=elevation_average_grade,
            elevation_max_grade=elevation_max_grade,
            elevation_min_grade=elevation_min_grade,
            elevation_data_source=elevation_data_source,
            elevation_data_version=elevation_data_version,
            elevation_calculated_at=elevation_calculated_at,
            counts_present=counts_present,
            accident_count=accident_count,
            stop_count=stop_count,
            intersection_count=intersection_count,
            is_designated=is_designated,
            _row_index=row_index,
        )

    def _reconstruct_attribute_counts(self, i: int) -> EdgeAttributeCounts | None:
        if not self.counts_present[i]:
            return None
        return EdgeAttributeCounts(
            accident_count=float(self.accident_count[i]),
            stop_count=int(self.stop_count[i]),
            intersection_count=int(self.intersection_count[i]),
        )

    def _reconstruct_elevation_attribute(self, i: int, edge_id: str) -> ElevationAttribute | None:
        if not self.elevation_present[i]:
            return None
        return ElevationAttribute(
            edge_id=edge_id,
            start_elevation_m=_none_if_nan(self.elevation_start_m[i]),
            end_elevation_m=_none_if_nan(self.elevation_end_m[i]),
            elevation_gain_m=_none_if_nan(self.elevation_gain_m[i]),
            elevation_loss_m=_none_if_nan(self.elevation_loss_m[i]),
            average_grade=_none_if_nan(self.elevation_average_grade[i]),
            max_grade=_none_if_nan(self.elevation_max_grade[i]),
            min_grade=_none_if_nan(self.elevation_min_grade[i]),
            data_source=self.elevation_data_source[i],
            data_version=self.elevation_data_version[i],
            calculated_at=self.elevation_calculated_at[i],
        )

    def get(self, edge_id: str) -> EdgeMaterialBundle | None:
        """`dict.get`と同じ意味論。行が無ければNone（元の`materials.get(edge_id)`が
        Noneを返すのと同じ、`EdgeMaterialBundle.way_tags`自体の`{}`/Noneの区別とは
        独立した「bundleそのものの有無」を表す）。"""
        i = self._row_index.get(edge_id)
        if i is None:
            return None
        return EdgeMaterialBundle(
            surface=self.surface[i],
            way_tags=self.way_tags[i],
            attribute_counts=self._reconstruct_attribute_counts(i),
            elevation_attribute=self._reconstruct_elevation_attribute(i, edge_id),
            is_designated=bool(self.is_designated[i]),
        )

    def __getitem__(self, edge_id: str) -> EdgeMaterialBundle:
        bundle = self.get(edge_id)
        if bundle is None:
            raise KeyError(edge_id)
        return bundle

    def values(self) -> Iterator[EdgeMaterialBundle]:
        for edge_id in self._row_index:
            bundle = self.get(edge_id)
            assert bundle is not None
            yield bundle

    def __len__(self) -> int:
        return len(self._row_index)

    def to_legacy_dicts(self) -> LegacyEdgeMaterialDicts:
        """`_evaluate_axes_bulk`が要求する個別辞書群へ全行を一括変換する
        （`build_static_edge_score_matrix`がタイル読込時に1回だけ呼ぶ）。"""
        elevation_attributes: dict[str, ElevationAttribute] = {}
        surface_attributes: dict[str, str | None] = {}
        way_tags: dict[str, dict[str, str]] = {}
        stop_counts: dict[str, int] = {}
        intersection_counts: dict[str, int] = {}
        accident_counts: dict[str, float] = {}
        designated_edge_ids: set[str] = set()

        for edge_id, i in self._row_index.items():
            surface_attributes[edge_id] = self.surface[i]
            way_tags[edge_id] = self.way_tags[i]
            if self.is_designated[i]:
                designated_edge_ids.add(edge_id)
            if self.counts_present[i]:
                stop_counts[edge_id] = int(self.stop_count[i])
                intersection_counts[edge_id] = int(self.intersection_count[i])
                accident_counts[edge_id] = float(self.accident_count[i])
            elevation = self._reconstruct_elevation_attribute(i, edge_id)
            if elevation is not None:
                elevation_attributes[edge_id] = elevation

        return LegacyEdgeMaterialDicts(
            elevation_attributes=elevation_attributes,
            surface_attributes=surface_attributes,
            way_tags=way_tags,
            stop_counts=stop_counts,
            intersection_counts=intersection_counts,
            accident_counts=accident_counts,
            designated_edge_ids=designated_edge_ids,
        )


@dataclass
class SearchMaterials:
    """探索フェーズ（`RoadGraphEngine.prepare`）が必要とするRoad Graphのトポロジ＋
    材料一式（改善計画T219、T12 Stage 1）。`GraphService.get_search_materials_for_bbox`の
    戻り値であり、`infrastructure/graph_material_cache.py`のタイル単位キャッシュ値
    （z12タイル1枚ぶんの同形の内容）としても使う共通の型（改善計画T228、旧`_TileMaterials`
    はフィールド完全一致の重複定義だったため統合済み）。"""

    # RoadGraph（Pydantic、split再構築を伴うuncached経路）またはLeanRoadGraph
    # （dataclass、タイルキャッシュ経路、改善計画T248）のいずれかが入る。
    graph: RoadGraphLike
    # 改善計画T546: `graph_material_cache`（ディスク永続化を経由する正規のタイルキャッシュ
    # 経路、`GraphService._get_or_build_tile_materials`）は`EdgeMaterialTable`（列指向、
    # pickle復元コストが低い）を持たせる。`_build_search_materials_uncached`
    # （split鮮度が古いbbox限定の再構築経路、タイルキャッシュへは書き込まれない
    # ——`GraphService.get_search_materials_for_bbox`のdocstring参照）はこの変換コストを
    # 払う理由が無いため、従来どおり`dict[str, EdgeMaterialBundle]`のまま返す。
    # いずれの型も`.get(edge_id)`で同じ意味論のEdgeMaterialBundle（またはNone）を返すため、
    # 消費側（`road_graph_engine.py`）はどちらの型が来ても区別なく扱える。
    materials: "dict[str, EdgeMaterialBundle] | EdgeMaterialTable"


@dataclass
class EdgeMaterialsBatch:
    """`SearchMaterials`から`graph`を除いた材料一式（改善計画T248・T533）。

    以前は`surface_attributes`/`edge_attribute_counts`/`way_tags`/
    `elevation_attributes`/`designated_edge_ids`をEdge集合が同じまま5回individually
    取得していたが、実測（dev DB、71,791 Edge）で現行5クエリ8.33秒→統合1クエリ
    （`AttributeRepository.get_edge_materials_batch`）1.30秒（6.4倍）を確認したため、
    1回のJOINクエリへ統合した。当初はこの戻り値を4つの辞書へ再分割していたが
    （クエリ統合時に直し忘れた技術的負債）、Edge単位で`EdgeMaterialBundle`へ
    統合した1辞書へ改めた（T533、`EdgeMaterialBundle`のdocstring参照）。"""

    materials: dict[str, EdgeMaterialBundle]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_elevation_attribute(
    edge_id: str,
    points: list[Coordinates],
    elevations: list[float | None],
    data_source: str,
) -> ElevationAttribute:
    """Edgeの形状点列とそれぞれの標高値からElevationAttributeを算出する。

    標高が取得できなかった点（None）は除外して評価する（Road Graph移行前のルート単位評価と同じ方針）。
    改善計画T463: 除外後に隣り合う2点（`valid`上で連続）でも、元の点列では間に欠損点を
    挟んでいる場合がある。そのまま隣接扱いすると、欠損区間内の実際の起伏（急な上り下り）が
    均された平均勾配として計算に混入する。distance_m（座標は両点とも既知のため常に正確）と
    gain/loss/grade（欠損を挟むと信頼できない）を分離し、元の点列でも真に隣接していた
    ペアのみgain/loss/gradeへ寄与させる。
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
