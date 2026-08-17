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
import logging
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone

import shapely
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import LineString, Point
from sqlalchemy import BigInteger, Boolean, Float, Text, any_, bindparam, cast, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.domain.attributes import ElevationAttribute
from app.domain.graph import DirectedEdge, Node, RoadGraph, WaySpec
from app.domain.region import BoundingBox
from app.domain.accident import ACCIDENT_FATAL_WEIGHT, ACCIDENT_MATCH_MAX_DISTANCE_M
from app.domain.designation import TRAFFIC_STRESS_DESIGNATION_KINDS
from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS, SURFACE_MATCH_MAX_DISTANCE_M
from app.domain.traffic import (
    INTERSECTION_DEGREE_THRESHOLD,
    INTERSECTION_MATCH_MAX_DISTANCE_M,
    STOP_POI_MATCH_MAX_DISTANCE_M,
)
from app.infrastructure.vector_tile import (
    ROAD_SURFACE_LAYER_NAME,
    STOP_POI_LAYER_NAME,
    TILE_EXTENT,
)
from app.infrastructure.road_graph_models import (
    Base,
    ElevationAttributeRow,
    OsmRawNodeRow,
    OsmRawWayRow,
    RoadEdgeRow,
    RoadGraphTileRow,
    RoadNodeRow,
)

logger = logging.getLogger("app.infrastructure.road_graph_repository")

CACHED_GRAPH_VERSION = "cached"

# 近傍Way探索範囲(extent)の上限マージン（改善計画T69）。bboxをかすめる1本の長大way
# （河川沿いサイクリングロード・幹線等で数十km）があると、主対象Way全体のextentが
# その全長へ広がり、そこに交差する全way・全nodeをロードしてしまう
# （最悪ケースでメモリ・転送量・build_road_graph計算量が数十倍に膨らむ）。
# extentを要求bboxからこのマージン分だけ拡張した範囲へクランプする（案a、実装最小）。
# クランプ幅を超えて伸びるwayの端の交差点は「そのwayが主対象になる別リクエストで更新される」
# 既存の結果整合性の考え方（本クラスdocstringの`get_way_specs_with_closure`該当節参照）に乗せる。
NEIGHBOR_EXTENT_MAX_MARGIN_M = 10_000.0

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
# - bicycle_infra: domain/traffic.py（classify_bicycle_infrastructure）と1:1対応するCASE式。
#   SQLにPythonを呼び出す手段が無いためやむを得ず判定ロジックを2箇所持つが、
#   test_road_graph_repository.pyの整合性テストで同じ入力に対し常に同じ出力になることを
#   担保する。
# - traffic_stress（交通ストレス、1-5）は改善計画（交通ストレスレシピ外出し基盤）以降、
#   ここでは**計算済みの最終値を焼かない**。タイルは全ユーザー共有でキャッシュされる
#   （Cache-Control: max-age=3600＋ディスクキャッシュ）ため、最終値をSQLへ焼き込むと
#   判定レシピ（highway別基準値・cycleway/maxspeed/lanes/指定路線の補正）を変えるたびに
#   世界中のタイルキャッシュを作り直す必要が生じる。代わりに材料タグ
#   （cycleway_class/maxspeed_kmh/lanes_count/motor_vehicle_no、highwayは既存プロパティを
#   流用）だけを焼き込み、最終値の計算はフロントエンド側
#   （frontend/src/components/Map/trafficStressExpression.ts、MapLibre expression）と
#   ルート採点（domain/traffic.py: traffic_stress_breakdown）がそれぞれ行う。両者は
#   domain/traffic.py: TrafficStressRecipeという共通のレシピ定義に対応させ、
#   trafficStressExpression.test.tsで整合性を検証する（このSQL側の整合性テストは
#   材料タグの焼き込みが正しいことだけを検証すればよくなった）。
#   maxspeed/lanesの数値パースは、Pythonのparse_maxspeed/parse_lanes（int(float(x))で
#   小数を切り捨て）と合わせるためtrunc()を使い、非数値文字列（"30 mph"等）は正規表現で
#   弾いてunknown安全にする。
# - safety（安全度、1-4、改善計画: 安全度レシピ）も同じ理由で最終値を焼かず材料タグのみ
#   焼き込む。cycleway_class/maxspeed_kmh/lanes_count/motor_vehicle_no/designationは
#   交通ストレスと共有し、litのみ新規追加（tunnelは上のtunnelプロパティを再利用。shoulderは
#   改善計画T102実測0.0%の死に補正のためT122で撤去した）。フロント側はsafetyExpression.ts、
#   採点側はdomain/safety.py: safety_breakdownがdomain/safety.py: SafetyRecipeという
#   共通のレシピ定義に対応させて計算する。
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
                        -- クリック時の交通ストレス内訳表示（改善計画T90）が、ポップアップに
                        -- 出た値と同じ行を曖昧さ無く引き直すための識別子。get_nearest_way_tags
                        -- の空間マッチ(半径内最近傍)だと交差点付近で別の道路を拾いうる
                        -- （実機確認で判明）ため、フィーチャーが指す行そのものをosm_way_id
                        -- 完全一致で引く（get_way_tags_by_osm_way_id）。
                        w.osm_way_id AS osm_way_id,
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
                        -- 交通ストレスの材料タグ（最終値はフロント/Pythonが計算、上のコメント参照）。
                        CASE
                            WHEN 'track' = ANY(cw.values) THEN 'track'
                            WHEN 'lane' = ANY(cw.values) THEN 'lane'
                            WHEN cw.values && ARRAY['shared_lane', 'share_busway'] THEN 'shared'
                        END AS cycleway_class,
                        -- ST_AsMVTはnumeric型を認識せずtextへフォールバックする（実機確認で
                        -- 判明。フロントのMapLibre expressionが数値比較できなくなる）ため、
                        -- integerへキャストしてから焼き込む。0以下はPythonのparse_maxspeed/
                        -- parse_lanes（`value if value > 0 else None`）と同じくunknown扱いにし
                        -- キー自体を省略する（"maxspeed=0"のような無効タグでフロント/採点側の
                        -- 補正が誤発火しないようにする。改善計画: 交通ストレスレシピ外出し基盤
                        -- のコードレビューで発覚）。
                        CASE
                            WHEN btrim(w.tags->>'maxspeed') ~ '^[0-9]+(\\.[0-9]+)?$'
                                 AND trunc(btrim(w.tags->>'maxspeed')::numeric) > 0
                                THEN trunc(btrim(w.tags->>'maxspeed')::numeric)::integer
                        END AS maxspeed_kmh,
                        CASE
                            WHEN btrim(w.tags->>'lanes') ~ '^[0-9]+(\\.[0-9]+)?$'
                                 AND trunc(btrim(w.tags->>'lanes')::numeric) > 0
                                THEN trunc(btrim(w.tags->>'lanes')::numeric)::integer
                        END AS lanes_count,
                        CASE WHEN lower(btrim(w.tags->>'motor_vehicle')) = 'no' THEN true END AS motor_vehicle_no,
                        -- 安全度の材料タグ（改善計画: 安全度レシピ）。tunnelは既存プロパティ
                        -- （上のtunnel、表示用と兼用）をそのまま再利用し、litのみ新規抽出する
                        -- （motor_vehicle_noと同じCASE式パターン。shoulderは改善計画T102実測
                        -- 0.0%の死に補正のためT122で撤去した）。
                        CASE WHEN lower(btrim(w.tags->>'lit')) = 'yes' THEN true END AS lit,
                        CASE
                            WHEN COALESCE(d.is_ert, false) AND COALESCE(d.is_cl, false) THEN 'both'
                            WHEN d.is_ert THEN 'emergency_transport'
                            WHEN d.is_cl THEN 'critical_logistics'
                        END AS designation
                    FROM osm_raw_ways w
                    CROSS JOIN LATERAL (
                        SELECT ARRAY[
                            lower(btrim(w.tags->>'cycleway')),
                            lower(btrim(w.tags->>'cycleway:left')),
                            lower(btrim(w.tags->>'cycleway:right')),
                            lower(btrim(w.tags->>'cycleway:both'))
                        ] AS values
                    ) cw
                    LEFT JOIN (
                        -- 指定路線コンフレーション機構（外部静的データソース T51）。
                        -- designation_attributesはmatch_designations.pyの事前計算バッチが埋める。
                        -- 改善計画T74: キーがosm_way_idになったため、road_edges経由の間接JOIN
                        -- （旧: designation_attributes.edge_id→road_edges.edge_id→osm_way_id）が
                        -- 不要になった。designation_attributes自体を直接osm_way_id単位へ
                        -- 事前集約する（改善計画T65の17倍高速化の知見はそのまま活きる。
                        -- osm_way_id 1件に対しkindは高々2件のためbool_or集約コストは軽微）。
                        SELECT
                            osm_way_id,
                            bool_or(kind = 'emergency_transport') AS is_ert,
                            bool_or(kind = 'critical_logistics') AS is_cl
                        FROM designation_attributes
                        GROUP BY osm_way_id
                    ) d ON d.osm_way_id = w.osm_way_id
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
    )
)


