from dataclasses import dataclass
from datetime import datetime, timezone

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
    materials: dict[str, EdgeMaterialBundle]


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
