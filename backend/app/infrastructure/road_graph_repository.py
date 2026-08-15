"""Road Graph・Road AttributeのPostGIS永続化層。

責務ごとに4つのリポジトリへ分割している（改善計画T6。変更理由が異なる操作を
1クラスに同居させない）:
- `RawOsmRepository`: 生OSM層（osm_raw_ways/osm_raw_nodes）とタイル取得マーカー
  （road_graph_tiles）。データ取込・closure読み出しの都合で変わる
- `DerivedGraphRepository`: 派生グラフ（road_nodes/road_edges）と鮮度判定（split_at）。
  交差点分割アルゴリズムの都合で変わる
- `AttributeRepository`: Edge単位のRoad Attribute（elevation_attributes。surfaceは
  road_edges.osm_way_id経由でosm_raw_ways.surfaceをJOIN導出するため専用テーブルは持たない、
  改善計画T9）。属性の種類追加の都合で変わる
- `RoadSurfaceTileQuery`: 地域路面レイヤー表示用のMVT生成（読み取り専用）。
  地図表示の都合で変わる
`RoadGraphRepository`は4つを既存の公開APIのまま束ねるファサード（DI・テストの
安定した注入点）。新しいコードは用途に応じて個別リポジトリを直接使ってよい。

**トランザクション境界の規約（T6で確立）**: 本モジュールの書き込みメソッドは
一切commitしない。呼び出し側（サービス層）が操作のまとまりごとに
`RoadGraphRepository.commit()`を呼んで確定する。4リポジトリは同一AsyncSessionを
共有するため、どのリポジトリ経由の変更もまとめて確定される。
例: GraphServiceは「タイルの生データ保存＋取得済みマーク」を1コミット、
「分割結果の保存」を1コミットにする（以前は各メソッドが内部でcommitしており、
保存とマークの原子性が呼び出し順の暗黙規約に依存していた）。

node_id/edge_idはdomain/graph.pyでOSM IDから決定論的に導出されるため、同じ現実の
交差点・道路区間に対する保存は常に同じ主キーへのUPSERT（`Session.merge`）になる。

`get_graph_in_bbox`自体は「指定bboxと交差するEdgeを返す」単純な空間検索であり、
「そのbboxが過去に完全に取得済みかどうか」は判定しない。正確なキャッシュカバレッジ判定は
`RoadGraphTileRow`（タイル取得済みマーカー、is_tile_cached/mark_tile_cached）が担う。
呼び出し側（GraphService）は、対象bboxを覆う全タイルが取得済みであることを先に保証し、
かつ`is_split_up_to_date`で生データ（osm_raw_ways）が前回のsplit以降変わっていないことを
確認してから`get_graph_in_bbox`を呼ぶ（地域路面レイヤー/RegionServiceがXYZタイル境界を
単位に厳密なキャッシュ単位を実現しているのと同じ考え方。詳細はdocs/architecture.md参照）。
生データが変わっていた場合は`get_way_specs_with_closure`→`build_road_graph`→`save_graph`の
通常経路（closure再計算＋Edge全量再UPSERT）へフォールバックする。

`save_raw_ways`/`get_way_specs_with_closure`は、タイル境界依存の交差点分割不一致問題
（docs/architecture.md参照）への根本対応として追加した。生のOSM Way/Nodeデータ
（`osm_raw_ways`/`osm_raw_nodes`）は取得元タイルに依存しない安定した永続化層とし、
交差点分割（`build_road_graph`）はDB上の既知の生データ全体から都度計算する。
`save_graph`は`way_ids_to_replace`を指定すると、そのosm_way_id群の既存Edge行を
全削除してから新しい分割結果を挿入し直す（delete-then-reinsert）ことで、Wayの
分割結果が変わった場合に孤立した古いEdge行が残らないようにする。
"""

import asyncio
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone

import shapely
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString, Point
from sqlalchemy import BigInteger, Float, Text, any_, bindparam, cast, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.domain.attributes import ElevationAttribute
from app.domain.graph import DirectedEdge, Node, RoadGraph, WaySpec
from app.domain.region import BoundingBox
from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS, SURFACE_MATCH_MAX_DISTANCE_M
from app.domain.traffic import STOP_POI_MATCH_MAX_DISTANCE_M, TRAFFIC_STRESS_BASE_BY_HIGHWAY
from app.infrastructure.vector_tile import ROAD_SURFACE_LAYER_NAME, TILE_EXTENT
from app.infrastructure.road_graph_models import (
    Base,
    ElevationAttributeRow,
    OsmRawNodeRow,
    OsmRawWayRow,
    RoadEdgeRow,
    RoadGraphTileRow,
    RoadNodeRow,
)

CACHED_GRAPH_VERSION = "cached"

# バルクUPSERT1文あたりの行数。asyncpgのプリペアド文パラメータ上限（32767個）を
# 最も列数の多いテーブル（8列）でも十分下回るサイズにする。
_BULK_CHUNK_ROWS = 1000
# IN句・削除等でIDリストを分割するサイズ（1要素=1パラメータのため上限に余裕を持たせる）
_ID_CHUNK_SIZE = 10_000