# 改善計画T54（既取込データの可視化漏れ解消）: 停止要因POI（osm_raw_pois）を1タイルへ
# 焼き込む。_ROAD_SURFACE_TILE_MVT_SQLと同じカバレッジ判定（road_graph_tilesのz12祖先
# タイルマーク）を再利用しつつ、対象データソースが別テーブルの点データのため道路（way）とは
# 独立のクエリにする。osm_raw_pois内のkindタグをそのまま焼き込むだけ（GiST索引を使う
# ST_Intersects、_STOP_POI_COUNTS_SQLと同じテーブル）。
#
# T54では交差点密度（次数3以上のroad_node）レイヤーも同じタイルへCOALESCE+bytea結合（||）で
# 焼き込んでいたが、T96でフロントの地図表示から撤去（道路網を見れば概ね自明という判断）され
# 参照が無くなったため、T97でこちらの配信自体も削除した（ルーティング材料の
# intersection_weightは`_INTERSECTION_COUNTS_SQL`が引き続き独立に計算する）。
_POI_TILE_MVT_SQL = text(
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
            SELECT ST_AsMVT(mvt.*, :stop_poi_layer, :extent, 'geom') FROM (
                SELECT
                    ST_AsMVTGeom(
                        ST_Transform(p.geom, 3857), ST_TileEnvelope(:z, :x, :y), :extent, 256, true
                    ) AS geom,
                    p.kind AS kind
                FROM osm_raw_pois p
                WHERE ST_Intersects(p.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
            ) mvt
            WHERE mvt.geom IS NOT NULL
        ) END AS tile
    FROM coverage
    """
).bindparams(
    bindparam("stop_poi_layer", value=STOP_POI_LAYER_NAME, type_=Text()),
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
# 改善計画T64: JOIN条件がST_DWithin(geography)単体だとGiST索引を使わずJoin Filter
# （全組み合わせ評価）に落ちる（_INTERSECTION_COUNTS_SQLのコメント・T64実測参照）。
# `&&`（geometry型のバウンディングボックス演算子）を前置してGiST索引を先に使わせてから
# ST_DWithinで精密判定する。
_STOP_POI_COUNTS_SQL = text(
    """
    SELECT e.edge_id, COUNT(p.osm_node_id) AS stop_count
    FROM road_edges e
    LEFT JOIN osm_raw_pois p
        ON p.geom && ST_Expand(e.geom, :max_distance_deg)
       AND ST_DWithin(p.geom::geography, e.geom::geography, :max_distance_m)
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
            ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS geom,
            ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography AS geog
        FROM unnest(CAST(:lats AS float8[]), CAST(:lons AS float8[])) WITH ORDINALITY AS t(lat, lon, ord)
    )
    SELECT pts.ord, COUNT(p.osm_node_id) AS stop_count
    FROM pts
    LEFT JOIN osm_raw_pois p
        ON p.geom && ST_Expand(pts.geom, :max_distance_deg)
       AND ST_DWithin(p.geom::geography, pts.geog, :max_distance_m)
    GROUP BY pts.ord
    ORDER BY pts.ord
    """
).bindparams(
    bindparam("lats", type_=ARRAY(Float())),
    bindparam("lons", type_=ARRAY(Float())),
)

# 外部静的データソース T50残作業（事故密度の評価組み込み）。_STOP_POI_COUNTS_SQLと同じ
# 「edge_idそれぞれの距離内件数」パターンだが、対象テーブルがaccident_pointsで
# bicycle_only（当事者に自転車を含む事故のみに絞るか）の切替を追加している。
# 改善計画T64: _STOP_POI_COUNTS_SQLと同じ理由で`&&`を前置する。
# 改善計画（事故密度の精度改善）: 単純COUNTではなく死亡事故を`ACCIDENT_FATAL_WEIGHT`件分と
# みなすSUMへ変更（domain/accident.py参照）。戻り値がint→floatになる。LEFT JOINで一致が
# 無いedgeはa.accident_idもa.fatalもNULLになるため、CASE式の先頭でa.accident_id IS NULLを
# 明示的に0扱いする（無いとNULLはWHEN a.fatal THENの条件が偽になりELSE 1へ落ち、
# 事故0件のedgeに架空の1件が計上されてしまう）。
_ACCIDENT_COUNTS_SQL = text(
    """
    SELECT e.edge_id,
           SUM(CASE WHEN a.accident_id IS NULL THEN 0 WHEN a.fatal THEN :fatal_weight ELSE 1 END) AS accident_count
    FROM road_edges e
    LEFT JOIN accident_points a
        ON a.geom && ST_Expand(e.geom, :max_distance_deg)
       AND ST_DWithin(a.geom::geography, e.geom::geography, :max_distance_m)
       AND (:bicycle_only = false OR a.involves_bicycle)
    WHERE e.edge_id = ANY(CAST(:edge_ids AS text[]))
    GROUP BY e.edge_id
    """
).bindparams(
    bindparam("bicycle_only", type_=Boolean()),
    bindparam("fatal_weight", value=ACCIDENT_FATAL_WEIGHT, type_=Float()),
)

# ORSエンジン用（サンプル点ごとの近傍件数）。_NEAREST_STOP_POI_COUNTS_SQLと同じ構造。
_NEAREST_ACCIDENT_COUNTS_SQL = text(
    """
    WITH pts AS (
        SELECT
            ord,
            ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS geom,
            ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography AS geog
        FROM unnest(CAST(:lats AS float8[]), CAST(:lons AS float8[])) WITH ORDINALITY AS t(lat, lon, ord)
    )
    SELECT pts.ord,
           SUM(CASE WHEN a.accident_id IS NULL THEN 0 WHEN a.fatal THEN :fatal_weight ELSE 1 END) AS accident_count
    FROM pts
    LEFT JOIN accident_points a
        ON a.geom && ST_Expand(pts.geom, :max_distance_deg)
       AND ST_DWithin(a.geom::geography, pts.geog, :max_distance_m)
       AND (:bicycle_only = false OR a.involves_bicycle)
    GROUP BY pts.ord
    ORDER BY pts.ord
    """
).bindparams(
    bindparam("lats", type_=ARRAY(Float())),
    bindparam("lons", type_=ARRAY(Float())),
    bindparam("bicycle_only", type_=Boolean()),
    bindparam("fatal_weight", value=ACCIDENT_FATAL_WEIGHT, type_=Float()),
)

# 指定路線コンフレーション機構（外部静的データソース T51）。designation_attributesは
# match_designations.pyの事前計算バッチが埋める（クエリ時にはバッファ交差計算をしない）。
# サンプル点版は改善計画T76で_NEAREST_WAY_TAGS_SQLへ統合し、専用クエリは廃止した
# （同一サンプル点集合に対する3本目の独立KNNラウンドトリップだったため。詳細は
# _NEAREST_WAY_TAGS_SQLのコメント参照）。
#
# 改善計画T74: designation_attributesはosm_way_idキーへ変更したが、呼び出し元
# （get_designated_edge_ids）は構築済みgraph（graph.edges.keys()、road_graph_engine.py）の
# edge_idを受け取りedge_id集合を返す必要があるため、この経路だけはroad_edgesを経由して
# edge_id→osm_way_idへマッピングしてからJOINする。呼び出し時点でgraphは既に構築済み
# （road_edgesの遅延構築は完了済み）のため、この間接JOINはT74の「遅延構築依存」問題の
# 対象外（MVT表示のように「ルート生成前に見えるか」が問題になる経路ではない）。
#
# DISTINCTは呼び出し側（get_designated_edge_ids）のset()化と二重に見えるが、1エッジが
# 複数kindに該当する場合（N10・N12両方等）に重複行がそのままネットワークへ乗るのを防ぐ
# 転送量削減が目的のため意図的に残す。
_DESIGNATED_EDGE_IDS_SQL = text(
    "SELECT DISTINCT e.edge_id FROM road_edges e "
    "JOIN designation_attributes da ON da.osm_way_id = e.osm_way_id "
    "WHERE e.edge_id = ANY(CAST(:edge_ids AS text[])) AND da.kind = ANY(:kinds)"
).bindparams(bindparam("kinds", type_=ARRAY(Text())))

# 事故データの収録年数（accident_import_runsの成功run数、年重複なしのdistinct件数）。
# distance_weighted_accident_density（domain/accident.py）の「件/(km・年)」正規化に使う。
# ハードコード定数にせず動的取得することで、将来の年次追加取込で自動的に正しくなる。
_ACCIDENT_YEARS_COVERED_SQL = text(
    "SELECT COUNT(DISTINCT occurred_year) FROM accident_import_runs WHERE status = 'succeeded'"
)

# 交通ストレスの区間別判定内訳表示（改善計画T90）。get_way_tags_by_osm_way_idが使う。
# _NEAREST_WAY_TAGS_SQLと違い空間マッチをしない完全一致1行取得のため、KNNより単純。
_WAY_TAGS_BY_OSM_WAY_ID_SQL = text(
    """
    SELECT
        w.highway,
        w.tags,
        EXISTS(
            SELECT 1 FROM designation_attributes d
            WHERE d.osm_way_id = w.osm_way_id AND d.kind = ANY(:kinds)
        ) AS is_designated
    FROM osm_raw_ways w
    WHERE w.osm_way_id = :osm_way_id
    """
).bindparams(bindparam("kinds", type_=ARRAY(Text())))

# 静的道路属性P1残り（交通ストレス・自転車インフラの評価組み込み）。_NEAREST_SURFACE_SQLと
# 同じ「最近傍1件」パターンだが、surfaceに加えhighway・tags(jsonb)も返す
# （domain/traffic.py: traffic_stress_level/classify_bicycle_infrastructureの入力）。
# 改善計画T76: is_designated（外部静的データソース T51、KSJ N10/N12該当）もここへ統合する。
# 以前はget_nearest_designated_flagsが同一サンプル点集合に対して独立のLATERAL KNN
# （WITH pts〜LEFT JOIN LATERAL road_edgesの骨格ごとコピー）を3本目のラウンドトリップとして
# 実行しており、並行道路付近でhighway/tagsとis_designatedが別のedge由来になる不整合の
# 可能性もあった。nearest.osm_way_idを1回のKNNで求め、designation_attributesへのEXISTSを
# 同じCASE式（ST_DWithinゲート）に同居させることでクエリ・ラウンドトリップとも1本化する。
# 改善計画T74: designation_attributesがosm_way_idキーになったため、EXISTS判定も
# nearest.osm_way_id（既にKNNで取得済み、道路種別tags取得のosm_raw_ways JOINと同じキー）で
# 直接判定する。edge_idを経由する必要が無くなった。
_NEAREST_WAY_TAGS_SQL = text(
    """
    WITH pts AS (
        SELECT
            ord,
            ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS geom,
            ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography AS geog
        FROM unnest(CAST(:lats AS float8[]), CAST(:lons AS float8[])) WITH ORDINALITY AS t(lat, lon, ord)
    )
    SELECT pts.ord,
           CASE WHEN ST_DWithin(nearest.geom::geography, pts.geog, :max_distance_m) THEN w.highway END AS highway,
           CASE WHEN ST_DWithin(nearest.geom::geography, pts.geog, :max_distance_m) THEN w.tags END AS tags,
           CASE WHEN ST_DWithin(nearest.geom::geography, pts.geog, :max_distance_m)
                THEN EXISTS(
                    SELECT 1 FROM designation_attributes da
                    WHERE da.osm_way_id = nearest.osm_way_id AND da.kind = ANY(:kinds)
                )
                ELSE false
           END AS is_designated
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
    bindparam("kinds", type_=ARRAY(Text())),
)

def _restore_ordinality_order(rows, count: int, default, value_fn=lambda row: row[1]):
    """`UNNEST(...) WITH ORDINALITY`で1始まりのord列を振ったSQL結果を、元の入力順・
    入力件数のリストへ復元する（改善計画T81）。

    「ordは1始まり・欠落（該当0件/範囲外）は既定値」という暗黙規約が、
    get_nearest_surface_tags等6メソッドへ同型の`by_ord = {...}; return [by_ord.get(i+1,
    default) for ...]`イディオムとして分散していた。SQL側変更時のオフバイワン
    （全属性が隣のサンプル点の値になる）を防ぐため1箇所へ集約する。

    `rows`の各行は先頭要素がord、`value_fn`がその行から値を組み立てる（既定は2列目を
    そのまま使う。3列以上をタプルへ束ねる場合はvalue_fnを渡す）。
    """
    by_ord = {row[0]: value_fn(row) for row in rows}
    return [by_ord.get(i + 1, default) for i in range(count)]


def _meters_to_bbox_margin_deg(max_distance_m: float) -> float:
    """`&&`によるバウンディングボックス事前フィルタ用に、距離(m)を安全側の緯度経度差(度)へ
    変換する。1度=100,000mという（実際の111,000mより小さい＝度換算では大きい）保守的な
    換算を使い、経度方向の圧縮（高緯度ほど同じ距離が大きい経度差になる）を考慮しても
    日本の緯度帯（〜46度）で確実に対象を包含する余裕を持たせる（cos(46°)≈0.69のため
    最大でも約1.45倍の余裕があれば足りるところ、100,000/111,320≈0.9倍の余裕では
    不足するため、さらに絞らず全体に1/70,000という大きめの換算係数を使う）。"""
    return max_distance_m / 70_000.0