def _chunked(items: list, size: int) -> Iterator[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


async def create_tables(engine: AsyncEngine) -> None:
    """新規DB向けの基本スキーマを作成する（PostGIS拡張の有効化＋ORMモデルからのcreate_all）。

    列追加・インデックス追加・データバックフィルといった一度きりのスキーマ変更は
    `migrations/`配下の番号付きSQLファイル（`infrastructure/migrate.py:
    apply_pending_migrations`）で行う（改善計画T17）。以前はこの関数へALTER文を直接
    追記する方式だったが、静的道路属性計画（docs/static-road-attributes-plan.md）に向けて
    列追加が繰り返される見込みのため分離した（decisions/pre-static-attributes-gate.md 決定3）。
    このため、実DBに対して呼び出す場合は本関数の直後に`apply_pending_migrations`も
    呼び出すこと（呼び出し例: `app/batch/import_pbf.py`）。

    Alembic等のフル機能マイグレーションツールは導入していない（このプロジェクトの規模には
    過剰と判断、decisions/pre-static-attributes-gate.md 決定3参照）。
    """
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(Base.metadata.create_all)


def _elevation_row_to_domain(row: ElevationAttributeRow) -> ElevationAttribute:
    return ElevationAttribute(
        edge_id=row.edge_id,
        start_elevation_m=row.start_elevation_m,
        end_elevation_m=row.end_elevation_m,
        elevation_gain_m=row.elevation_gain_m,
        elevation_loss_m=row.elevation_loss_m,
        average_grade=row.average_grade,
        max_grade=row.max_grade,
        min_grade=row.min_grade,
        data_source=row.data_source,
        data_version=row.data_version,
        calculated_at=row.calculated_at.isoformat(),
    )


def _raw_node_row_to_coords(row: OsmRawNodeRow) -> tuple[float, float]:
    point = to_shape(row.geom)
    return point.y, point.x  # (latitude, longitude)


# 路面タイル（MVT）をPostGIS側で丸ごと生成するクエリ（get_road_surface_tile_mvt参照）。
#
# 以前は「bbox内の全way行（数千件のジオメトリ）をPythonへ転送→shapelyでdecode→
# mapbox_vector_tileでencode」という構成で、遠隔DB（Supabaseムンバイ）では行転送だけで
# 数秒、Python側のCPU処理（GILを握る）でさらに数秒かかり、パン操作のバースト時は
# 3並列の待ち行列が30秒を超えてフロントエンド（Next.jsのrewritesプロキシ、デフォルト
# 30秒タイムアウト）が一律500を返す不具合の主因になっていた。ST_AsMVTなら転送は
# 完成済みタイル1個（数十KB）で済み、エンコードはPostGISのC実装が担う。
#
# surface_goodの分類はdomain/road.pyのclassify_osm_surfaceと同義（タグ集合も同じ定数を
# バインドする）: 良い=true / 悪い=false / 不明(タグ無し・未知タグ)=NULL。
# ST_AsMVTはNULL値のプロパティをfeatureから省略するため、MVT上は「キー無し」になり、
# Python実装（mapbox_vector_tileもNone値を省略）ともフロントエンドの
# ["get","surface_good"]==null判定（不明=グレー表示）とも互換。
# lower(btrim())はclassify_osm_surfaceのstrip().lower()に対応する（btrimはASCII空白のみ
# だが、OSMのsurfaceタグに全角空白等が入るケースは実データ上考慮しない）。
#
# surface（正規化済み生タグ）とhighway（OSM道路種別）もプロパティとして焼き込む。
# フロントエンドが色分けモード（舗装/未舗装・路面種別・道路種別）をスタイル式の差し替え
# だけで切り替えられるようにするためで、surface_good（3値の正準分類。ルート評価と共通）
# は従来互換のためそのまま残す。surfaceはフロントエンドのグルーピングが文字列一致で
# 済むようlower(btrim())で正規化した値を入れる。
#
# ST_AsMVTGeom: 対象タイルのWeb Mercator範囲（ST_TileEnvelope、XYZ方式でPython側の
# tile_bounds_lonlatと同じタイル座標系）へ射影し、extent=TILE_EXTENT（Pythonエンコーダと
# 同じ4096）・バッファ256（MVT標準値。タイル境界を跨ぐ線の描画継続に必要）でクリップする。
# クリップ後に空になったジオメトリはNULLになるため内側のWHEREで除外する。
#
# カバレッジ判定（road_graph_tilesのz12祖先タイルマーク）も同じクエリへ畳み込み、
# 1タイルあたりのDB往復を1回にする（Supabaseが遠隔リージョンにあり、往復1回の削減が
# そのまま数百ms〜1秒程度の短縮になる。以前はis_tile_cached＋MVT生成の2往復だった）。
# CASE式は条件がfalseの分岐を評価しないため、カバレッジ外ではMVT生成のサブクエリ自体が
# 実行されない。
# 静的道路属性 P0（docs/static-road-attributes-plan.md）追加プロパティの計算根拠:
# - smoothness: 生タグをlower(btrim())で正規化して焼くだけ（surfaceと同じ流儀）
# - tunnel/bridge: タグ値'yes'のときだけtrueを焼く（それ以外はキー省略＝ST_AsMVTがNULLを
#   省略する既存の挙動をそのまま使う。「非該当」が大多数のため省略した方がタイルが軽い）
# - traffic_stress/bicycle_infra: domain/traffic.py（traffic_stress_level/
#   classify_bicycle_infrastructure）と1:1対応するCASE式。SQLにPythonを呼び出す手段が
#   無いためやむを得ず判定ロジックを2箇所持つが、test_road_graph_repository.pyの
#   整合性テストで同じ入力に対し常に同じ出力になることを担保する。
#   traffic_stressの基本値（highway→1-4）はTRAFFIC_STRESS_BASE_BY_HIGHWAY（正準1箇所）から
#   導出した配列をバインドし、ハードコードの二重管理を避ける（good_tags/bad_tagsと同じ方式）。
#   maxspeed/lanesの数値パースは、Pythonのparse_maxspeed/parse_lanes（int(float(x))で
#   小数を切り捨て）と合わせるためtrunc()を使い、非数値文字列（"30 mph"等）は正規表現で
#   弾いてunknown安全にする。
_ROAD_SURFACE_TILE_MVT_SQL = (
    text(
        """
        WITH coverage AS (
            SELECT EXISTS(
                SELECT 1 FROM road_graph_tiles
                WHERE zoom = :coverage_zoom AND x = :coverage_x AND y = :coverage_y
            ) AS covered
        )
        SELECT
            coverage.covered,
            CASE WHEN coverage.covered THEN (
                SELECT ST_AsMVT(mvt.*, :layer_name, :extent, 'geom') FROM (
                    SELECT
                        ST_AsMVTGeom(
                            ST_Transform(w.geom, 3857), ST_TileEnvelope(:z, :x, :y), :extent, 256, true
                        ) AS geom,
                        CASE
                            WHEN lower(btrim(w.surface)) = ANY(:good_tags) THEN true
                            WHEN lower(btrim(w.surface)) = ANY(:bad_tags) THEN false
                        END AS surface_good,
                        lower(btrim(w.surface)) AS surface,
                        w.highway AS highway,
                        lower(btrim(w.tags->>'smoothness')) AS smoothness,
                        CASE WHEN lower(btrim(w.tags->>'tunnel')) = 'yes' THEN true END AS tunnel,
                        CASE WHEN lower(btrim(w.tags->>'bridge')) = 'yes' THEN true END AS bridge,
                        CASE
                            WHEN w.highway = 'cycleway' OR 'track' = ANY(cw.values) THEN 'separated'
                            WHEN 'lane' = ANY(cw.values) THEN 'lane'
                            WHEN cw.values && ARRAY['share_busway', 'shared_lane'] THEN 'shared_busway'
                            WHEN w.highway IN ('path', 'footway')
                                 AND lower(btrim(w.tags->>'bicycle')) IN ('yes', 'designated', 'permissive')
                                THEN 'shared_pedestrian'
                            WHEN lower(btrim(w.tags->>'bicycle')) = 'no' THEN 'prohibited'
                            WHEN w.highway IS NOT NULL THEN 'roadway'
                        END AS bicycle_infra,
                        CASE
                            WHEN ts.base IS NULL THEN NULL
                            WHEN lower(btrim(w.tags->>'motor_vehicle')) = 'no' THEN 1
                            ELSE GREATEST(1, LEAST(4,
                                ts.base
                                + CASE
                                      WHEN 'track' = ANY(cw.values) THEN -2
                                      WHEN 'lane' = ANY(cw.values) THEN -1
                                      ELSE 0
                                  END
                                + CASE
                                      WHEN btrim(w.tags->>'maxspeed') ~ '^[0-9]+(\\.[0-9]+)?$'
                                           AND trunc(btrim(w.tags->>'maxspeed')::numeric) <= 30 THEN -1
                                      WHEN btrim(w.tags->>'maxspeed') ~ '^[0-9]+(\\.[0-9]+)?$'
                                           AND trunc(btrim(w.tags->>'maxspeed')::numeric) >= 60 THEN 1
                                      ELSE 0
                                  END
                                + CASE
                                      WHEN btrim(w.tags->>'lanes') ~ '^[0-9]+(\\.[0-9]+)?$'
                                           AND trunc(btrim(w.tags->>'lanes')::numeric) >= 4 THEN 1
                                      ELSE 0
                                  END
                            ))
                        END AS traffic_stress
                    FROM osm_raw_ways w
                    CROSS JOIN LATERAL (
                        SELECT ARRAY[
                            lower(btrim(w.tags->>'cycleway')),
                            lower(btrim(w.tags->>'cycleway:left')),
                            lower(btrim(w.tags->>'cycleway:right')),
                            lower(btrim(w.tags->>'cycleway:both'))
                        ] AS values
                    ) cw
                    CROSS JOIN LATERAL (
                        SELECT CASE
                            WHEN w.highway = ANY(:ts_base1) THEN 1
                            WHEN w.highway = ANY(:ts_base2) THEN 2
                            WHEN w.highway = ANY(:ts_base3) THEN 3
                            WHEN w.highway = ANY(:ts_base4) THEN 4
                        END AS base
                    ) ts
                    WHERE w.geom IS NOT NULL
                      AND ST_Intersects(w.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
                ) mvt
                WHERE mvt.geom IS NOT NULL
            ) END AS tile
        FROM coverage
        """
    )
    .bindparams(
        bindparam("good_tags", value=sorted(GOOD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
        bindparam("bad_tags", value=sorted(BAD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
        *(
            bindparam(
                f"ts_base{level}",
                value=sorted(hw for hw, lv in TRAFFIC_STRESS_BASE_BY_HIGHWAY.items() if lv == level),
                type_=ARRAY(Text()),
            )
            for level in (1, 2, 3, 4)
        ),
    )
)


# 座標点列→最近傍road_edgeのsurfaceタグ取得（改善計画T21、評価のエンジン非依存化）。
# ORS産geometryのサンプル点を自前DBのEdgeへ空間マッチする用途。
#
# LATERAL側は`ORDER BY e.geom <-> pts.geom LIMIT 1`のみ（WHERE句を持たない）でGiST索引の
# 純粋なKNNスキャンにする。最大距離の足切り（`ST_DWithin(..., ::geography, :max_distance_m)`）は
# 選ばれた1行に対して外側のCASEで行う。当初はLATERAL内に`WHERE ST_DWithin(...)`を直接書いていたが、
# `ORDER BY <-> LIMIT`にWHERE句を同居させると、範囲内に候補が無い点ではプランナが
# 「フィルタに合う1行が見つかるまでKNN順に全行を舐める」実行計画になり、関東本土全域規模の
# road_edges（134万行）で1点あたり数秒級に悪化することを実測で確認した（EXPLAIN ANALYZEで
# `Rows Removed by Filter`が全行分出る。ローカルPostGIS実データ22,164行でも1点3.4秒）。
# WHERE句を外側へ追い出すとLATERALは常にO(log n)のKNN索引スキャン1回で終わり、
# 同条件で1点あたり数ミリ秒（12点合計38ms）まで改善した。
_NEAREST_SURFACE_SQL = text(
    """
    WITH pts AS (
        SELECT
            ord,
            ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS geom,
            ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography AS geog
        FROM unnest(CAST(:lats AS float8[]), CAST(:lons AS float8[])) WITH ORDINALITY AS t(lat, lon, ord)
    )
    SELECT pts.ord,
           CASE WHEN ST_DWithin(nearest.geom::geography, pts.geog, :max_distance_m) THEN w.surface END AS surface
    FROM pts
    LEFT JOIN LATERAL (
        SELECT e.osm_way_id, e.geom
        FROM road_edges e
        ORDER BY e.geom <-> pts.geom
        LIMIT 1
    ) nearest ON true
    LEFT JOIN osm_raw_ways w ON w.osm_way_id = nearest.osm_way_id
    ORDER BY pts.ord
    """
).bindparams(
    bindparam("lats", type_=ARRAY(Float())),
    bindparam("lons", type_=ARRAY(Float())),
)

# 静的道路属性P1（信号・横断歩道・一時停止・踏切のnode取込・停止密度評価）。
# _NEAREST_SURFACE_SQLと違い「最近傍1件」ではなく「距離内の件数」を求める単純な
# LEFT JOIN + COUNTのため、ORDER BY <-> LIMITは使わない（T21コメントにある
# 「WHEREをKNNと同居させる」アンチパターンには該当せず、GiST索引で素直に
# index nested loopになる）。edge_idはWHEREで先に絞るため、LEFT JOINでも
# 指定edge_id全件が0件を含めて1行ずつ返る。
_STOP_POI_COUNTS_SQL = text(
    """
    SELECT e.edge_id, COUNT(p.osm_node_id) AS stop_count
    FROM road_edges e
    LEFT JOIN osm_raw_pois p ON ST_DWithin(p.geom::geography, e.geom::geography, :max_distance_m)
    WHERE e.edge_id = ANY(CAST(:edge_ids AS text[]))
    GROUP BY e.edge_id
    """
)

# ORSエンジン用（サンプル点ごとの近傍件数）。_NEAREST_SURFACE_SQLと同じUNNEST WITH
# ORDINALITY構造だが、単純な件数JOINのため_NEAREST_SURFACE_SQLの回避策（WHEREを
# LATERAL外へ出す）は元々不要。
_NEAREST_STOP_POI_COUNTS_SQL = text(
    """
    WITH pts AS (
        SELECT
            ord,
            ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography AS geog
        FROM unnest(CAST(:lats AS float8[]), CAST(:lons AS float8[])) WITH ORDINALITY AS t(lat, lon, ord)
    )
    SELECT pts.ord, COUNT(p.osm_node_id) AS stop_count
    FROM pts
    LEFT JOIN osm_raw_pois p ON ST_DWithin(p.geom::geography, pts.geog, :max_distance_m)
    GROUP BY pts.ord
    ORDER BY pts.ord
    """
).bindparams(
    bindparam("lats", type_=ARRAY(Float())),
    bindparam("lons", type_=ARRAY(Float())),
)


def _rows_to_road_graph(edge_rows: Iterable[RoadEdgeRow], node_rows: Iterable[RoadNodeRow]) -> RoadGraph:
    """`get_graph_in_bbox`用。Edge/Nodeが数万〜十数万行になる規模のため、1行ずつ
    `to_shape()`を呼ぶ従来実装ではなく`shapely.from_wkb()`のバッチAPI（GEOS呼び出しの
    ループをPython側ではなくC側で回す）でgeometryを一括デコードし、Pydanticの
    `model_construct`（フィールド検証をスキップ。DB由来で型が保証済みのため安全）で
    Node/DirectedEdgeを構築する。実データ（東京都心4km相当bbox、Edge151,820件・
    Node59,270件）での実測でCPU時間を約37%削減（6.11秒→3.84秒、
    backend/benchmarks/README.md参照）。
    """
    edge_rows = list(edge_rows)
    node_rows = list(node_rows)
    edge_lines = shapely.from_wkb([bytes(row.geom.data) for row in edge_rows])
    node_points = shapely.from_wkb([bytes(row.geom.data) for row in node_rows])

    nodes = {
        row.node_id: Node.model_construct(
            node_id=row.node_id, latitude=point.y, longitude=point.x, osm_node_id=row.osm_node_id
        )
        for row, point in zip(node_rows, node_points)
    }
    edges = {
        row.edge_id: DirectedEdge.model_construct(
            edge_id=row.edge_id,
            from_node_id=row.from_node_id,
            to_node_id=row.to_node_id,
            # DirectedEdge.geometryは[[lat, lon], ...]だが、Shapely/PostGISの座標順は(lon, lat)。
            geometry=[[lat, lon] for lon, lat in line.coords],
            distance_m=row.distance_m,
            osm_way_id=row.osm_way_id,
            highway=row.highway,
        )
        for row, line in zip(edge_rows, edge_lines)
    }
    return RoadGraph(graph_version=CACHED_GRAPH_VERSION, nodes=nodes, edges=edges)


def _primary_way_conditions(envelope):
    """「主対象Way」＝bboxのenvelopeとST_Intersectsで交差するWay、を表すWHERE条件。
    `get_way_specs_with_closure`と`is_split_up_to_date`の両方が同じ「何が主対象Wayか」の
    定義を使う必要があるため、述語がずれないようここへ共通化する。
    """
    return (OsmRawWayRow.geom.is_not(None), func.ST_Intersects(OsmRawWayRow.geom, envelope))


def _way_spec_row_to_domain(row: OsmRawWayRow) -> WaySpec:
    return WaySpec(
        osm_way_id=row.osm_way_id,
        node_ids=list(row.node_ids),
        highway=row.highway,
        surface=row.surface,
        tags=row.tags or {},
        direction=row.direction,
    )


async def _bulk_upsert(
    session: AsyncSession,
    model,
    rows: list[dict],
    index_elements: list[str],
    update_columns: list[str] | None,
    change_detection_columns: list[str] | None = None,
) -> None:
    """INSERT ... ON CONFLICTによるバルクUPSERT。

    行単位のSession.mergeは1行ごとにSELECT+INSERT/UPDATEのラウンドトリップが発生し、
    都心部のbbox（数万Node・十数万Edge）では1リクエストが数十分オーダーになることを
    実機で確認したため（設計レビュー指摘7）、複数行VALUESの一括文に置き換えた。
    update_columns=Noneは競合時に何もしない（DO NOTHING）。

    change_detection_columns指定時は、そのカラム群が実際に変わった行だけを更新する
    （`ON CONFLICT ... DO UPDATE ... WHERE`。条件がfalseの行は`update_columns`に
    `updated_at`等の監査用カラムを含めていてもそれ自体を含め一切更新されない）。
    内容が同一な再UPSERT（例: 1つのWayが複数タイルにまたがり、隣接タイルを後から
    取得しただけで無関係なWayを再送してしまうケース）で`updated_at`が無意味に進むのを防ぎ、
    鮮度判定（`is_split_up_to_date`）を安定させるために使う。
    """
    for chunk in _chunked(rows, _BULK_CHUNK_ROWS):
        stmt = pg_insert(model).values(chunk)
        if update_columns:
            where_clause = None
            if change_detection_columns:
                where_clause = or_(
                    *(
                        getattr(model, column).is_distinct_from(stmt.excluded[column])
                        for column in change_detection_columns
                    )
                )
            stmt = stmt.on_conflict_do_update(
                index_elements=index_elements,
                set_={column: stmt.excluded[column] for column in update_columns},
                where=where_clause,
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)
        await session.execute(stmt)


class _SessionRepository:
    """1リクエスト（1トランザクション）につき1インスタンスを想定し、`AsyncSession`を
    DIで受け取る共通基底。commitは持たない（モジュールdocstringの規約参照）。"""

    def __init__(self, session: AsyncSession):
        self._session = session


class DerivedGraphRepository(_SessionRepository):
    """派生グラフ（road_nodes/road_edges、交差点分割の結果）の読み書きと鮮度判定。"""

    async def get_graph_in_bbox(self, bbox: BoundingBox) -> RoadGraph | None:
        envelope = func.ST_MakeEnvelope(
            bbox.min_longitude, bbox.min_latitude, bbox.max_longitude, bbox.max_latitude, 4326
        )
        edge_stmt = select(RoadEdgeRow).where(func.ST_Intersects(RoadEdgeRow.geom, envelope))
        edge_rows = (await self._session.execute(edge_stmt)).scalars().all()
        if not edge_rows:
            return None

        node_ids = sorted({row.from_node_id for row in edge_rows} | {row.to_node_id for row in edge_rows})
        # =ANY(配列)化の理由はget_elevation_attributesのコメント参照（1要素=1パラメータの
        # IN句展開と異なり配列全体で1パラメータのため、WAN経由でのラウンドトリップ増加を
        # 避けられる。50,000件チャンクなのでasyncpgのパラメータ上限32767個の問題も無い）。
        node_rows = []
        for id_chunk in _chunked(node_ids, 50_000):
            node_stmt = select(RoadNodeRow).where(RoadNodeRow.node_id == any_(cast(id_chunk, ARRAY(Text))))
            node_rows.extend((await self._session.execute(node_stmt)).scalars().all())

        # 密集した都市部のbboxではEdge/Nodeが数万〜十数万行になり、shapelyへのgeometry
        # decode（to_shape）だけで数秒〜十数秒のCPU処理になる（bench_postgis_prepare.py
        # 実測でこの呼び出し単体13.3秒、東京都心4km相当bbox・Edge151,820件）。
        # asyncio.to_threadで逃さないとイベントループを塞ぐ。
        return await asyncio.to_thread(_rows_to_road_graph, edge_rows, node_rows)

    async def is_split_up_to_date(self, bbox: BoundingBox) -> bool:
        """bboxと交差する全ての主対象Way（`_primary_way_conditions`と同じ定義。
        `get_way_specs_with_closure`参照）について、最後のsplit（`save_graph`の
        `way_ids_to_replace`呼び出し）が現在の生データ（`osm_raw_ways.updated_at`）より
        新しいかどうかを判定する。Wayが1本も無ければ（道路の無い地域）自明にTrue。

        Trueなら`get_graph_in_bbox`+`get_surface_attributes`で直接読み出してよい
        （`GraphService.get_or_build_graph_with_attributes`の省略パス）。Falseなら
        `get_way_specs_with_closure`→`build_road_graph`→`save_graph`の通常経路で
        再構築が必要。

        `get_graph_in_bbox`とは判定基準が異なる点に注意: こちらは「Wayが主対象bboxと
        交差するか」（way-membership）で判定するのに対し、`get_graph_in_bbox`は
        「Edgeの実ジオメトリがbboxと交差するか」（geometry-membership）で読み出す。
        交差点分割の結果、境界付近でこの2つが完全には一致しない場合がありうるが、
        呼び出し元（RoadGraphEngine）は探索半径に対しBBOX_MARGIN_MIN_KM（最低2km）の
        マージンを既に載せてbboxを渡しているため許容する。
        """
        envelope = func.ST_MakeEnvelope(
            bbox.min_longitude, bbox.min_latitude, bbox.max_longitude, bbox.max_latitude, 4326
        )
        stale_stmt = (
            select(OsmRawWayRow.osm_way_id)
            .where(
                *_primary_way_conditions(envelope),
                or_(OsmRawWayRow.split_at.is_(None), OsmRawWayRow.split_at < OsmRawWayRow.updated_at),
            )
            .limit(1)
        )
        return (await self._session.execute(stale_stmt)).first() is None

    async def save_graph(self, graph: RoadGraph, way_ids_to_replace: set[int] | None = None) -> None:
        """RoadGraphをroad_nodes/road_edgesへ永続化する。

        `way_ids_to_replace`を指定した場合、それらのosm_way_idを持つ既存Edge行を
        全削除してから`graph`内の該当Edgeを挿入し直す（delete-then-reinsert）。
        `build_road_graph`は渡されたWay集合全体から交差点を再計算するため、
        Wayの分割結果が前回と変わっていた場合でも、古い分割によるEdge行が
        孤立して残らないようにするための措置（タイル境界依存の分割不一致問題への対応、
        本ファイル冒頭のdocstring参照）。`way_ids_to_replace`外のosm_way_idを持つEdge
        （closureで近傍として取得しただけのWay）はこの呼び出しでは保存しない
        （不完全な文脈で計算した分割結果によって、他のリクエストが正しく永続化した
        Edgeを誤って上書き・破壊しないため）。
        Noneの場合は`graph`内の全Edgeを単純にUPSERTする（従来の挙動）。

        `way_ids_to_replace`指定時は、その各osm_way_idについて`osm_raw_ways.split_at`も
        この時刻へ更新する（`is_split_up_to_date`の鮮度判定に使う。Edgeを1件も生成しなかった
        Wayでもスタンプする点に注意。road_graph_models.py: OsmRawWayRowのdocstring参照）。
        """
        now = datetime.now(timezone.utc)
        # Edgeがroad_nodes.node_idを外部キー参照するため、先にNodeを一括UPSERTする
        # （同一トランザクション内のため文の実行順で制約を満たせる）。
        node_rows = [
            {
                "node_id": node.node_id,
                "osm_node_id": node.osm_node_id,
                "geom": from_shape(Point(node.longitude, node.latitude), srid=4326),
                "updated_at": now,
            }
            for node in graph.nodes.values()
        ]
        await _bulk_upsert(
            self._session, RoadNodeRow, node_rows, ["node_id"], ["osm_node_id", "geom", "updated_at"])

        if way_ids_to_replace:
            for id_chunk in _chunked(sorted(way_ids_to_replace), _ID_CHUNK_SIZE):
                await self._session.execute(delete(RoadEdgeRow).where(RoadEdgeRow.osm_way_id.in_(id_chunk)))
                await self._session.execute(
                    update(OsmRawWayRow).where(OsmRawWayRow.osm_way_id.in_(id_chunk)).values(split_at=now)
                )

        edge_rows = [
            {
                "edge_id": edge.edge_id,
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "geom": from_shape(LineString([(lon, lat) for lat, lon in edge.geometry]), srid=4326),
                "distance_m": edge.distance_m,
                "osm_way_id": edge.osm_way_id,
                "highway": edge.highway,
                "updated_at": now,
            }
            for edge in graph.edges.values()
            if way_ids_to_replace is None or edge.osm_way_id in way_ids_to_replace
        ]
        await _bulk_upsert(
            self._session,
            RoadEdgeRow,
            edge_rows,
            ["edge_id"],
            ["from_node_id", "to_node_id", "geom", "distance_m", "osm_way_id", "highway", "updated_at"],
        )


class RawOsmRepository(_SessionRepository):
    """生OSM層（osm_raw_ways/osm_raw_nodes）とタイル取得マーカー（road_graph_tiles）の読み書き。"""

    async def save_raw_ways(self, way_specs: list[WaySpec], node_coords: dict[int, tuple[float, float]]) -> None:
        """生のOSM Way/Nodeデータを永続化する。Wayのタグ・ノード列は取得元タイルに
        依存せず一意に決まるため、build_road_graphの分割結果とは異なり素直にUPSERTしてよい。

        ただしosm_raw_waysの`updated_at`は内容が実際に変わった行だけを更新する
        （road_graph_models.py: OsmRawWayRowのdocstring参照）。1つのWayが複数タイルに
        またがるのは普通にあり、Overpassはタイル単位で問い合わせてもWay全体を返すため、
        隣接タイルを後から取得しただけで無関係なWayを毎回再送してしまう。無条件に
        `updated_at`を更新すると`is_split_up_to_date`の鮮度判定を誤らせる。
        """
        if not way_specs:
            return
        now = datetime.now(timezone.utc)
        referenced_node_ids = {node_id for way in way_specs for node_id in way.node_ids}
        node_rows = []
        for node_id in sorted(referenced_node_ids):
            coords = node_coords.get(node_id)
            if coords is None:
                continue
            lat, lon = coords
            node_rows.append(
                {
                    "osm_node_id": node_id,
                    "geom": from_shape(Point(lon, lat), srid=4326),
                    "updated_at": now,
                }
            )
        await _bulk_upsert(
            self._session, OsmRawNodeRow, node_rows, ["osm_node_id"], ["geom", "updated_at"])

        way_rows_by_id: dict[int, dict] = {}
        for way in way_specs:
            if way.osm_way_id is None:
                continue
            # 実体化済みLINESTRING（座標が判明しているノードが2点未満ならNULL）。
            # PBF取込バッチと同じ意味論（road_graph_models.py: OsmRawWayRow.geomのコメント参照）。
            way_coords = [node_coords[n] for n in way.node_ids if n in node_coords]
            geom = (
                from_shape(LineString([(lon, lat) for lat, lon in way_coords]), srid=4326)
                if len(way_coords) >= 2
                else None
            )
            way_rows_by_id[way.osm_way_id] = {
                "osm_way_id": way.osm_way_id,
                "node_ids": way.node_ids,
                "highway": way.highway,
                "surface": way.surface,
                "tags": way.tags,
                "direction": way.direction,
                "geom": geom,
                "updated_at": now,
            }
        await _bulk_upsert(
            self._session,
            OsmRawWayRow,
            list(way_rows_by_id.values()),
            ["osm_way_id"],
            ["node_ids", "highway", "surface", "tags", "direction", "geom", "updated_at"],
            # geomは比較対象に含めない: PostGISのgeometry `=`（is_distinct_fromの内部比較）は
            # 形状の完全一致ではなくbbox一致のため、node_idsが変わらなければgeomも変わらない
            # という前提の下でnode_ids側の比較に委ねる。
            change_detection_columns=["node_ids", "highway", "surface", "tags", "direction"],
        )

    async def get_way_specs_with_closure(
        self, bbox: BoundingBox
    ) -> tuple[list[WaySpec], dict[int, tuple[float, float]], set[int]]:
        """bboxとジオメトリが交差する「主対象Way」と、それらの周辺文脈となる「近傍Way」を
        合わせて返す。近傍Wayとの重ね合わせによって、build_road_graphがタイル境界や
        要求bboxの境界に関わらず正しく交差点を判定できるようにする
        （タイル境界依存の分割不一致問題への根本対応）。

        当初の実装は「bbox内にノードを持つWay」→「そのノード配列と重なるWay」という
        node_ids配列のGIN検索（&&）だったが、都心部のbboxでは配列パラメータが数十万
        要素になり実用的な速度が出ないことを実機で確認した。現在は次の空間検索へ
        置き換えている（geom列＝Phase 1で追加した実体化済みLINESTRINGが前提。
        NULLのままの旧データはcreate_tablesのバックフィルで補われる）:

        1. 主対象Way: bboxのenvelopeとST_Intersectsで交差するWay（旧実装の「bbox内に
           ノードを持つ」の上位互換。頂点がbbox内に無くてもbboxを横切るWayを含む）
        2. 近傍Way: 主対象Way全体のextent（全長分の外接矩形、bbox外の部分も含む）と
           交差するWay。「主対象とノードを共有するWay」の厳密な上位集合であり、
           余分に含まれるWayは交差点判定の文脈情報が増えるだけで正しさを損なわない
           （近傍Wayはこの呼び出しでは永続化しないため）

        戻り値は(WaySpec一覧, それらが参照する全ノードの座標, 主対象WayのosmWay ID集合)。
        3つ目の要素は`save_graph`の`way_ids_to_replace`にそのまま渡す想定。

        既知の残存制約: 近傍の探索は1ホップ相当に限定している（近傍Wayのさらに先の
        接続は辿らない）。間接的に関係するWay同士の交差点は、そのWay自身が別の
        リクエストで「主対象」として処理されるまで更新されない（結果整合的、
        docs/architecture.md参照）。
        """
        bbox_params = {
            "xmin": bbox.min_longitude,
            "ymin": bbox.min_latitude,
            "xmax": bbox.max_longitude,
            "ymax": bbox.max_latitude,
        }
        envelope = func.ST_MakeEnvelope(
            bbox.min_longitude, bbox.min_latitude, bbox.max_longitude, bbox.max_latitude, 4326
        )
        primary_id_stmt = select(OsmRawWayRow.osm_way_id).where(*_primary_way_conditions(envelope))
        primary_way_ids = set((await self._session.execute(primary_id_stmt)).scalars().all())
        if not primary_way_ids:
            return [], {}, set()

        # 主対象Wayの全長分のextent（1回の集約クエリでbbox外へのはみ出し範囲を得る）
        extent_row = (
            await self._session.execute(
                text(
                    "SELECT ST_XMin(e) AS xmin, ST_YMin(e) AS ymin, ST_XMax(e) AS xmax, ST_YMax(e) AS ymax "
                    "FROM (SELECT ST_Extent(geom) AS e FROM osm_raw_ways "
                    "WHERE geom IS NOT NULL "
                    "AND ST_Intersects(geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))) s"
                ),
                bbox_params,
            )
        ).one()

        extent_envelope = func.ST_MakeEnvelope(
            extent_row.xmin, extent_row.ymin, extent_row.xmax, extent_row.ymax, 4326
        )
        way_stmt = select(OsmRawWayRow).where(
            OsmRawWayRow.geom.is_not(None), func.ST_Intersects(OsmRawWayRow.geom, extent_envelope)
        )
        way_rows = (await self._session.execute(way_stmt)).scalars().all()
        way_specs = [_way_spec_row_to_domain(row) for row in way_rows]

        # ノード座標はWayが実際に参照するIDで正確に引く（=ANY(配列)は1パラメータで済み、
        # IN句のようなパラメータ数上限の問題を起こさない）。
        final_node_ids = sorted({node_id for way in way_specs for node_id in way.node_ids})
        node_coords: dict[int, tuple[float, float]] = {}
        for id_chunk in _chunked(final_node_ids, 50_000):
            node_stmt = select(OsmRawNodeRow).where(
                OsmRawNodeRow.osm_node_id == any_(cast(id_chunk, ARRAY(BigInteger)))
            )
            for row in (await self._session.execute(node_stmt)).scalars().all():
                node_coords[row.osm_node_id] = _raw_node_row_to_coords(row)

        return way_specs, node_coords, primary_way_ids


    async def is_tile_cached(self, zoom: int, x: int, y: int) -> bool:
        stmt = select(RoadGraphTileRow).where(
            RoadGraphTileRow.zoom == zoom, RoadGraphTileRow.x == x, RoadGraphTileRow.y == y
        )
        row = (await self._session.execute(stmt)).scalars().first()
        return row is not None

    async def mark_tile_cached(self, zoom: int, x: int, y: int) -> None:
        # 以前はSession.merge（ORM。INSERTがflushまで保留される）だったが、T6でcommitを
        # サービス層へ移した結果、同一トランザクション内の後続の生SQL実行
        # （get_road_surface_tile_mvt等。text()の実行はautoflushの対象外）から保留中の行が
        # 見えない問題が顕在化した。即時実行されるCoreのUPSERTへ変更する
        # （_bulk_upsertと同じ方式。挙動は従来のmerge＝存在すればfetched_at更新と同じ）。
        stmt = pg_insert(RoadGraphTileRow).values(zoom=zoom, x=x, y=y, fetched_at=datetime.now(timezone.utc))
        stmt = stmt.on_conflict_do_update(
            index_elements=["zoom", "x", "y"], set_={"fetched_at": stmt.excluded.fetched_at}
        )
        await self._session.execute(stmt)


class RoadSurfaceTileQuery(_SessionRepository):
    """地域路面レイヤー（RegionService）表示用のMVT生成。読み取り専用でcommit対象の書き込みは無い。"""

    async def get_road_surface_tile_mvt(
        self, z: int, x: int, y: int, bbox: BoundingBox, coverage_tile: tuple[int, int, int]
    ) -> bytes | None:
        """地域路面レイヤー用のMVTタイル1枚を、PostGIS側（ST_AsMVT）で丸ごと生成して返す
        （docs/osm-pbf-import.md Phase 2。クエリの設計意図は_ROAD_SURFACE_TILE_MVT_SQLの
        コメント参照）。

        カバレッジ判定も同じクエリで行う（DB往復1回化）: `coverage_tile`（(zoom, x, y)、
        呼び出し側がtile_ancestorで求めたz12祖先タイル）がroad_graph_tilesに未マークなら
        None（取込範囲外。呼び出し側でOverpass/空タイルへのフォールバック判定へ）。
        マーク済みで対象wayが1本も無い場合は空バイト列（有効な空MVT、「道路が無いことを
        確認済み」の正常応答でNoneとは区別される）。

        Road Graph構築（get_way_specs_with_closure）と異なり交差点分割・近傍closureは
        不要で、表示に必要な「線とsurface分類」だけをタイルへ焼き込む。

        bboxは呼び出し側がtile_bounds_lonlatで求めたz/x/yと同じタイルの経緯度範囲
        （検索条件はST_TileEnvelopeから導出せず既存のbbox表現を使い、従来の検索述語との
        パリティとgistインデックス利用を明確にする）。
        """
        coverage_zoom, coverage_x, coverage_y = coverage_tile
        result = await self._session.execute(
            _ROAD_SURFACE_TILE_MVT_SQL,
            {
                "coverage_zoom": coverage_zoom,
                "coverage_x": coverage_x,
                "coverage_y": coverage_y,
                "layer_name": ROAD_SURFACE_LAYER_NAME,
                "extent": TILE_EXTENT,
                "z": z,
                "x": x,
                "y": y,
                "xmin": bbox.min_longitude,
                "ymin": bbox.min_latitude,
                "xmax": bbox.max_longitude,
                "ymax": bbox.max_latitude,
            },
        )
        covered, tile = result.one()
        if not covered:
            return None
        # カバレッジ内で対象0行のときST_AsMVT（集約関数）はNULLを返す。長さ0のバイト列は
        # 「featureが1つも無い有効なMVT」としてMapLibreがそのまま受理する。
        return bytes(tile) if tile is not None else b""


class AttributeRepository(_SessionRepository):
    """Edge単位のRoad Attribute（elevation_attributes）の読み書き。

    surfaceは専用テーブルを持たず、road_edges.osm_way_id経由でosm_raw_ways.surfaceを
    JOINして都度導出する（改善計画T9でsurface_attributesテーブルを廃止）。

    新しい属性種別（交通・信号密度等）を追加するときはこのクラスへメソッドを足す
    （他のリポジトリには触れない。docs/design-review-2026-08-15.md 設計原則6）。
    """

    async def get_elevation_attributes(self, edge_ids: list[str]) -> dict[str, ElevationAttribute]:
        if not edge_ids:
            return {}
        result: dict[str, ElevationAttribute] = {}
        # =ANY(配列)は1要素=1パラメータのIN句と異なり配列全体で1パラメータのため、
        # WAN経由（Supabase等）でラウンドトリップ回数がそのまま遅延に乗る問題を避けられる
        # （get_way_specs_with_closureのノード座標取得と同じ手法。50,000件のチャンク幅も
        # そちらと合わせている。実測はbackend/benchmarks/README.md参照）。
        for id_chunk in _chunked(edge_ids, 50_000):
            stmt = select(ElevationAttributeRow).where(
                ElevationAttributeRow.edge_id == any_(cast(id_chunk, ARRAY(Text)))
            )
            for row in (await self._session.execute(stmt)).scalars().all():
                result[row.edge_id] = _elevation_row_to_domain(row)
        return result

    async def save_elevation_attributes(self, attributes: list[ElevationAttribute]) -> None:
        if not attributes:
            return
        rows = [
            {
                "edge_id": a.edge_id,
                "start_elevation_m": a.start_elevation_m,
                "end_elevation_m": a.end_elevation_m,
                "elevation_gain_m": a.elevation_gain_m,
                "elevation_loss_m": a.elevation_loss_m,
                "average_grade": a.average_grade,
                "max_grade": a.max_grade,
                "min_grade": a.min_grade,
                "data_source": a.data_source,
                "data_version": a.data_version,
                "calculated_at": datetime.fromisoformat(a.calculated_at),
            }
            for a in attributes
        ]
        await _bulk_upsert(
            self._session,
            ElevationAttributeRow,
            rows,
            ["edge_id"],
            [
                "start_elevation_m", "end_elevation_m", "elevation_gain_m", "elevation_loss_m",
                "average_grade", "max_grade", "min_grade", "data_source", "data_version", "calculated_at",
            ],
        )

    async def get_surface_attributes(self, edge_ids: list[str]) -> dict[str, str | None]:
        if not edge_ids:
            return {}
        result: dict[str, str | None] = {}
        # road_edges.osm_way_id経由でosm_raw_ways.surfaceをJOIN導出する（改善計画T9、
        # surface_attributesテーブル廃止）。JOINにはmigration 0001の
        # idx_road_edges_osm_way_idを使う。osm_way_idが無いEdge（座標2点未満等）は
        # LEFT JOINでsurface=Noneになる。=ANY(配列)化の理由はget_elevation_attributesの
        # コメント参照。旧実装（専用テーブルへのSELECT）は都心4km相当bbox
        # （edge_id 151,820件・チャンク数16）でSupabase(WAN)実測7.97〜11.49秒だった。
        for id_chunk in _chunked(edge_ids, 50_000):
            stmt = (
                select(RoadEdgeRow.edge_id, OsmRawWayRow.surface)
                .select_from(RoadEdgeRow)
                .outerjoin(OsmRawWayRow, RoadEdgeRow.osm_way_id == OsmRawWayRow.osm_way_id)
                .where(RoadEdgeRow.edge_id == any_(cast(id_chunk, ARRAY(Text))))
            )
            for edge_id, surface in (await self._session.execute(stmt)).all():
                result[edge_id] = surface
        return result

    async def get_nearest_surface_tags(
        self, points: list[tuple[float, float]], max_distance_m: float = SURFACE_MATCH_MAX_DISTANCE_M
    ) -> list[str | None]:
        """(lat, lon)点列それぞれについて、`max_distance_m`以内の最近傍road_edgeの
        surfaceタグを返す（入力と同じ順序・同じ長さ。該当Edgeが無い/surfaceタグ無しはNone）。

        改善計画T21（評価のエンジン非依存化）: openrouteserviceエンジンがgeometry上の
        サンプル点をこのメソッドで自前DBのEdgeへ空間マッチし、road_graphエンジンと
        同じOSMタグ語彙（domain/road.py: classify_osm_surface）で評価できるようにする。
        1回のSQLで全点をまとめて処理する（_NEAREST_SURFACE_SQL参照、点数分のラウンド
        トリップを避ける）。
        """
        if not points:
            return []
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        result = await self._session.execute(
            _NEAREST_SURFACE_SQL, {"lats": lats, "lons": lons, "max_distance_m": max_distance_m}
        )
        by_ord = {ord_: surface for ord_, surface in result.all()}
        return [by_ord.get(i + 1) for i in range(len(points))]

    async def get_stop_poi_counts(
        self, edge_ids: list[str], max_distance_m: float = STOP_POI_MATCH_MAX_DISTANCE_M
    ) -> dict[str, int]:
        """指定edge_idそれぞれについて、`max_distance_m`以内にある信号・横断歩道・
        一時停止・踏切（osm_raw_pois）の合計件数を返す（静的道路属性P1）。

        road_graphエンジンのcompute_edge_cost（探索コスト自体）で使う。get_surface_attributes
        と同じ「edge_idリストを渡して辞書で受け取る」形。指定edge_idは（該当POIが0件でも）
        必ず結果に含まれる＝Noneではなく0として扱えることをEvaluationService側が前提にする。
        """
        if not edge_ids:
            return {}
        result: dict[str, int] = {}
        for id_chunk in _chunked(edge_ids, 50_000):
            rows = await self._session.execute(
                _STOP_POI_COUNTS_SQL, {"edge_ids": id_chunk, "max_distance_m": max_distance_m}
            )
            for edge_id, stop_count in rows.all():
                result[edge_id] = stop_count
        return result

    async def get_nearest_stop_poi_counts(
        self, points: list[tuple[float, float]], max_distance_m: float = STOP_POI_MATCH_MAX_DISTANCE_M
    ) -> list[int]:
        """(lat, lon)点列それぞれについて、`max_distance_m`以内にある信号・横断歩道・
        一時停止・踏切（osm_raw_pois）の件数を返す（入力と同じ順序・同じ長さ、静的道路属性P1）。

        改善計画T21のget_nearest_surface_tagsと同じ考え方（openrouteserviceエンジンが
        geometry上のサンプル点をこのメソッドで自前DBへ空間マッチする）。1回のSQLで
        全点をまとめて処理する。
        """
        if not points:
            return []
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        result = await self._session.execute(
            _NEAREST_STOP_POI_COUNTS_SQL, {"lats": lats, "lons": lons, "max_distance_m": max_distance_m}
        )
        by_ord = {ord_: stop_count for ord_, stop_count in result.all()}
        return [by_ord.get(i + 1, 0) for i in range(len(points))]


class RoadGraphRepository:
    """責務別の4リポジトリ（raw_osm/graph/attributes/tile_query属性）を束ね、
    フラットな委譲メソッド群として公開するファサード（改善計画T6）。

    **このフラットな形（`repository.save_raw_ways(...)`等、`repository.raw_osm.save_raw_ways(...)`
    ではない）が、`GraphService`/`ElevationAttributeService`/`RegionService`が依存する
    正式なインターフェースである（改善計画T18で確認・確定）。各サービスは`RoadGraphRepository`
    という具象クラスではなくこのフラットな形をダックタイピングで期待しており、対応するテストは
    それぞれ独立した`FakeRoadGraphRepository`/`FakeRegionRepository`等（同じくフラットな形）を
    注入する。個別リポジトリ（`.raw_osm`/`.graph`/`.attributes`/`.tile_query`）への直接アクセスは
    このファサード自身の実装内部、または検証スクリプト・ファサード単体テストなど
    「フラットな契約を経由しない」ことが明確な用途に限定する。

    **新しい属性の読み書きメソッドを追加するとき**（例: 静的道路属性計画の新属性）は、
    対応する個別リポジトリへメソッドを実装したうえで、**既存と同じ流儀でこのファサードにも
    フラットな委譲メソッドを追加する**（対称性を崩さない。サービス層がフラット契約に依存して
    いる以上、ここへの追加は重複ではなく契約の一部）。

    書き込みメソッドはcommitしない。呼び出し側（サービス層）が操作のまとまりごとに
    `commit()`を呼ぶ（モジュールdocstringの規約参照）。
    """

    def __init__(self, session: AsyncSession):
        self._session = session
        self.raw_osm = RawOsmRepository(session)
        self.graph = DerivedGraphRepository(session)
        self.attributes = AttributeRepository(session)
        self.tile_query = RoadSurfaceTileQuery(session)

    async def commit(self) -> None:
        """ここまでの書き込みを確定する。4リポジトリは同一セッションを共有するため、
        どのリポジトリ経由の変更もまとめて確定される。"""
        await self._session.commit()

    # --- 生OSM層・タイルマーカー（RawOsmRepository） ---

    async def save_raw_ways(self, way_specs: list[WaySpec], node_coords: dict[int, tuple[float, float]]) -> None:
        await self.raw_osm.save_raw_ways(way_specs, node_coords)

    async def get_way_specs_with_closure(
        self, bbox: BoundingBox
    ) -> tuple[list[WaySpec], dict[int, tuple[float, float]], set[int]]:
        return await self.raw_osm.get_way_specs_with_closure(bbox)

    async def is_tile_cached(self, zoom: int, x: int, y: int) -> bool:
        return await self.raw_osm.is_tile_cached(zoom, x, y)

    async def mark_tile_cached(self, zoom: int, x: int, y: int) -> None:
        await self.raw_osm.mark_tile_cached(zoom, x, y)

    # --- 派生グラフ（DerivedGraphRepository） ---

    async def get_graph_in_bbox(self, bbox: BoundingBox) -> RoadGraph | None:
        return await self.graph.get_graph_in_bbox(bbox)

    async def is_split_up_to_date(self, bbox: BoundingBox) -> bool:
        return await self.graph.is_split_up_to_date(bbox)

    async def save_graph(self, graph: RoadGraph, way_ids_to_replace: set[int] | None = None) -> None:
        await self.graph.save_graph(graph, way_ids_to_replace=way_ids_to_replace)

    # --- Road Attribute（AttributeRepository） ---

    async def get_elevation_attributes(self, edge_ids: list[str]) -> dict[str, ElevationAttribute]:
        return await self.attributes.get_elevation_attributes(edge_ids)

    async def save_elevation_attributes(self, attributes: list[ElevationAttribute]) -> None:
        await self.attributes.save_elevation_attributes(attributes)

    async def get_surface_attributes(self, edge_ids: list[str]) -> dict[str, str | None]:
        return await self.attributes.get_surface_attributes(edge_ids)

    async def get_nearest_surface_tags(
        self, points: list[tuple[float, float]], max_distance_m: float = SURFACE_MATCH_MAX_DISTANCE_M
    ) -> list[str | None]:
        return await self.attributes.get_nearest_surface_tags(points, max_distance_m=max_distance_m)

    async def get_stop_poi_counts(
        self, edge_ids: list[str], max_distance_m: float = STOP_POI_MATCH_MAX_DISTANCE_M
    ) -> dict[str, int]:
        return await self.attributes.get_stop_poi_counts(edge_ids, max_distance_m=max_distance_m)

    async def get_nearest_stop_poi_counts(
        self, points: list[tuple[float, float]], max_distance_m: float = STOP_POI_MATCH_MAX_DISTANCE_M
    ) -> list[int]:
        return await self.attributes.get_nearest_stop_poi_counts(points, max_distance_m=max_distance_m)

    # --- 表示用MVT（RoadSurfaceTileQuery） ---

    async def get_road_surface_tile_mvt(
        self, z: int, x: int, y: int, bbox: BoundingBox, coverage_tile: tuple[int, int, int]
    ) -> bytes | None:
        return await self.tile_query.get_road_surface_tile_mvt(z, x, y, bbox, coverage_tile)