# 静的道路属性P1残り（intersectionDensity）。「次数3以上のNode」を交差点とみなし、
# road_edgesのfrom/to隣接ノード集合から次数を導出する（road_nodes自体は次数を保持していない。
# build_road_graphのNode化条件は「Wayの端点、または複数Wayに共有されるNode」であり、
# 次数2の単純な通過点もNode化されうるため、次数はここで都度計算する必要がある）。
# edge_idで指定範囲を絞ってから集計するため（road_graphエンジンは既に取得済みの
# ローカルグラフのedge_id全量を渡す）、DB全体のroad_edgesを走査しない。
#
# road_nodesとのJOINは`ST_DWithin(geom::geography, ...)`だけに頼らず、必ず`&&`
# （バウンディングボックス重なり、GiST索引を素直に使う）を先に効かせてからST_DWithinで
# 精密に絞り込む。`geom::geography`へキャストしたST_DWithinは本環境の実測でGiST索引を
# 使わない全件Seq Scan + Nested Loopになり（road_nodes 25,608件で単純な1点問い合わせが
# 132msかかることをEXPLAIN ANALYZEで確認）、複数点をまとめて処理すると数秒〜数十秒に
# 劣化する。`&&`はgeometry型の演算子で確実にインデックスを使うため（_NEAREST_SURFACE_SQL等の
# 既存クエリも`ORDER BY geom <-> geom`のKNN索引か`geom && bbox`のいずれかで索引を使わせており、
# ST_DWithin(geography)単体には頼っていない）、まずこれで候補を数件程度まで絞ってから
# ST_DWithinで正確な距離判定をする。
#
# `degrees`は独立したJOIN句として1回だけ参照する（`local_edges`側のJOIN ON句の中へ
# `rn.node_id IN (SELECT ... FROM degrees)`のようにサブクエリとして埋め込まない）。
# JOIN ONの内側に置くとPostgresがdegrees（内部でlocal_edges全件を再スキャンする集計）を
# 外側local_edgesの行ごとに再実行するNested Loopを選び、O(件数^2)に劣化することを
# 実測で確認した（2000件で15秒のstatement_timeoutに到達）。
_INTERSECTION_COUNTS_SQL = text(
    """
    WITH local_edges AS (
        SELECT edge_id, from_node_id, to_node_id, geom
        FROM road_edges
        WHERE edge_id = ANY(CAST(:edge_ids AS text[]))
    ),
    endpoints AS (
        SELECT from_node_id AS node_id, to_node_id AS neighbor_id FROM local_edges
        UNION
        SELECT to_node_id AS node_id, from_node_id AS neighbor_id FROM local_edges
    ),
    degrees AS (
        SELECT node_id
        FROM endpoints
        GROUP BY node_id
        HAVING COUNT(DISTINCT neighbor_id) >= :degree_threshold
    )
    SELECT le.edge_id, COUNT(d.node_id) AS intersection_count
    FROM local_edges le
    LEFT JOIN road_nodes rn
        ON rn.geom && ST_Expand(le.geom, :max_distance_deg)
        AND ST_DWithin(rn.geom::geography, le.geom::geography, :max_distance_m)
    LEFT JOIN degrees d ON d.node_id = rn.node_id
    GROUP BY le.edge_id
    """
)

# ORSエンジン用（サンプル点ごとの近傍交差点件数）。_INTERSECTION_COUNTS_SQLと違い、edge_idの
# 一覧が無い（ルートgeometry上の任意サンプル点）ため、まず各点の近傍road_node候補を
# 同じ`&&`先行フィルタ+ST_DWithinパターンで求め、その少数の候補nodeについてのみ
# from_node_id/to_node_id（btree索引）で次数を計算する。以前は「サンプル点集合の外接矩形を
# 広げた範囲のroad_edges全件から次数を先に計算し、その結果へ点をJOINする」実装だったが、
# (1)8方位ぶんの点をまとめて1回のクエリに渡すため外接矩形がループ全体（最大約60km径）に
# 及ぶ、(2)次数計算結果へのJOINがST_DWithin(geography)単体では索引を使わない総当たりになる
# （_INTERSECTION_COUNTS_SQLのコメント参照）、の二重の理由で実データ大規模時に深刻に
# 遅くなることを実測（EXPLAIN ANALYZEで数秒〜数十秒、本番規模ではさらに悪化する見込み）した
# ため、点ごとに閉じた候補探索へ変更した。
_NEAREST_INTERSECTION_COUNTS_SQL = text(
    """
    WITH pts AS (
        SELECT
            ord,
            ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS geom,
            ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography AS geog
        FROM unnest(CAST(:lats AS float8[]), CAST(:lons AS float8[])) WITH ORDINALITY AS t(lat, lon, ord)
    ),
    nearby_nodes AS (
        SELECT pts.ord, rn.node_id
        FROM pts
        JOIN road_nodes rn
            ON rn.geom && ST_Expand(pts.geom, :max_distance_deg)
            AND ST_DWithin(rn.geom::geography, pts.geog, :max_distance_m)
    ),
    candidate_nodes AS (
        SELECT DISTINCT node_id FROM nearby_nodes
    ),
    endpoints AS (
        SELECT e.from_node_id AS node_id, e.to_node_id AS neighbor_id
        FROM road_edges e
        WHERE e.from_node_id IN (SELECT node_id FROM candidate_nodes)
        UNION
        SELECT e.to_node_id AS node_id, e.from_node_id AS neighbor_id
        FROM road_edges e
        WHERE e.to_node_id IN (SELECT node_id FROM candidate_nodes)
    ),
    degrees AS (
        SELECT node_id
        FROM endpoints
        GROUP BY node_id
        HAVING COUNT(DISTINCT neighbor_id) >= :degree_threshold
    )
    SELECT nn.ord, COUNT(*) AS intersection_count
    FROM nearby_nodes nn
    JOIN degrees d ON d.node_id = nn.node_id
    GROUP BY nn.ord
    ORDER BY nn.ord
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

        `way_ids_to_replace`を指定した場合、それらのosm_way_idを持つ既存Edge行のうち
        「今回のgraphに同じedge_idで含まれないもの」だけを削除してから`graph`内の該当Edgeを
        UPSERTする（改善計画T66: 全削除→無条件再挿入だと、分割結果が前回と変わらない
        大多数のケースでも同じedge_idの行がDELETE→INSERTを経由してしまい、
        `ON DELETE CASCADE`のEdge派生属性（elevation_attributes等）が巻き添えで
        消える。edge_idは決定論的なため、分割結果が変わらなければ削除自体が不要。
        なおdesignation_attributesは改善計画T74でosm_raw_ways基準のWay派生に変更したため、
        Edgeの再splitでは影響を受けない）。
        `build_road_graph`は渡されたWay集合全体から交差点を再計算するため、
        Wayの分割結果が実際に変わっていた場合は、古い分割によるEdge行（新graphに
        存在しないedge_id）を削除して孤立させない（タイル境界依存の分割不一致問題への
        対応、本ファイル冒頭のdocstring参照）。`way_ids_to_replace`外のosm_way_idを持つEdge
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

        if way_ids_to_replace:
            new_edge_ids = {row["edge_id"] for row in edge_rows}
            for id_chunk in _chunked(sorted(way_ids_to_replace), _ID_CHUNK_SIZE):
                delete_stmt = delete(RoadEdgeRow).where(RoadEdgeRow.osm_way_id.in_(id_chunk))
                # 今回も同じedge_idで再挿入される行はDELETE対象から除外する（上記docstring
                # 参照）。new_edge_idsが空（対象way群がEdgeを1件も生成しなかった）場合は
                # NOT INの右辺が空集合になり全削除相当のままで問題ない。
                if new_edge_ids:
                    delete_stmt = delete_stmt.where(RoadEdgeRow.edge_id.not_in(new_edge_ids))
                await self._session.execute(delete_stmt)
                await self._session.execute(
                    update(OsmRawWayRow).where(OsmRawWayRow.osm_way_id.in_(id_chunk)).values(split_at=now)
                )

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
        2. 近傍Way: 主対象Way全体のextent（全長分の外接矩形、bbox外の部分も含む。
           NEIGHBOR_EXTENT_MAX_MARGIN_M分だけ拡張した要求bboxへクランプ済み、
           改善計画T69）と交差するWay。「主対象とノードを共有するWay」の厳密な
           上位集合であり、余分に含まれるWayは交差点判定の文脈情報が増えるだけで
           正しさを損なわない（近傍Wayはこの呼び出しでは永続化しないため）

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

        # 主対象Wayの全長分のextent（1回の集約クエリでbbox外へのはみ出し範囲を得る）。
        # 改善計画T69: extentを要求bboxをNEIGHBOR_EXTENT_MAX_MARGIN_M分だけ拡張した範囲へ
        # ST_Intersectionでクランプする。主対象Wayは定義上すべて要求bboxと交差するため、
        # 拡張後のbboxとの交差は常に非空になる（クランプが空集合を返すことはない）。
        extent_row = (
            await self._session.execute(
                text(
                    "SELECT ST_XMin(clamped) AS xmin, ST_YMin(clamped) AS ymin, "
                    "ST_XMax(clamped) AS xmax, ST_YMax(clamped) AS ymax, "
                    "ST_XMin(raw) AS raw_xmin, ST_YMin(raw) AS raw_ymin, "
                    "ST_XMax(raw) AS raw_xmax, ST_YMax(raw) AS raw_ymax "
                    "FROM (SELECT "
                    "ST_SetSRID(ST_Extent(geom)::geometry, 4326) AS raw, "
                    "ST_Intersection("
                    "ST_SetSRID(ST_Extent(geom)::geometry, 4326), "
                    "ST_Envelope(ST_Buffer(ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)::geography, "
                    ":margin_m)::geometry)"
                    ") AS clamped "
                    "FROM osm_raw_ways "
                    "WHERE geom IS NOT NULL "
                    "AND ST_Intersects(geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))) s"
                ),
                {**bbox_params, "margin_m": NEIGHBOR_EXTENT_MAX_MARGIN_M},
            )
        ).one()

        if (
            extent_row.raw_xmin != extent_row.xmin
            or extent_row.raw_ymin != extent_row.ymin
            or extent_row.raw_xmax != extent_row.xmax
            or extent_row.raw_ymax != extent_row.ymax
        ):
            logger.warning(
                "近傍Way探索のextentがマージン上限を超えたためクランプしました "
                "raw=(%.2f,%.2f,%.2f,%.2f) clamped=(%.2f,%.2f,%.2f,%.2f) margin_m=%.0f",
                extent_row.raw_xmin, extent_row.raw_ymin, extent_row.raw_xmax, extent_row.raw_ymax,
                extent_row.xmin, extent_row.ymin, extent_row.xmax, extent_row.ymax,
                NEIGHBOR_EXTENT_MAX_MARGIN_M,
            )

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
    """地域路面レイヤー・停止要因POI/交差点密度レイヤー（RegionService）表示用のMVT生成。
    読み取り専用でcommit対象の書き込みは無い。"""

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

    async def get_poi_tile_mvt(
        self, z: int, x: int, y: int, bbox: BoundingBox, coverage_tile: tuple[int, int, int]
    ) -> bytes | None:
        """停止要因POIレイヤー用のMVTタイル1枚を、PostGIS側（ST_AsMVT）で丸ごと生成して
        返す（改善計画T54、T97で交差点密度レイヤーの配信を撤去）。get_road_surface_tile_mvtと
        同じ契約（カバレッジ外はNone、カバレッジ内で対象0件は空バイト列）。クエリの設計意図は
        _POI_TILE_MVT_SQLのコメント参照。
        """
        coverage_zoom, coverage_x, coverage_y = coverage_tile
        result = await self._session.execute(
            _POI_TILE_MVT_SQL,
            {
                "coverage_zoom": coverage_zoom,
                "coverage_x": coverage_x,
                "coverage_y": coverage_y,
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
        return _restore_ordinality_order(result.all(), len(points), None)

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
        max_distance_deg = _meters_to_bbox_margin_deg(max_distance_m)
        for id_chunk in _chunked(edge_ids, 50_000):
            rows = await self._session.execute(
                _STOP_POI_COUNTS_SQL,
                {"edge_ids": id_chunk, "max_distance_m": max_distance_m, "max_distance_deg": max_distance_deg},
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
            _NEAREST_STOP_POI_COUNTS_SQL,
            {
                "lats": lats, "lons": lons, "max_distance_m": max_distance_m,
                "max_distance_deg": _meters_to_bbox_margin_deg(max_distance_m),
            },
        )
        return _restore_ordinality_order(result.all(), len(points), 0)

    async def get_way_tags(self, edge_ids: list[str]) -> dict[str, dict[str, str]]:
        """指定edge_idそれぞれについて、road_edges.osm_way_id経由のosm_raw_ways.tags
        （静的道路属性P0の許可リストタグ）を返す（静的道路属性P1残り、交通ストレス・
        自転車インフラ評価の入力）。get_surface_attributesと同じJOINパターン。

        該当way自体が無い/tagsが空のEdgeは`{}`（highwayはEdge側に既に保持済みのため、
        タグが空でも交通ストレスの基本値は評価できる。domain/evaluation.py:
        compute_edge_cost参照）。「データ未取得（repository未注入）」との区別は
        呼び出し元（本メソッド自体を呼ぶかどうか）で行う。
        """
        if not edge_ids:
            return {}
        result: dict[str, dict[str, str]] = {}
        for id_chunk in _chunked(edge_ids, 50_000):
            stmt = (
                select(RoadEdgeRow.edge_id, OsmRawWayRow.tags)
                .select_from(RoadEdgeRow)
                .outerjoin(OsmRawWayRow, RoadEdgeRow.osm_way_id == OsmRawWayRow.osm_way_id)
                .where(RoadEdgeRow.edge_id == any_(cast(id_chunk, ARRAY(Text))))
            )
            for edge_id, tags in (await self._session.execute(stmt)).all():
                result[edge_id] = tags or {}
        return result

    async def get_way_tags_by_osm_way_id(self, osm_way_id: int) -> tuple[str | None, dict[str, str], bool] | None:
        """osm_way_id完全一致で(highway, tags, is_designated)を返す（改善計画T90）。

        `get_nearest_way_tags`の空間マッチ（半径内最近傍）は、交差点付近など複数の道路が
        近接する場所で、実際にクリックされたMVTフィーチャー（`_ROAD_SURFACE_TILE_MVT_SQL`が
        同じosm_way_idをプロパティとして焼き込み済み）とは別の道路を拾いうることが実機確認で
        判明した（ポップアップの`traffic_stress`表示値と、内訳ボタンで計算した値が食い違う）。
        フィーチャーが指す行そのものをosm_way_idで引き直すことで、この不整合を構造的に防ぐ。

        該当way自体が存在しない（極端な状況、タイル生成後の再取込等）場合はNone。
        """
        result = await self._session.execute(
            _WAY_TAGS_BY_OSM_WAY_ID_SQL,
            {"osm_way_id": osm_way_id, "kinds": sorted(TRAFFIC_STRESS_DESIGNATION_KINDS)},
        )
        row = result.first()
        if row is None:
            return None
        return (row.highway, row.tags or {}, row.is_designated)

    async def get_nearest_way_tags(
        self, points: list[tuple[float, float]], max_distance_m: float = SURFACE_MATCH_MAX_DISTANCE_M
    ) -> list[tuple[str | None, dict[str, str], bool]]:
        """(lat, lon)点列それぞれについて、`max_distance_m`以内の最近傍road_edgeが
        参照するosm_raw_waysの(highway, tags, is_designated)を返す（入力と同じ順序・同じ長さ、
        静的道路属性P1残り＋外部静的データソースT51）。get_nearest_surface_tagsと同じ
        空間マッチ方式で、openrouteserviceエンジンの交通ストレス・自転車インフラ・
        指定路線該当（trafficStress補正）評価の入力になる。

        is_designatedは以前get_nearest_designated_flagsという専用メソッド・専用SQLだったが、
        同一サンプル点集合に対する3本目の独立KNNだったため改善計画T76でここへ統合した
        （_NEAREST_WAY_TAGS_SQLのコメント参照）。
        """
        if not points:
            return []
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        result = await self._session.execute(
            _NEAREST_WAY_TAGS_SQL,
            {
                "lats": lats, "lons": lons, "max_distance_m": max_distance_m,
                "kinds": sorted(TRAFFIC_STRESS_DESIGNATION_KINDS),
            },
        )
        return _restore_ordinality_order(
            result.all(), len(points), (None, {}, False),
            value_fn=lambda row: (row[1], row[2] or {}, row[3]),
        )

    async def get_intersection_counts(
        self, edge_ids: list[str], max_distance_m: float = INTERSECTION_MATCH_MAX_DISTANCE_M
    ) -> dict[str, int]:
        """指定edge_idそれぞれについて、`max_distance_m`以内にある交差点（次数
        `INTERSECTION_DEGREE_THRESHOLD`以上のroad_node）の件数を返す（静的道路属性P1残り、
        intersectionDensity）。road_graphエンジンのcompute_edge_cost（探索コスト自体）で使う。
        get_stop_poi_countsと同じ「edge_idリストを渡して辞書で受け取る」形で、指定edge_idは
        （0件でも）必ず結果に含まれる。

        次数はDB全体ではなく指定edge_ids（呼び出し元が既に取得済みのローカルグラフの
        全edge）に限定して都度計算する（_INTERSECTION_COUNTS_SQL参照。DB全体のroad_edgesを
        毎回集計すると規模に応じて遅くなるため）。
        """
        if not edge_ids:
            return {}
        result: dict[str, int] = {}
        for id_chunk in _chunked(edge_ids, 50_000):
            rows = await self._session.execute(
                _INTERSECTION_COUNTS_SQL,
                {
                    "edge_ids": id_chunk,
                    "max_distance_m": max_distance_m,
                    "max_distance_deg": _meters_to_bbox_margin_deg(max_distance_m),
                    "degree_threshold": INTERSECTION_DEGREE_THRESHOLD,
                },
            )
            for edge_id, intersection_count in rows.all():
                result[edge_id] = intersection_count
        return result

    async def get_nearest_intersection_counts(
        self, points: list[tuple[float, float]], max_distance_m: float = INTERSECTION_MATCH_MAX_DISTANCE_M
    ) -> list[int]:
        """(lat, lon)点列それぞれについて、`max_distance_m`以内にある交差点（次数
        `INTERSECTION_DEGREE_THRESHOLD`以上のroad_node）の件数を返す（入力と同じ順序・
        同じ長さ、静的道路属性P1残り）。get_nearest_stop_poi_countsと同じ考え方で、
        点ごとの近傍road_node候補をGiST索引で求めてから次数を計算する
        （_NEAREST_INTERSECTION_COUNTS_SQL参照）。
        """
        if not points:
            return []
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        result = await self._session.execute(
            _NEAREST_INTERSECTION_COUNTS_SQL,
            {
                "lats": lats,
                "lons": lons,
                "max_distance_m": max_distance_m,
                "max_distance_deg": _meters_to_bbox_margin_deg(max_distance_m),
                "degree_threshold": INTERSECTION_DEGREE_THRESHOLD,
            },
        )
        return _restore_ordinality_order(result.all(), len(points), 0)

    async def get_accident_counts(
        self, edge_ids: list[str], bicycle_only: bool = True, max_distance_m: float = ACCIDENT_MATCH_MAX_DISTANCE_M
    ) -> dict[str, float]:
        """指定edge_idそれぞれについて、`max_distance_m`以内にある事故（accident_points）の
        合計件数（死亡事故は`ACCIDENT_FATAL_WEIGHT`件分の重み付け、domain/accident.py参照）を
        返す（外部静的データソース T50残作業、改善計画: 事故密度の精度改善）。
        `bicycle_only`の既定値は`True`（自転車ルート案内で自動車同士のみの事故まで
        数えるのは実質バグに近いという判断、ユーザー承認済みの既定挙動変更）。
        get_stop_poi_countsと同じ「edge_idリストを渡して辞書で受け取る」形で、
        指定edge_idは（該当事故が0件でも）必ず結果に含まれる。
        """
        if not edge_ids:
            return {}
        result: dict[str, float] = {}
        max_distance_deg = _meters_to_bbox_margin_deg(max_distance_m)
        for id_chunk in _chunked(edge_ids, 50_000):
            rows = await self._session.execute(
                _ACCIDENT_COUNTS_SQL,
                {
                    "edge_ids": id_chunk, "bicycle_only": bicycle_only, "max_distance_m": max_distance_m,
                    "max_distance_deg": max_distance_deg,
                },
            )
            for edge_id, accident_count in rows.all():
                result[edge_id] = float(accident_count)
        return result

    async def get_nearest_accident_counts(
        self,
        points: list[tuple[float, float]],
        bicycle_only: bool = True,
        max_distance_m: float = ACCIDENT_MATCH_MAX_DISTANCE_M,
    ) -> list[float]:
        """(lat, lon)点列それぞれについて、`max_distance_m`以内にある事故の件数
        （死亡事故重み付け）を返す（入力と同じ順序・同じ長さ、外部静的データソース T50残作業）。
        get_nearest_stop_poi_countsと同じ考え方（openrouteserviceエンジンがgeometry上の
        サンプル点をこのメソッドで自前DBへ空間マッチする）。`bicycle_only`既定値は
        get_accident_countsと同じ理由でTrue。
        """
        if not points:
            return []
        lats = [p[0] for p in points]
        lons = [p[1] for p in points]
        result = await self._session.execute(
            _NEAREST_ACCIDENT_COUNTS_SQL,
            {
                "lats": lats, "lons": lons, "bicycle_only": bicycle_only, "max_distance_m": max_distance_m,
                "max_distance_deg": _meters_to_bbox_margin_deg(max_distance_m),
            },
        )
        return _restore_ordinality_order(result.all(), len(points), 0.0)

    async def get_accident_years_covered(self) -> int:
        """事故データの収録年数（accident_import_runsの成功run、年重複なし）を返す。
        distance_weighted_accident_density（domain/accident.py）の「件/(km・年)」
        正規化に使う。1リクエスト1回だけ呼ぶ想定（stop_counts等と同じタイミング）。
        """
        result = await self._session.execute(_ACCIDENT_YEARS_COVERED_SQL)
        return result.scalar_one()

    async def get_designated_edge_ids(self, edge_ids: list[str]) -> set[str]:
        """指定edge_idのうち、KSJ N10/N12（`domain/designation.py:
        TRAFFIC_STRESS_DESIGNATION_KINDS`）に該当するものの集合を返す（外部静的データソース
        T51）。`designation_attributes`はmatch_designations.pyの事前計算バッチが埋める
        （クエリ時にバッファ交差計算はしない）。
        """
        if not edge_ids:
            return set()
        result: set[str] = set()
        for id_chunk in _chunked(edge_ids, 50_000):
            rows = await self._session.execute(
                _DESIGNATED_EDGE_IDS_SQL,
                {"edge_ids": id_chunk, "kinds": sorted(TRAFFIC_STRESS_DESIGNATION_KINDS)},
            )
            result.update(edge_id for (edge_id,) in rows.all())
        return result


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

    async def get_way_tags(self, edge_ids: list[str]) -> dict[str, dict[str, str]]:
        return await self.attributes.get_way_tags(edge_ids)

    async def get_way_tags_by_osm_way_id(self, osm_way_id: int) -> tuple[str | None, dict[str, str], bool] | None:
        return await self.attributes.get_way_tags_by_osm_way_id(osm_way_id)

    async def get_nearest_way_tags(
        self, points: list[tuple[float, float]], max_distance_m: float = SURFACE_MATCH_MAX_DISTANCE_M
    ) -> list[tuple[str | None, dict[str, str], bool]]:
        return await self.attributes.get_nearest_way_tags(points, max_distance_m=max_distance_m)

    async def get_intersection_counts(
        self, edge_ids: list[str], max_distance_m: float = INTERSECTION_MATCH_MAX_DISTANCE_M
    ) -> dict[str, int]:
        return await self.attributes.get_intersection_counts(edge_ids, max_distance_m=max_distance_m)

    async def get_nearest_intersection_counts(
        self, points: list[tuple[float, float]], max_distance_m: float = INTERSECTION_MATCH_MAX_DISTANCE_M
    ) -> list[int]:
        return await self.attributes.get_nearest_intersection_counts(points, max_distance_m=max_distance_m)

    async def get_accident_counts(
        self, edge_ids: list[str], bicycle_only: bool = True, max_distance_m: float = ACCIDENT_MATCH_MAX_DISTANCE_M
    ) -> dict[str, float]:
        return await self.attributes.get_accident_counts(edge_ids, bicycle_only=bicycle_only, max_distance_m=max_distance_m)

    async def get_nearest_accident_counts(
        self,
        points: list[tuple[float, float]],
        bicycle_only: bool = True,
        max_distance_m: float = ACCIDENT_MATCH_MAX_DISTANCE_M,
    ) -> list[float]:
        return await self.attributes.get_nearest_accident_counts(
            points, bicycle_only=bicycle_only, max_distance_m=max_distance_m
        )

    async def get_accident_years_covered(self) -> int:
        return await self.attributes.get_accident_years_covered()

    async def get_designated_edge_ids(self, edge_ids: list[str]) -> set[str]:
        return await self.attributes.get_designated_edge_ids(edge_ids)

    # --- 表示用MVT（RoadSurfaceTileQuery） ---

    async def get_road_surface_tile_mvt(
        self, z: int, x: int, y: int, bbox: BoundingBox, coverage_tile: tuple[int, int, int]
    ) -> bytes | None:
        return await self.tile_query.get_road_surface_tile_mvt(z, x, y, bbox, coverage_tile)

    async def get_poi_tile_mvt(
        self, z: int, x: int, y: int, bbox: BoundingBox, coverage_tile: tuple[int, int, int]
    ) -> bytes | None:
        return await self.tile_query.get_poi_tile_mvt(z, x, y, bbox, coverage_tile)
