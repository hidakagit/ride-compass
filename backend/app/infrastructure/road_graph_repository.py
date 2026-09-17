"""Road Graph・Road AttributeのPostGIS永続化層。

責務ごとに4つのリポジトリへ分割している（変更理由が異なる操作を
1クラスに同居させない）:
- `RawOsmRepository`: 生OSM層（osm_raw_ways/osm_raw_nodes）とタイル取得マーカー
  （road_graph_tiles）。データ取込・closure読み出しの都合で変わる
- `DerivedGraphRepository`: 派生グラフ（road_nodes/road_edges）と鮮度判定（split_at）。
  交差点分割アルゴリズムの都合で変わる
- `AttributeRepository`: Edge単位のRoad Attribute（elevation_attributes。surfaceは
  road_edges.osm_way_id経由でosm_raw_ways.surfaceをJOIN導出するため専用テーブルは持たない）。
  属性の種類追加の都合で変わる
- `RoadSurfaceTileQuery`: 地域路面レイヤー表示用のMVT生成（読み取り専用）。
  地図表示の都合で変わる
`RoadGraphRepository`は4つを既存の公開APIのまま束ねるファサード（DI・テストの
安定した注入点）。新しいコードは用途に応じて個別リポジトリを直接使ってよい。

**トランザクション境界の規約**: 本モジュールの書き込みメソッドは
一切commitしない。呼び出し側（サービス層）が操作のまとまりごとに
`RoadGraphRepository.commit()`を呼んで確定する。4リポジトリは同一AsyncSessionを
共有するため、どのリポジトリ経由の変更もまとめて確定される。
例: GraphServiceは「タイルの生データ保存＋取得済みマーク」を1コミット、
「分割結果の保存」を1コミットにする（保存とマークを1コミットにまとめることで
原子性を保つ）。

node_id/edge_idはdomain/graph.pyでOSM IDから決定論的に導出されるため、同じ現実の
交差点・道路区間に対する保存は常に同じ主キーへのUPSERT（`Session.merge`）になる。

`get_graph_in_bbox`自体は「指定bboxと交差するEdgeを返す」単純な空間検索であり、
「そのbboxが過去に完全に取得済みかどうか」は判定しない。正確なキャッシュカバレッジ判定は
`RoadGraphTileRow`（タイル取得済みマーカー、読み取りは`get_cached_tiles`、書き込みは
`app/batch/import_pbf.py`の`_mark_tiles`）が担う。
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
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

import shapely
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString, Point
from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    Text,
    and_,
    any_,
    bindparam,
    case,
    cast,
    delete,
    func,
    or_,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.domain.attributes import (
    EdgeAttributeCounts,
    EdgeMaterialBundle,
    EdgeMaterialsBatch,
    ElevationAttribute,
    WayAttributeCounts,
    WIRED_LANDCOVER_KEYS,
)
from app.domain.landcover import EdgeLandcover, LandcoverPercentages, LandcoverRecord, WayLandcover
from app.domain.graph import (
    DirectedEdge,
    EdgeLike,
    LeanEdge,
    LeanNode,
    LeanRoadGraph,
    Node,
    NodeLike,
    RoadGraph,
    RoadGraphLike,
    WaySpec,
)
from app.domain.region import BoundingBox
from app.domain.accident import ACCIDENT_FATAL_WEIGHT, ACCIDENT_MATCH_MAX_DISTANCE_M
from app.domain.designation import CAR_STRESS_DESIGNATION_KINDS
from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS
from app.domain.traffic import (
    HIGHWAY_RANK,
    INTERSECTION_DEGREE_THRESHOLD,
    POI_COUNT_KINDS,
    POI_CLUSTER_EPS_M,
    POI_ON_EDGE_TOLERANCE_M,
    STOP_POI_KINDS,
)
from app.domain.tuning import tuning_value
from app.infrastructure.cache_identity import POI_REVISION, ROAD_SURFACE_REVISION, cache_identity
from app.infrastructure.designation_models import DesignationAttributeRow
from app.infrastructure.osm_way_tag_sql import (
    BICYCLE_NORMALIZED_SQL,
    BRIDGE_NORMALIZED_SQL,
    CYCLEWAY_TAGS_ARRAY_SQL,
    HIGHWAY_SQL,
    LANES_COUNT_CASE_SQL,
    LIT_NORMALIZED_SQL,
    MAXSPEED_KMH_CASE_SQL,
    MOTOR_VEHICLE_NORMALIZED_SQL,
    SMOOTHNESS_NORMALIZED_SQL,
    SURFACE_GOOD_CASE_SQL,
    SURFACE_NORMALIZED_SQL,
    TUNNEL_NORMALIZED_SQL,
)
from app.infrastructure.vector_tile import (
    ROAD_SURFACE_LAYER_NAME,
    STOP_POI_LAYER_NAME,
    TILE_EXTENT,
)
from app.infrastructure import derived_data_meta
from app.infrastructure.road_graph_models import (
    Base,
    EdgeAttributeCountsRow,
    EdgeLandcoverRow,
    ElevationAttributeRow,
    OsmRawNodeRow,
    OsmRawWayRow,
    RoadEdgeRow,
    RoadGraphTileRow,
    RoadNodeRow,
    WayLandcoverRow,
)

logger = logging.getLogger("ridecompass.road_graph_repository")

CACHED_GRAPH_VERSION = "cached"

# 近傍Way探索範囲(extent)の上限マージン。bboxをかすめる1本の長大way
# （河川沿いサイクリングロード・幹線等で数十km）があると、主対象Way全体のextentが
# その全長へ広がり、そこに交差する全way・全nodeをロードしてしまう
# （最悪ケースでメモリ・転送量・build_road_graph計算量が数十倍に膨らむ）。
# extentを要求bboxからこのマージン分だけ拡張した範囲へクランプする（案a、実装最小）。
# クランプ幅を超えて伸びるwayの端の交差点は「そのwayが主対象になる別リクエストで更新される」
# 既存の結果整合性の考え方（本クラスdocstringの`get_way_specs_with_closure`該当節参照）に乗せる。
NEIGHBOR_EXTENT_MAX_MARGIN_M = 10_000.0

# バルクUPSERT1文あたりの行数の上限。実際に1文へ載せる行数は、これと「パラメータ上限
# から列数で割った値」の小さい方（`_bulk_chunk_rows`）を使う——UPSERTは行数×列数ぶんの
# パラメータを消費するため、行数だけを固定値で持つと列を足したときに静かに上限を超える。
_BULK_CHUNK_ROWS = 1000
# PostgreSQLが1文で受け取れるバインドパラメータの上限。
MAX_BIND_PARAMS_PER_STATEMENT = 32_767
# IN句・削除等でIDリストを分割するサイズ（1要素=1パラメータのため上限に余裕を持たせる）
_ID_CHUNK_SIZE = 10_000
# 交差点属性の再計算・読み戻しの1回あたりnode数。信号の有無は半径での空間結合で、
# 全件を1文にするとプランが全組み合わせ評価へ落ちる（precompute_road_node_intersections.py
# と同じ事情。同じ理由で同じ大きさにしてある）。
_NODE_ATTRIBUTE_CHUNK_SIZE = 20_000


def _chunked(items: list, size: int) -> Iterator[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _bulk_chunk_rows(rows: list[dict]) -> int:
    """`rows`（同じ列構成の辞書のリスト）を1文へ何行ずつ載せるか（`_BULK_CHUNK_ROWS`参照）。"""
    return max(1, min(_BULK_CHUNK_ROWS, MAX_BIND_PARAMS_PER_STATEMENT // len(rows[0])))


async def create_tables(engine: AsyncEngine) -> None:
    """新規DB向けの基本スキーマを作成する（PostGIS拡張の有効化＋ORMモデルからのcreate_all）。

    列追加・インデックス追加・データバックフィルといった一度きりのスキーマ変更は
    `migrations/`配下の番号付きSQLファイル（`infrastructure/migrate.py:
    apply_pending_migrations`）で行う（decisions/pre-static-attributes-gate.md 決定3参照）。
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


# 路面タイル（MVT）をPostGIS側で丸ごと生成するクエリ（get_road_surface_tile_mvt参照）。
#
# ST_AsMVTでPostGIS側にてタイルを丸ごと生成する。転送は完成済みタイル1個（数十KB）で
# 済み、エンコードはPostGISのC実装が担う。bbox内の全way行（数千件のジオメトリ）を
# Pythonへ転送してshapelyでdecode→mapbox_vector_tileでencodeする構成だと、遠隔DB
# （Supabase等）では行転送だけで数秒、Python側のCPU処理（GILを握る）でさらに数秒かかり、
# パン操作のバースト時に複数リクエストの待ち行列がフロントエンド（Next.jsのrewrites
# プロキシ、デフォルト30秒タイムアウト）の制限に抵触しうる。
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
# そのまま数百ms〜1秒程度の短縮になる）。
# CASE式は条件がfalseの分岐を評価しないため、カバレッジ外ではMVT生成のサブクエリ自体が
# 実行されない。
# 静的道路属性 P0（docs/static-road-attributes-plan.md）追加プロパティの計算根拠:
# - smoothness: 生タグをlower(btrim())で正規化して焼くだけ（surfaceと同じ流儀）
# - tunnel/bridge: タグ値'yes'のときだけtrueを焼く（それ以外はキー省略＝ST_AsMVTがNULLを
#   省略する既存の挙動をそのまま使う。「非該当」が大多数のため省略した方がタイルが軽い）
# - car_stress（車ストレス、1-5）は
#   ここでは**計算済みの最終値を焼かない**。タイルは全ユーザー共有でキャッシュされる
#   （Cache-Control: max-age=3600＋ディスクキャッシュ）ため、最終値をSQLへ焼き込むと
#   判定基準（highway別基準値・cycleway/maxspeed/lanes/指定路線の補正）を変えるたびに
#   世界中のタイルキャッシュを作り直す必要が生じる。代わりに材料タグ
#   （maxspeed_kmh/lanes_count/motor_vehicle_no、highwayは既存プロパティを流用。
#   自転車インフラの評価はis_emergency_transport等と同じ正規化フラグ材料
#   [highway_is_cycleway等、domain/recipe.py: bicycle_infra_flags]で行う）だけを
#   焼き込み、最終値の計算はフロントエンド側
#   （frontend/src/components/Map/axisLayers.ts、汎用rampパイプライン）と
#   ルート採点（domain/axis_definitions.pyのAXIS_DEFINITIONS、car_stressを
#   支える内部軸6つ+公開軸1つの階層構造）がそれぞれ行う。両者は同じ材料タグの定義
#   （domain/registry_defaults.pyのtile_inputsが
#   AXIS_DEFINITIONSの各内部軸shapeを片側importで参照）に対応させることで同期を担保する
#   （このSQL側の整合性テストは材料タグの焼き込みが正しいことだけを検証すればよい）。
#   maxspeed/lanesの数値パースは、Pythonのparse_maxspeed/parse_lanes（int(float(x))で
#   小数を切り捨て）と合わせるためtrunc()を使い、非数値文字列（"30 mph"等）は正規表現で
#   弾いてunknown安全にする。
# - lit（街灯タグの有無）はnight軸（domain/night.py: night_difficulty、
#   domain/registry_defaults.py: inputs=["lit","tunnel"]）の入力として焼き込む
#   （tunnelは上のtunnelプロパティを再利用）。night軸自体は専用の地図レイヤーを持たない。
# - accident_per_km/intersection_per_km（「事実はタイルに、
#   解釈はクライアントに」方針）: km正規化した密度を焼き込む。**そのフィーチャーが表す
#   区間の実測から出す**（`_density_column_sql`）——区間単位のフィーチャーは
#   edge_attribute_counts、way丸ごとのフィーチャーはway_attribute_counts。
#   edge_attribute_countsがroad_edgesの範囲しか覆わないことは制約にならない: 区間単位の
#   フィーチャーを出す枝の母集団がroad_edgesそのもので、両者は一致する（引いた表示や
#   区間を持たないwayはそもそもway集計側へ落ちる）。これらはレシピに
#   依存しない静的な事実のため、「最終値を焼かない」上記方針と矛盾しない（レシピ変更で
#   タイルキャッシュが無効化されることはない。無効化が必要になるのはaccident_points/
#   osm_raw_pois/osm_raw_waysの再取込時のみで、その場合はprecompute_way_attribute_counts
#   →タイル世代対上げで反映する）。km正規化は評価軸の実入力（停止密度の材料はper-km値）
#   と意味論を揃えるためで、way長への依存も除ける。0・極短way（length_m<=0）はNULLIFで
#   キー省略し（大多数のwayが0のためタイルが軽くなる、tunnel/bridgeと同じ流儀）、
#   フロントは欠損=0として扱う。二次軸スコア（レシピ依存の解釈）は引き続きフロント側で
#   計算する。
def _density_column_sql(edge_count_sql: str, way_count_sql: str, precision: int) -> str:
    """件数をkm正規化した密度の式を組み立てる。

    **そのフィーチャーが表す区間の実測から出す**。区間単位のフィーチャーは
    `edge_attribute_counts`（`road_edges`と同じ母集団を`precompute_edge_attribute_counts`が
    埋める）の件数をその区間の長さで割る。way丸ごとのフィーチャー（引いた表示・区間を
    持たないway）と、区間はあるが集計行がまだ無いフィーチャーはway集計へ落ちる——件数と
    長さは必ず同じ側から取る（片方だけedgeにすると、区間の件数をway全体の長さで割った
    無意味な値になる）。

    ST_AsMVTはnumeric型をtextへフォールバックするため（maxspeed_kmhのコメント参照）、
    丸めた後にdouble precisionへキャストする。0はNULLIFでプロパティ自体を省く
    （大多数が0のためタイルが軽くなる。フロントは欠損=0として扱う既存の流儀）。
    """
    return f"""
                        NULLIF(
                            round(
                                (CASE WHEN ec.edge_id IS NOT NULL
                                      THEN ({edge_count_sql}) * 1000.0 / NULLIF(src.length_m, 0)
                                      ELSE ({way_count_sql}) * 1000.0 / NULLIF(wc.length_m, 0)
                                 END)::numeric, {precision}
                            ), 0
                        )::double precision"""


# 区間単位の土地被覆を、向きに依らない区間の同定子で引き当てる条件。road_edgesの
# forward/backwardは同じ1行を共有する（`precompute_edge_landcover.py`参照）。
_EDGE_LANDCOVER_JOIN_ON = and_(
    EdgeLandcoverRow.osm_way_id == RoadEdgeRow.osm_way_id,
    EdgeLandcoverRow.node_lo == func.least(RoadEdgeRow.from_node_id, RoadEdgeRow.to_node_id),
    EdgeLandcoverRow.node_hi == func.greatest(RoadEdgeRow.from_node_id, RoadEdgeRow.to_node_id),
)


def _landcover_value_column(key: str):
    """そのEdgeへ与える土地被覆1クラスの値。**区間単位の行があればそちら、無ければway単位**
    へ落とす（路面タイルの同じ切り替えと揃える——揃えないと、地図に出ている値と採点が
    使う値が食い違う）。区間の行が「計算済み・値なし」のときもway単位へは戻さない
    （行の有無で決める。密度の`_density_column_sql`と同じ規則）。"""
    return case(
        (EdgeLandcoverRow.osm_way_id.is_not(None), getattr(EdgeLandcoverRow, key)),
        else_=getattr(WayLandcoverRow, key),
    ).label(key)


# 土地被覆の派生行のうち、単位（way／区間）に依らない列。way_landcover・edge_landcoverは
# 鍵だけが違い、値と系譜は同じ形で書く——片方だけ列が増えると、同じ道の同じ場所に別の
# 内容の行ができる。
_LANDCOVER_UPSERT_COLUMNS = [
    "valid_pixels", "water_percent", "trees_percent", "flooded_veg_percent", "crops_percent",
    "built_percent", "bare_percent", "snow_ice_percent", "rangeland_percent",
    "data_source", "data_version", "computed_at", "source_osm_import_run_id", "algorithm_version",
    "source_raster_set",
]


def _landcover_value_row(record: LandcoverRecord) -> dict:
    """`_LANDCOVER_UPSERT_COLUMNS`ぶんの値。`percentages`がNoneの行は「計算済み・値なし」で、
    割合列をNULLで書くことで増分実行が同じ対象を毎回やり直すのを避ける。"""
    p = record.percentages
    return {
        "valid_pixels": p.valid_pixels if p else None,
        "water_percent": p.water_percent if p else None,
        "trees_percent": p.trees_percent if p else None,
        "flooded_veg_percent": p.flooded_veg_percent if p else None,
        "crops_percent": p.crops_percent if p else None,
        "built_percent": p.built_percent if p else None,
        "bare_percent": p.bare_percent if p else None,
        "snow_ice_percent": p.snow_ice_percent if p else None,
        "rangeland_percent": p.rangeland_percent if p else None,
        "data_source": record.data_source,
        "data_version": record.data_version,
        "computed_at": record.computed_at,
        "source_osm_import_run_id": record.source_osm_import_run_id,
        "algorithm_version": record.algorithm_version,
        "source_raster_set": record.source_raster_set,
    }


# 地図タイルへ焼き込む停止要因の種別別密度。列名は材料id（`poi_{kind}_per_km`）と同じにして
# 対応を自明にする。MVTはjsonbを持てないため、ここだけキー一覧から列へ展開する
# （手書きせず`POI_COUNT_KINDS`から生成するので、キーを増やしてもこの式は変わらない）。
# 0件のキーはjsonbに載らないため0として読む。
_POI_TILE_COLUMNS_SQL = "".join(
    _density_column_sql(
        f"COALESCE((ec.poi_counts->>'{kind}')::int, 0)",
        f"COALESCE((wc.poi_counts->>'{kind}')::int, 0)",
        precision=1,
    )
    + f" AS poi_{kind}_per_km,"
    for kind in POI_COUNT_KINDS
)


# 土地被覆の焼き込み列。材料の`tile_property`（`crops_pct`等）と同じ名前にし、配線する
# クラスの並び（`WIRED_LANDCOVER_KEYS`）から組み立てる——手で並べると、クラスを1つ
# 配線したときに「材料は地図レンズを持つのに列が無い」形で静かに空になる。
# DBの列名は`<クラス>_percent`、タイルのプロパティ名は`<クラス>_pct`。
#
# **そのフィーチャーが表す単位から出す**（密度の`_density_column_sql`と同じ規則）。区間単位の
# フィーチャーは`edge_landcover`、way丸ごとのフィーチャー（引いた表示・区間を持たないway）と
# 区間の行がまだ無いフィーチャーは`way_landcover`へ落ちる。区間の行があって値がNULL
# （その構成では値なし）のときもway側へは戻さない——戻すと、隣り合う区間が別の単位の値で
# 塗られる。
_LANDCOVER_COLUMN_SUFFIX = "_percent"
_LANDCOVER_TILE_COLUMNS_SQL = ("," + "\n").join(
    f"                        (CASE WHEN elc.osm_way_id IS NOT NULL THEN elc.{key} ELSE lc.{key} END)"
    f"::double precision AS {key.removesuffix(_LANDCOVER_COLUMN_SUFFIX)}_pct"
    for key in WIRED_LANDCOVER_KEYS
)

# 路面タイルが1フィーチャーとして焼く単位。**区間が読めるズームでは区間（road_edges）、
# それより引いた表示ではway丸ごと（osm_raw_ways）**にする。境界の根拠は
# docs/tasks/T917.mdの実測——gzip後の費用はz14で1.48倍・z12で1.81倍（1画面9タイルで
# +90KB / +2.4MB）へ増える一方、z12は1pxが約38mで、交差点で切った区間は数pxにしかならず
# 塗り分けても読めない。費用が跳ね上がるズームと、区間単位の情報量が消えるズームが
# 一致している。
#
# どちらの単位も`feature_key`という同じ名前のプロパティで出す。フロントは`promoteId`で
# これをfeature.idへ昇格させるだけでよく、中身がway_idかedge_idかを知らなくてよい
# （値の配信もタイル単位のため、そのズームの鍵で返せば噛み合う）。
EDGE_UNIT_MIN_ZOOM = 14

# 同じ物理区間の逆方向（road_edgesはforward/backwardを別行で持つ）を落とす。**wayと両端ノードの
# 組で見分ける**——PostGISのジオメトリ正規化はLINESTRINGの向きを揃えないため形状では
# 同一と判定できず、
# 一方でノードの組だけだと同じノード対を共有する別々のwayまで1本へ潰れる。残す側はedge_id
# 昇順で決定論的に固定する。
#
# 空間フィルタは各枝の中に置く。外へ出すと重複排除がroad_edges全件に対して走り、タイルの
# 中身に依存しない固定コスト（実測8秒台）になる。
_TILE_FEATURE_SOURCE_SQL = """
    SELECT
        w2.geom AS geom,
        w2.osm_way_id AS osm_way_id,
        w2.osm_way_id::text AS feature_key,
        NULL::text AS node_lo,
        NULL::text AS node_hi,
        NULL::double precision AS length_m
    FROM osm_raw_ways w2
    WHERE :z < EDGE_UNIT_MIN_ZOOM_VALUE
      AND w2.geom IS NOT NULL
      AND ST_Intersects(w2.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
    UNION ALL
    SELECT geom, osm_way_id, feature_key, node_lo, node_hi, length_m FROM (
        SELECT DISTINCT ON (
            re.osm_way_id, LEAST(re.from_node_id, re.to_node_id), GREATEST(re.from_node_id, re.to_node_id)
        )
            re.geom AS geom,
            re.osm_way_id AS osm_way_id,
            re.edge_id AS feature_key,
            -- 代表に選ばれなかった逆向きの行を後から引き当てるための、向きに依らない区間の
            -- 同定子。材料（標高属性等）は向きごとの行に付くため、代表の向きの行にだけ
            -- 無いと値が落ちる。
            LEAST(re.from_node_id, re.to_node_id) AS node_lo,
            GREATEST(re.from_node_id, re.to_node_id) AS node_hi,
            -- 密度（件/km）の分母。way全体ではなくこの区間の長さで割る。
            re.distance_m AS length_m
        FROM road_edges re
        WHERE :z >= EDGE_UNIT_MIN_ZOOM_VALUE
          AND re.osm_way_id IS NOT NULL
          AND ST_Intersects(re.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
        ORDER BY
            re.osm_way_id,
            LEAST(re.from_node_id, re.to_node_id),
            GREATEST(re.from_node_id, re.to_node_id),
            re.edge_id
    ) deduped_edges
    UNION ALL
    -- 区間を1本も持たないway（座標が判明しているノードが2点未満のway等、domain/graph.py:
    -- build_road_graph参照）は、区間単位のズームでもway丸ごとで出す。**落とすと、その道は
    -- ズームを上げたときだけ地図から消える**——引いた表示には出ているのに拡大すると無くなる
    -- 見え方は、データが無いことよりも壊れて見える。
    SELECT
        w3.geom AS geom,
        w3.osm_way_id AS osm_way_id,
        w3.osm_way_id::text AS feature_key,
        NULL::text AS node_lo,
        NULL::text AS node_hi,
        NULL::double precision AS length_m
    FROM osm_raw_ways w3
    WHERE :z >= EDGE_UNIT_MIN_ZOOM_VALUE
      AND w3.geom IS NOT NULL
      AND ST_Intersects(w3.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
      AND NOT EXISTS (SELECT 1 FROM road_edges re2 WHERE re2.osm_way_id = w3.osm_way_id)
""".replace("EDGE_UNIT_MIN_ZOOM_VALUE", str(EDGE_UNIT_MIN_ZOOM))


_ROAD_SURFACE_TILE_MVT_SQL = (
    text(
        f"""
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
                            ST_Transform(src.geom, 3857), ST_TileEnvelope(:z, :x, :y), :extent, 256, true
                        ) AS geom,
                        -- このフィーチャーが表す単位の識別子（EDGE_UNIT_MIN_ZOOM参照）。
                        -- 値の配信（dynamic-way-values）はこの鍵で返る。
                        src.feature_key AS feature_key,
                        -- 区間インスペクタ（クリック時の車ストレス内訳表示）が、ポップアップに
                        -- 出た値と同じ行を曖昧さ無く引き直すための識別子。空間マッチ
                        -- (半径内最近傍)だと交差点付近で別の道路を拾いうるため、
                        -- フィーチャーが指す行そのものをosm_way_id完全一致で引く
                        -- （get_way_tags_by_osm_way_id）。
                        w.osm_way_id AS osm_way_id,
                        -- 道路名・路線番号（表示専用）。材料の正規化（小文字化）は
                        -- かけない——利用者へそのまま見せる固有名詞のため。空文字の
                        -- タグはNULLIFでキーごと省く（名前を持たないwayが大多数で、
                        -- 欠損とタグ値""を区別する意味も無い）。**第三者が編集できる
                        -- 生値で対訳表を持たない**ため、埋め込む側は必ずエスケープする
                        -- （frontend: popupEscape.ts）。
                        NULLIF(btrim(w.tags->>'name'), '') AS name,
                        NULLIF(btrim(w.tags->>'ref'), '') AS ref,
                        {SURFACE_GOOD_CASE_SQL} AS surface_good,
                        {SURFACE_NORMALIZED_SQL} AS surface,
                        {HIGHWAY_SQL} AS highway,
                        {SMOOTHNESS_NORMALIZED_SQL} AS smoothness,
                        CASE WHEN {TUNNEL_NORMALIZED_SQL} = 'yes' THEN true END AS tunnel,
                        CASE WHEN {BRIDGE_NORMALIZED_SQL} = 'yes' THEN true END AS bridge,
                        -- 一方通行（一次属性）。w.directionはosm_adapter.py:
                        -- _resolve_directionがoneway/oneway:bicycleタグから解決済みの
                        -- forward/backward/both（osm_raw_ways専用列、tagsのJSONBには
                        -- 含まれない）。一方通行の逆方向は既にbuild_road_graphがEdge自体を
                        -- 生成しないため、探索の正しさには無関係（表示専用の一次属性）。
                        -- 上下線が分かれた道の片側は外す（道路としては双方向で、逆方向は
                        -- 数m隣にある。判定はway_divided_carriageway）。未判定
                        -- （バッチ未実行でNULL）は安全側のfalseとして扱い、directionだけで
                        -- 塗る従来の見え方へ倒す。
                        CASE WHEN w.direction != 'both'
                                  AND NOT COALESCE(wdc.divided, false)
                             THEN true END AS oneway,
                        -- ST_AsMVTはnumeric型を認識せずtextへフォールバックする
                        -- （フロントのMapLibre expressionが数値比較できなくなる）ため、
                        -- integerへキャストしてから焼き込む。0以下はPythonのparse_maxspeed/
                        -- parse_lanes（`value if value > 0 else None`）と同じくunknown扱いにし
                        -- キー自体を省略する（"maxspeed=0"のような無効タグでフロント/採点側の
                        -- 補正が誤発火しないようにする）。
                        {MAXSPEED_KMH_CASE_SQL} AS maxspeed_kmh,
                        {LANES_COUNT_CASE_SQL} AS lanes_count,
                        CASE WHEN {MOTOR_VEHICLE_NORMALIZED_SQL} = 'no' THEN true END AS motor_vehicle_no,
                        -- night軸の材料タグ。tunnelは既存プロパティ
                        -- （上のtunnel、表示用と兼用）をそのまま再利用し、litのみ新規抽出する
                        -- （motor_vehicle_noと同じCASE式パターン）。
                        CASE WHEN {LIT_NORMALIZED_SQL} = 'yes' THEN true END AS lit,
                        CASE
                            WHEN COALESCE(d.is_ert, false) AND COALESCE(d.is_cl, false) THEN 'both'
                            WHEN d.is_ert THEN 'emergency_transport'
                            WHEN d.is_cl THEN 'critical_logistics'
                        END AS designation,
                        -- 上のdesignation（3値、地図表示専用）が畳み込む前の正規化フラグを、
                        -- 評価軸の材料として個別に焼き込む（複雑な分類の生値は表示専用として
                        -- 残し、評価用の正規化材料は別途用意する設計）。d.is_ert/d.is_clは
                        -- 既に計算済みのため追加JOINは不要。
                        CASE WHEN d.is_ert THEN true END AS is_emergency_transport,
                        CASE WHEN d.is_cl THEN true END AS is_critical_logistics,
                        -- 公開軸「自転車インフラ」（bicycle_infra_quality）が参照する
                        -- 5正規化フラグ材料（domain/recipe.py: bicycle_infra_flagsと
                        -- 同じ判定式、domain/material_catalog.py参照）。複数の独立フラグ
                        -- として個別に焼き込む設計（is_emergency_transport/
                        -- is_critical_logisticsと同じ理由）。
                        CASE WHEN {HIGHWAY_SQL} = 'cycleway' THEN true END AS highway_is_cycleway,
                        CASE WHEN 'track' = ANY({CYCLEWAY_TAGS_ARRAY_SQL}) THEN true END AS cycleway_has_track,
                        CASE WHEN 'lane' = ANY({CYCLEWAY_TAGS_ARRAY_SQL}) THEN true END AS cycleway_has_lane,
                        CASE WHEN {CYCLEWAY_TAGS_ARRAY_SQL} && ARRAY['share_busway', 'shared_lane']
                            THEN true END AS cycleway_has_shared,
                        CASE
                            WHEN {HIGHWAY_SQL} IN ('footway', 'path')
                                 AND {BICYCLE_NORMALIZED_SQL} IN ('yes', 'designated')
                                THEN true
                        END AS shared_pedestrian_path,
                        -- 事前集計カウントのkm正規化密度（冒頭コメント・
                        -- _density_column_sql参照）。
                        {_density_column_sql("ec.accident_count", "wc.accident_count", 2)} AS accident_per_km,
                        {_density_column_sql("ec.intersection_count", "wc.intersection_count", 1)}
                            AS intersection_per_km,{_POI_TILE_COLUMNS_SQL}
{_LANDCOVER_TILE_COLUMNS_SQL}
                    FROM ({_TILE_FEATURE_SOURCE_SQL}) src
                    JOIN osm_raw_ways w ON w.osm_way_id = src.osm_way_id
                    LEFT JOIN way_attribute_counts wc ON wc.osm_way_id = w.osm_way_id
                    -- 区間単位のフィーチャーのときだけ一致する（feature_keyがedge_idの
                    -- ときのみ。way丸ごとのフィーチャーではNULLになりway集計側へ落ちる）。
                    LEFT JOIN edge_attribute_counts ec ON ec.edge_id = src.feature_key
                    LEFT JOIN way_landcover lc ON lc.osm_way_id = w.osm_way_id
                    -- 区間単位のフィーチャーのときだけ一致する（way丸ごとのフィーチャーは
                    -- node_lo/node_hiがNULLのため一致せず、way_landcover側へ落ちる）。
                    LEFT JOIN edge_landcover elc
                        ON elc.osm_way_id = src.osm_way_id
                       AND elc.node_lo = src.node_lo
                       AND elc.node_hi = src.node_hi
                    LEFT JOIN way_divided_carriageway wdc ON wdc.osm_way_id = w.osm_way_id
                    LEFT JOIN LATERAL (
                        -- 指定路線（designation_attributes、match_designations.pyが埋める
                        -- osm_way_id単位の派生テーブル）をwayごとに主キーで引く。wayに相関
                        -- させたLATERALにするのは、相関の無い集約サブクエリ（テーブル全体を
                        -- GROUP BYしてからJOIN）だとプランナが全行の集約を毎回先に実行し、
                        -- 数百wayのタイルでもその固定コストが乗るため。osm_way_id 1件に対し
                        -- kindは高々2件。該当行が無いwayではbool_orがNULLになる（LEFT JOINの
                        -- 不一致と同じ扱い）。
                        SELECT
                            bool_or(kind = 'emergency_transport') AS is_ert,
                            bool_or(kind = 'critical_logistics') AS is_cl
                        FROM designation_attributes
                        WHERE osm_way_id = w.osm_way_id
                    ) d ON true
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


# way_id→動的値配信層（風、「評価軸」グループ）。ルート未確定時は視界内の全道路へ
# 一律適用する線表示の基盤。_ROAD_SURFACE_TILE_MVT_SQLと同じカバレッジ判定
# （road_graph_tilesのz12祖先タイルマーク）・同じST_Intersectsフィルタで対象wayを絞るが、
# MVTエンコード（ST_AsMVT/ST_AsMVTGeom）は行わない——返すのは指定タイル範囲に存在する
# way_idの単純な集合のみ。
#
# ある道路のwind_drag_ratioは「その道路の最寄り風グリッド点の値」と「ユーザーが指定した
# 単一の向き（全道路共通、UIのコンパススライダー由来）」だけから決まり、道路自身の向き
# （OSM上の始点→終点、データ収集上の都合で決まる値でユーザーの走行方向とは無関係）は
# 計算に一切関与しない。そのため、このSQLはway自身の方位角（ST_Azimuth）を計算する必要が
# 無く、単に「タイル範囲に存在するway_idの一覧」を返すだけの軽量なクエリになっている。
# タイルと**同じソース**（_TILE_FEATURE_SOURCE_SQL）から鍵の一覧を引く。別に組み立てると、
# 代表の選び方がタイルとずれた瞬間に鍵が噛み合わず、色が一切付かない。
_FEATURE_KEYS_IN_TILE_SQL = text(
    f"""
    WITH coverage AS (
        SELECT EXISTS(
            SELECT 1 FROM road_graph_tiles
            WHERE zoom = :coverage_zoom AND x = :coverage_x AND y = :coverage_y
        ) AS covered
    )
    SELECT
        coverage.covered,
        CASE WHEN coverage.covered THEN (
            SELECT COALESCE(jsonb_agg(src.feature_key), '[]'::jsonb)
            FROM ({_TILE_FEATURE_SOURCE_SQL}) src
        ) END AS feature_keys
    FROM coverage
    """
)


# 鍵→勾配（gradient_percent）配信層。**タイルと同じソース**（_TILE_FEATURE_SOURCE_SQL）へ
# 勾配を結び、鍵がタイルのフィーチャーと1対1で噛み合うようにする。
#
# 勾配は「道路自身の向き」が本質的に必要な材料（風とは異なる性質）のため、鍵ごとに
# `(gradient_percent, road_bearing_deg)`を返す。
#
# **区間単位のズームでは、その区間の実際の値がそのまま返る**（近似が無くなる）。way単位の
# ズームでは、そのwayの**いちばん急な区間**を代表にする——区間の平均を取ると、崖を下って
# 上り返す道が両端の標高差で0%になり、実際は坂なのに平坦として塗られる。
#
# 候補には**その区間の両方向の行**が入る（区間単位のズームではnode_lo/node_hiで、way単位の
# ズームではosm_way_idで引く）。標高属性は向きごとの行に付き、片方向にしか無いことがある。
# forward/backwardのどちらを拾っても値は同じ（bearing_degが180度反転し同時に
# gradient_percentの符号も反転するため、cos補正の結果は打ち消し合う。domain/gradient.pyの
# モジュールdocstring・test_gradient.py参照）。
_FEATURE_GRADIENT_INPUTS_IN_TILE_SQL = text(
    f"""
    WITH coverage AS (
        SELECT EXISTS(
            SELECT 1 FROM road_graph_tiles
            WHERE zoom = :coverage_zoom AND x = :coverage_x AND y = :coverage_y
        ) AS covered
    )
    SELECT
        coverage.covered,
        CASE WHEN coverage.covered THEN (
            SELECT COALESCE(
                jsonb_object_agg(t.feature_key, jsonb_build_array(t.average_grade, t.bearing_deg)),
                '{{}}'::jsonb
            )
            FROM (
                SELECT DISTINCT ON (src.feature_key)
                    src.feature_key,
                    ea.average_grade,
                    re.bearing_deg
                FROM ({_TILE_FEATURE_SOURCE_SQL}) src
                JOIN road_edges re
                  ON re.osm_way_id = src.osm_way_id
                 AND (
                     src.node_lo IS NULL
                     OR (LEAST(re.from_node_id, re.to_node_id) = src.node_lo
                         AND GREATEST(re.from_node_id, re.to_node_id) = src.node_hi)
                 )
                JOIN elevation_attributes ea ON ea.edge_id = re.edge_id
                WHERE ea.average_grade IS NOT NULL
                  AND re.bearing_deg IS NOT NULL
                ORDER BY src.feature_key, abs(ea.average_grade) DESC, re.edge_id
            ) t
        ) END AS feature_gradient_inputs
    FROM coverage
    """
)


# 停止要因POI（osm_raw_pois）を1タイルへ焼き込む。_ROAD_SURFACE_TILE_MVT_SQLと同じ
# カバレッジ判定（road_graph_tilesのz12祖先タイルマーク）を再利用しつつ、対象データソースが
# 別テーブルの点データのため道路（way）とは独立のクエリにする。osm_raw_pois内のkindタグを
# そのまま焼き込むだけ（GiST索引を使うST_Intersects、集計SQLと同じosm_raw_pois）。
# 材料`intersection_count_per_km`の値は`_INTERSECTION_COUNTS_SQL`が独立に計算する。
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


# 静的道路属性P1（信号・横断歩道・一時停止・踏切のnode取込・停止密度評価）。
# 「最近傍1件」ではなく「距離内の件数」を求める単純なLEFT JOIN + COUNTのため、
# ORDER BY <-> LIMITは使わない（GiST索引で素直にindex nested loopになる）。
# edge_idはWHEREで先に絞るため、LEFT JOINでも指定edge_id全件が0件を含めて1行ずつ返る。
# JOIN条件がST_DWithin(geography)単体だとGiST索引を使わずJoin Filter
# （全組み合わせ評価）に落ちる（_INTERSECTION_COUNTS_SQLのコメント参照）。
# `&&`（geometry型のバウンディングボックス演算子）を前置してGiST索引を先に使わせてから
# ST_DWithinで精密判定する。
# 補給POI（convenience/vending_machine等）も同じosm_raw_poisへ入っているため、
# kindを絞らないこのCOUNTは停止密度へコンビニ・自販機を誤算入する
# （dev環境で全POIの約17%が補給kind）。STOP_POI_KINDS（domain/traffic.py）で
# フィルタする。
# 停止要因POIを集計キー（`domain/traffic.py: POI_COUNT_KINDS`）へ写す式。取込時の`kind`を
# そのまま使わず、信号の2通りの書かれ方を1つへまとめ、徐行を一時停止へ畳む。生タグは
# `osm_raw_pois.tags`に全件残っているため、キーの切り方を変えてもPBF再取込は要らず、
# 集計バッチの再実行だけで済む。
# SQL本文へは`__POI_KIND__`の位置へ差し込む（f-stringにすると本文中の`{}`をすべて
# エスケープする必要があり読みにくくなるため）。
_POI_COUNT_KIND_EXPR = """CASE
                    WHEN p.kind = 'traffic_signals' THEN 'signal'
                    WHEN p.kind = 'crossing' AND p.tags->>'crossing' LIKE '%signals%' THEN 'signal'
                    WHEN p.kind = 'crossing' THEN 'crossing'
                    WHEN p.kind IN ('level_crossing', 'railway_crossing') THEN 'level_crossing'
                    WHEN p.kind IN ('barrier', 'traffic_calming') THEN 'barrier'
                    ELSE 'stop'
                END"""

# 集計キー別のカウント本体。`osm_raw_pois`から次の3段で数える。
#
# 1. **そのwayの構成ノードだけ**を対象にする（`osm_node_id = ANY(node_ids)`）。距離だけで
#    拾うと、交差する別の道に付いている信号・並行する歩道の横断歩道まで数えてしまう。
# 2. **区間の始点にあるノードを除く**。交差点のノードは「入る区間」と「出る区間」の両方が
#    持つため、両方が数えると1回の停止が2回になる。止まるのは区間を走り終えるところなので、
#    到着側（終点側）の区間が持つ。有向Edgeのため逆向きの区間でも同じ規則が成り立つ。
# 3. **同じキーの点を`eps`でまとめてから数える**。日本のOSMは1つの信号交差点を流入路ごと・
#    横断歩道位置ごとの複数ノードで描くため、素直に数えると停止回数を上回る。
#
# `__EXCLUDE_NODE__`には「始点のOSMノードid」を返す式を差し込む（Edge単位はfrom_node、
# Way単位は`node_ids`の先頭）。
_POI_COUNTS_BODY = """
        SELECT c.kind, count(DISTINCT c.cid) AS cnt
        FROM (
            SELECT __POI_KIND__ AS kind,
                   ST_ClusterDBSCAN(ST_Transform(p.geom, 3857), eps := :cluster_eps_m, minpoints := 1)
                       OVER (PARTITION BY __POI_KIND__) AS cid
            FROM osm_raw_pois p
            WHERE p.osm_node_id = ANY(__NODE_IDS__)
              AND p.kind = ANY(:stop_kinds)
              AND p.osm_node_id IS DISTINCT FROM __EXCLUDE_NODE__
              __EXTRA_FILTER__
        ) c
        GROUP BY c.kind"""


def _poi_counts_body(node_ids: str, exclude_node: str, extra_filter: str = "") -> str:
    return (
        _POI_COUNTS_BODY.replace("__POI_KIND__", _POI_COUNT_KIND_EXPR)
        .replace("__NODE_IDS__", node_ids)
        .replace("__EXCLUDE_NODE__", exclude_node)
        .replace("__EXTRA_FILTER__", extra_filter)
    )


# Edge単位の種別別カウント。wayは複数の区間へ分割されるため、wayの構成ノードのうち
# 「この区間の線上にあるもの」だけへ絞る（`ST_DWithin`の許容は浮動小数の誤差ぶん）。
# タイルURL・キャッシュパスへ入る世代。焼き込むSQLから署名を導出するため、プロパティを
# 足す・消す・式を変えれば鍵が自動で変わる（手で上げるのはSQLが読むテーブルの中身を作り
# 直したときだけ。cache_identity.pyのリビジョンのコメント参照）。frontendへは
# export_openapi.pyがgenerated/region-tile-config.json経由で渡す。
ROAD_SURFACE_TILE_VERSION = cache_identity(ROAD_SURFACE_REVISION, _ROAD_SURFACE_TILE_MVT_SQL)
POI_TILE_VERSION = cache_identity(POI_REVISION, _POI_TILE_MVT_SQL)


_POI_COUNTS_BY_KIND_SQL = text(
    """
    SELECT e.edge_id,
           COALESCE(jsonb_object_agg(t.kind, t.cnt) FILTER (WHERE t.kind IS NOT NULL), '{}'::jsonb) AS poi_counts
    FROM road_edges e
    LEFT JOIN road_nodes fn ON fn.node_id = e.from_node_id
    LEFT JOIN osm_raw_ways w ON w.osm_way_id = e.osm_way_id
    LEFT JOIN LATERAL (
    __BODY__
    ) t ON true
    WHERE e.edge_id = ANY(CAST(:edge_ids AS text[]))
    GROUP BY e.edge_id
    """.replace(
        "__BODY__",
        _poi_counts_body(
            "w.node_ids",
            "fn.osm_node_id",
            "AND ST_DWithin(p.geom::geography, e.geom::geography, :on_edge_tolerance_m)",
        ),
    )
).bindparams(bindparam("stop_kinds", value=sorted(STOP_POI_KINDS), type_=ARRAY(Text())))


# 事故点の帰属先（半径内で最も近い1本のway）。事故点はOSMの要素ではないため、信号・交差点の
# ように「wayの構成ノードか」では帰属を決められない。距離だけで数えると1つの事故が半径内の
# **すべての**道路へ計上され、静かな裏道が隣の幹線で起きた事故を相続する。
# 同距離のときはosm_way_idで決める（結果を呼び出し順に依存させない）。
# way単位・Edge単位の両方が同じ帰属を使うため、判定はこの1箇所に置く。
_NEAREST_WAY_FOR_ACCIDENT_SQL = """
            SELECT nw.osm_way_id
            FROM osm_raw_ways nw
            WHERE nw.highway IS NOT NULL
              AND nw.geom && ST_Expand(a.geom, :accident_distance_deg)
              AND ST_DWithin(a.geom::geography, nw.geom::geography, :accident_distance_m)
            ORDER BY ST_Distance(a.geom::geography, nw.geom::geography), nw.osm_way_id
            LIMIT 1"""

# 外部静的データソースT50（事故密度の評価組み込み）。対象テーブルはaccident_points、
# bicycle_only（当事者に自転車を含む事故のみに絞るか）の切替を持つ。
# 空間索引（GiST）を使わせるため`&&`（bbox交差）をST_DWithinの前に置く。
# 単純COUNTではなく死亡事故を`ACCIDENT_FATAL_WEIGHT`件分とみなすSUMにする
# （domain/accident.py参照）。戻り値はfloat。LATERALで一致が無いedgeも1行返り
# `a.fatal`がNULLになるため、CASE式の先頭で`a.accident_id IS NULL`を0扱いする
# （無いとNULLは`WHEN a.fatal THEN`の条件が偽になりELSE 1へ落ち、事故0件のedgeに
# 架空の1件が計上される）。
#
# 帰属先のwayが決まったあと、そのwayのどの区間が持つかは距離で決める。逆向きの区間は
# 同じ線を共有するため距離が並び、どちらも数える（走行方向のどちらで通っても同じ事故に
# 遭遇する）。浮動小数の誤差ぶんの許容を置くのはこのため。
_EDGE_OF_WAY_NEAREST_TO_ACCIDENT_M = 0.01
_ACCIDENT_COUNTS_SQL = text(
    """
    SELECT e.edge_id,
           SUM(CASE WHEN a.accident_id IS NULL THEN 0 WHEN a.fatal THEN :fatal_weight ELSE 1 END)
               AS accident_count
    FROM road_edges e
    LEFT JOIN LATERAL (
        SELECT a.accident_id, a.fatal
        FROM accident_points a
        WHERE a.geom && ST_Expand(e.geom, :accident_distance_deg)
          AND ST_DWithin(a.geom::geography, e.geom::geography, :accident_distance_m)
          AND (:bicycle_only = false OR a.involves_bicycle)
          AND (__NEAREST_WAY__) = e.osm_way_id
          AND ST_Distance(a.geom::geography, e.geom::geography) <= :edge_tie_tolerance_m + (
              SELECT MIN(ST_Distance(a.geom::geography, e2.geom::geography))
              FROM road_edges e2
              WHERE e2.osm_way_id = e.osm_way_id
          )
    ) a ON true
    WHERE e.edge_id = ANY(CAST(:edge_ids AS text[]))
    GROUP BY e.edge_id
    """.replace("__NEAREST_WAY__", _NEAREST_WAY_FOR_ACCIDENT_SQL)
).bindparams(
    bindparam("bicycle_only", type_=Boolean()),
    bindparam("fatal_weight", value=ACCIDENT_FATAL_WEIGHT, type_=Float()),
    bindparam("edge_tie_tolerance_m", value=_EDGE_OF_WAY_NEAREST_TO_ACCIDENT_M, type_=Float()),
)

# 指定路線コンフレーション機構（外部静的データソース T51）。designation_attributesは
# match_designations.pyの事前計算バッチが埋める（クエリ時にはバッファ交差計算をしない）。
#
# designation_attributesはosm_way_idキーのため、呼び出し元
# （get_designated_edge_ids）は構築済みgraph（graph.edges.keys()、road_graph_engine.py）の
# edge_idを受け取りedge_id集合を返す必要があるため、この経路だけはroad_edgesを経由して
# edge_id→osm_way_idへマッピングしてからJOINする。呼び出し時点でgraphは既に構築済み
# （road_edgesの遅延構築は完了済み）のため、この間接JOINは「遅延構築依存」問題の
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
# domain/evaluation.py: compute_edge_axis_scoresの「件/(km・年)」正規化に使う。
# ハードコード定数にせず動的取得することで、将来の年次追加取込で自動的に正しくなる。
_ACCIDENT_YEARS_COVERED_SQL = text(
    "SELECT COUNT(DISTINCT occurred_year) FROM accident_import_runs WHERE status = 'succeeded'"
)

# 区間インスペクタ。_WAY_TAGS_BY_OSM_WAY_IDと同じ完全一致1行取得パターン。
# way_attribute_counts（事前集計）が該当osm_way_idを持たない場合（highway無し等で
# バッチのWHERE対象外だったway）は行自体が無くNoneを返す＝呼び出し元は「データ無し」として
# 扱う（0件と区別する。get_accident_counts等の「edge_id自体は必ず含まれ0埋め」とは異なる
# 単純な1行SELECTのため区別不要）。
_WAY_ATTRIBUTE_COUNTS_BY_OSM_WAY_ID_SQL = text(
    "SELECT length_m, accident_count, intersection_count, poi_counts "
    "FROM way_attribute_counts WHERE osm_way_id = :osm_way_id"
)


@dataclass(frozen=True, slots=True)
class WayMaterialSampleRow:
    """`sample_way_rows`が返す1行（軸スタジオの分布プレビューの母集団）。

    SQLの列別名と1対1で、値の解釈はしない。生の`Row`を返すと列別名がinfrastructureの
    外側の暗黙の契約になり、SQLを編集しても型では何も落ちない。
    """

    length_m: float | None
    highway: str | None
    tags: dict[str, str] | None
    # 舗装は専用列。tags jsonbには入らない（`domain/osm_adapter.py: ALLOWED_WAY_TAGS`）。
    surface: str | None
    counts_length_m: float | None
    accident_count: float | None
    intersection_count: int | None
    poi_counts: dict[str, int] | None
    # 配線済みクラス（`WIRED_LANDCOVER_KEYS`）→割合。way_landcoverの行が無ければNone。
    landcover_percents: dict[str, float] | None
    is_designated: bool


# 標本の土地被覆列。焼き込み列と同じく配線するクラスの並びから組み立てる——ここを手で
# 並べると、クラスを1つ配線したときに分布プレビューだけが古い並びで材料を組み立てる。
_LANDCOVER_SAMPLE_COLUMNS_SQL = "\n".join(f"        lc.{key}," for key in WIRED_LANDCOVER_KEYS)


def _landcover_percents_or_none(row: object) -> dict[str, float] | None:
    values = {key: getattr(row, key) for key in WIRED_LANDCOVER_KEYS}
    if all(value is None for value in values.values()):
        return None
    return {key: float(value or 0.0) for key, value in values.items()}


# 軸スタジオの分布プレビュー用。Way単位の材料をまとめて取る標本。取り方だけが2通りで、
# 取る列は共通のため1つのテンプレートから組み立てる。
_SAMPLE_WAY_MATERIALS_TEMPLATE = """
    SELECT
        ST_Length(w.geom::geography) AS length_m,
        w.highway,
        w.tags,
        w.surface,
        wc.length_m AS counts_length_m,
        wc.accident_count,
        wc.intersection_count,
        wc.poi_counts,
{landcover}
        EXISTS(
            SELECT 1 FROM designation_attributes da
            WHERE da.osm_way_id = w.osm_way_id AND da.kind = ANY(:kinds)
        ) AS is_designated
    FROM osm_raw_ways w {sampling}
    LEFT JOIN way_attribute_counts wc ON wc.osm_way_id = w.osm_way_id
    LEFT JOIN way_landcover lc ON lc.osm_way_id = w.osm_way_id
    WHERE w.geom IS NOT NULL AND w.highway IS NOT NULL {area}
    LIMIT :limit
"""

# 全域から取る場合。`TABLESAMPLE SYSTEM`はページ単位の抽選で、全表走査を避けつつ広い
# 範囲から拾える（行単位のBERNOULLIや`ORDER BY random()`は数百万行の全走査になり、
# 管理画面の応答時間に収まらない）。ページ単位のため地理的な偏りが残りうる点は、分布を
# 「目安」として扱う前提で許容する。
_SAMPLE_WAY_MATERIALS_SQL = text(
    _SAMPLE_WAY_MATERIALS_TEMPLATE.format(
        sampling="TABLESAMPLE SYSTEM (:sample_percent)", area="", landcover=_LANDCOVER_SAMPLE_COLUMNS_SQL
    )
).bindparams(bindparam("kinds", type_=ARRAY(Text())))

# 範囲を絞って取る場合。抽選と併用しない——`TABLESAMPLE`は表全体のページから抽選するため、
# 狭い範囲を重ねると当たるページがほとんど残らず、標本が範囲の広さに関係なく数本まで
# 落ちる。範囲内は空間索引で直接引き、多すぎる場合は`LIMIT`で頭打ちにする。
_SAMPLE_WAY_MATERIALS_IN_BBOX_SQL = text(
    _SAMPLE_WAY_MATERIALS_TEMPLATE.format(
        sampling="",
        area="AND w.geom && ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)",
        landcover=_LANDCOVER_SAMPLE_COLUMNS_SQL,
    )
).bindparams(bindparam("kinds", type_=ARRAY(Text())))



# 区間インスペクタの土地被覆。_WAY_ATTRIBUTE_COUNTS_BY_OSM_WAY_ID_SQLと同じ完全一致
# 1行取得パターン。表示に使うクラス以外も含めて全列を1回のSELECTで取る。
_WAY_LANDCOVER_BY_OSM_WAY_ID_SQL = text(
    "SELECT valid_pixels, water_percent, trees_percent, flooded_veg_percent, crops_percent, "
    "built_percent, bare_percent, snow_ice_percent, rangeland_percent, "
    "data_source, data_version, computed_at, source_osm_import_run_id, algorithm_version, "
    "source_raster_set "
    "FROM way_landcover WHERE osm_way_id = :osm_way_id"
)

# 車ストレスの区間別判定内訳表示。get_way_tags_by_osm_way_idが使う。
# 空間マッチをしない完全一致1行取得。
_WAY_TAGS_BY_OSM_WAY_ID_SQL = text(
    """
    SELECT
        w.highway,
        w.tags,
        w.surface,
        EXISTS(
            SELECT 1 FROM designation_attributes d
            WHERE d.osm_way_id = w.osm_way_id AND d.kind = ANY(:kinds)
        ) AS is_designated
    FROM osm_raw_ways w
    WHERE w.osm_way_id = :osm_way_id
    """
).bindparams(bindparam("kinds", type_=ARRAY(Text())))

def _meters_to_bbox_margin_deg(max_distance_m: float) -> float:
    """`&&`によるバウンディングボックス事前フィルタ用に、距離(m)を安全側の緯度経度差(度)へ
    変換する。1度=100,000mという（実際の111,000mより小さい＝度換算では大きい）保守的な
    換算を使い、経度方向の圧縮（高緯度ほど同じ距離が大きい経度差になる）を考慮しても
    日本の緯度帯（〜46度）で確実に対象を包含する余裕を持たせる（cos(46°)≈0.69のため
    最大でも約1.45倍の余裕があれば足りるところ、100,000/111,320≈0.9倍の余裕では
    不足するため、さらに絞らず全体に1/70,000という大きめの換算係数を使う）。"""
    return max_distance_m / 70_000.0


# 静的道路属性P1残り（intersectionDensity）。「次数3以上のNode」を交差点とみなす。
#
# 「この区間を走ると通る交差点」を数える。`build_road_graph`はwayが共有するノード
# （＝交差点になりうるノード）で必ず区間を切るため、交差点は区間の内部には現れず必ず端点に
# 来る。空間的な近傍探索は要らず、終点のノードが交差点かどうかだけで決まる。
#
# 数えるのは終点だけにする。1つの交差点は「手前の区間の終点」と「次の区間の始点」の
# 両方に現れるため、両端を数えるとルートに沿って二重に積まれる（停止要因POIが始点の
# ノードを除くのと同じ規則）。距離で数えていたときは、隣を平行に走る別の道路の交差点まで
# 計上されていた。
#
# 次数は`road_nodes.degree`（DB全体から見た真のグローバル次数、
# `precompute_road_node_degrees.py`が事前計算）を参照する。呼び出し元のedge_ids集合や
# チャンク分割からは独立する。
_INTERSECTION_COUNTS_SQL = text(
    """
    SELECT e.edge_id, COUNT(rn.node_id) AS intersection_count
    FROM road_edges e
    LEFT JOIN road_nodes rn
        ON rn.node_id = e.to_node_id
        AND rn.degree >= :degree_threshold
    WHERE e.edge_id = ANY(CAST(:edge_ids AS text[]))
    GROUP BY e.edge_id
    """
)

# raw_intersection_nodes（次数3以上の生OSMノード）の全再構築SQL。
# road_nodes.degree（Road Graph依存、ルート生成済みエリアのみ）と異なり、osm_raw_ways.
# node_idsの隣接関係から全域の次数を導出する。Wayの連続するnode_idペアを双方向に展開し、
# node単位でDISTINCT隣接node数を数える（同じ判定基準: 次数3以上=交差点。中間の形状点は
# 前後2ノードのみで次数2となり除外される）。highway無しのway（osm_raw_waysには原則
# 道路プロファイルのwayのみだが防御的に絞る）は隣接関係に含めない。
_REBUILD_RAW_INTERSECTION_NODES_SQL = text(
    """
    WITH adj AS (
        SELECT
            n.node_id,
            lead(n.node_id) OVER (PARTITION BY w.osm_way_id ORDER BY n.ord) AS neighbor_id
        FROM osm_raw_ways w
        CROSS JOIN LATERAL unnest(w.node_ids) WITH ORDINALITY AS n(node_id, ord)
        WHERE w.highway IS NOT NULL
    ),
    pairs AS (
        SELECT node_id, neighbor_id FROM adj
        WHERE neighbor_id IS NOT NULL AND neighbor_id <> node_id
        UNION
        SELECT neighbor_id AS node_id, node_id AS neighbor_id FROM adj
        WHERE neighbor_id IS NOT NULL AND neighbor_id <> node_id
    ),
    degrees AS (
        SELECT node_id, COUNT(DISTINCT neighbor_id) AS degree
        FROM pairs
        GROUP BY node_id
        HAVING COUNT(DISTINCT neighbor_id) >= :degree_threshold
    )
    INSERT INTO raw_intersection_nodes (osm_node_id, degree, geom)
    SELECT d.node_id, d.degree, rn.geom
    FROM degrees d
    JOIN osm_raw_nodes rn ON rn.osm_node_id = d.node_id
    """
)

# 上下線が分かれた道の相方を探す横方向の距離（m）。同じ路線番号/名前を持つ相方を探すとき
# （下記の条件2）に使う、緩めの上限。名前が一致している時点で同じ道路だとOSM自身が言って
# いるため、間隔そのものは広めに許す。
DIVIDED_CARRIAGEWAY_NAMED_GAP_M = 40.0
# 名前に頼らず幾何だけで判定するとき（条件3）の距離。上下線分離の間隔（幹線で中央値
# 10m前後）と、街区を挟んで並ぶ別々の一方通行路地の間隔（中央値20m弱）が分布として
# 分かれる、その谷間に置く値。
DIVIDED_CARRIAGEWAY_GEOMETRIC_GAP_M = 15.0
# 前置フィルタの箱を度へ直すときの、1度あたりの距離（m）。**距離の判定より必ず広い箱に
# なるよう小さめに取る**——箱の方が狭いと、距離をいくつに設定しても箱の大きさが実効の
# 上限になり、しきい値を緩めても何も変わらない。関東の緯度では
# 経度1度が89〜91kmのため、80,000mなら常に広い側へ倒れる。
DIVIDED_CARRIAGEWAY_PREFILTER_METERS_PER_DEGREE = 80_000.0
# 「逆向き」と見なす進行方位の差の許容（度、180度からのずれ）。カーブの途中で上下線の
# 向きがずれるぶんを吸収する。
DIVIDED_CARRIAGEWAY_BEARING_TOLERANCE_DEG = 45.0
# 「全長にわたって寄り添う」を確かめる標本点の位置（線長に対する割合）。端点ちょうどは
# 交差点で他の道と接するため avoid し、少し内側から取る。
DIVIDED_CARRIAGEWAY_SAMPLE_FRACTIONS = (0.05, 0.25, 0.5, 0.75, 0.95)
# OSMが「上下線が分かれている」と言っている carriageway の値（条件1）。
DIVIDED_CARRIAGEWAY_TAG_VALUES = ("dual", "triple", "2")

# way_divided_carriageway（上下線が分かれた道の片側か）の再計算
# （app/batch/precompute_way_divided_carriageway.py）。
#
# OSMは中央分離帯のある道路の上下線を別wayにしそれぞれへoneway=yesを付けるため、
# osm_raw_ways.directionだけでは一方通行規制の道と区別できない。判定は次の3条件のORで、
# 上から順に確からしい。
#
#   1. carriageway タグが dual/triple/2。OSM自身の申告で確実だが、関東全域で117件しか
#      無く（motorwayを除く。motorwayは自転車が走れず取り込んでいない）主軸にできない。
#   2. 同じ路線番号/名前（ref/name）の対向一方通行が近くにある。ref/nameの一致は
#      「この2本は同じ道路」というOSM側の明示で、最も強い同一性の根拠。上下線分離が
#      実際に起きる trunk/primary/secondary では一方通行wayの ref/name 欠損は0件のため、
#      その層はこの条件だけで捕捉できる。
#   3. 名前に頼らず、**全長にわたって**対向する同種別の一方通行が寄り添う。tertiaryは
#      無名の一方通行1,201本のうち689本（57%）がこれに該当し、条件2だけでは取りこぼす
#      （residential/unclassifiedの背景率2%台と桁が違うため、誤判定ではなく実体）。
#
# 条件3の掛け方に注意が要る。相方は1本とは限らない——上下線は別々の位置で分割されるため、
# 「標本点すべてが同一の相方から近い」と書くと分割位置のずれだけで落ちる。
# **点ごとに相方を探す**（EXISTSを点の内側へ入れる）こと。
#
# また、進行方位が反対であることは条件2・3の両方に要る。これが無いと、同じ道を分割した
# 連続する区間が端点を共有して距離0になり、すべて相方ありになる。
_WAY_TRAVEL_BEARING_SQL = """
    degrees(ST_Azimuth(ST_StartPoint({alias}.geom), ST_EndPoint({alias}.geom)))
        + CASE WHEN {alias}.direction = 'backward' THEN 180 ELSE 0 END
"""

_ANTIPARALLEL_SQL = """
    abs(
      ((({bearing}) - t.travel_deg)::numeric % 360 + 360) % 360 - 180
    ) < :bearing_tolerance_deg
""".format(bearing=_WAY_TRAVEL_BEARING_SQL.format(alias="b"))

# バインド変数は使わない。`:name::type`と書くとバインド名の直後のキャストが構文を壊し、
# バインド変数同士の割り算は型が決まらないため、定数からSQLへ直接展開する。
_sample_fractions_sql = ", ".join(str(f) for f in DIVIDED_CARRIAGEWAY_SAMPLE_FRACTIONS)
_named_prefilter_deg = DIVIDED_CARRIAGEWAY_NAMED_GAP_M / DIVIDED_CARRIAGEWAY_PREFILTER_METERS_PER_DEGREE
_geometric_prefilter_deg = (
    DIVIDED_CARRIAGEWAY_GEOMETRIC_GAP_M / DIVIDED_CARRIAGEWAY_PREFILTER_METERS_PER_DEGREE
)

_RECOMPUTE_WAY_DIVIDED_CARRIAGEWAY_SQL = text(
    f"""
    WITH target AS (
        SELECT w.osm_way_id, w.geom, w.direction, w.highway,
               lower(btrim(coalesce(w.tags->>'carriageway', ''))) AS carriageway,
               COALESCE(NULLIF(btrim(w.tags->>'ref'), ''), NULLIF(btrim(w.tags->>'name'), '')) AS ident,
               {_WAY_TRAVEL_BEARING_SQL.format(alias="w")} AS travel_deg
        FROM osm_raw_ways w
        WHERE w.osm_way_id = ANY(:osm_way_ids)
    )
    INSERT INTO way_divided_carriageway (
        osm_way_id, divided, computed_at, source_osm_import_run_id, algorithm_version
    )
    SELECT t.osm_way_id,
           t.direction <> 'both' AND t.travel_deg IS NOT NULL AND (
               -- 条件1: OSM自身の申告
               t.carriageway = ANY(:carriageway_values)
               -- 条件2: 同じ路線番号/名前の対向一方通行が近くにある
               OR (t.ident IS NOT NULL AND EXISTS (
                   SELECT 1 FROM osm_raw_ways b
                   WHERE b.osm_way_id <> t.osm_way_id
                     AND b.direction <> 'both'
                     AND COALESCE(NULLIF(btrim(b.tags->>'ref'), ''), NULLIF(btrim(b.tags->>'name'), ''))
                         = t.ident
                     AND b.geom && ST_Expand(t.geom, {_named_prefilter_deg})
                     AND ST_DWithin(t.geom::geography, b.geom::geography, :named_gap_m)
                     AND {_ANTIPARALLEL_SQL}
               ))
               -- 条件3: 全長にわたって対向する同種別の一方通行が寄り添う
               OR NOT EXISTS (
                   SELECT 1 FROM unnest(ARRAY[{_sample_fractions_sql}]::double precision[]) AS f
                   WHERE NOT EXISTS (
                       SELECT 1 FROM osm_raw_ways b
                       WHERE b.osm_way_id <> t.osm_way_id
                         AND b.direction <> 'both'
                         AND b.highway = t.highway
                         -- 名前が食い違う道どうしは対にしない（両方無名は許す）。
                         -- 主線に沿う側道を上下線の片側と見なさないため。
                         AND (COALESCE(NULLIF(btrim(b.tags->>'ref'), ''), NULLIF(btrim(b.tags->>'name'), ''))
                                IS NOT DISTINCT FROM t.ident
                              OR t.ident IS NULL
                              OR COALESCE(NULLIF(btrim(b.tags->>'ref'), ''),
                                          NULLIF(btrim(b.tags->>'name'), '')) IS NULL)
                         -- 前置フィルタは標本点まわりの小さな箱にする（wayの全体bboxで
                         -- 広げると長い道で候補が爆発する）。osm_raw_ways.geomのGiST
                         -- インデックスを使わせるためにあり、正確な距離は次の行が決める。
                         AND b.geom && ST_Expand(
                               ST_LineInterpolatePoint(t.geom, f), {_geometric_prefilter_deg})
                         AND ST_DWithin(
                               ST_LineInterpolatePoint(t.geom, f)::geography,
                               b.geom::geography, :geometric_gap_m)
                         AND {_ANTIPARALLEL_SQL}
                   )
               )
           ),
           :computed_at, :source_osm_import_run_id, :algorithm_version
    FROM target t
    ON CONFLICT (osm_way_id) DO UPDATE SET
        divided = EXCLUDED.divided,
        computed_at = EXCLUDED.computed_at,
        source_osm_import_run_id = EXCLUDED.source_osm_import_run_id,
        algorithm_version = EXCLUDED.algorithm_version
    """
).bindparams(bindparam("osm_way_ids", type_=ARRAY(BigInteger())))


# way_attribute_counts（way単位の事実カウント）の再計算SQL。
# カウントの意味論はedge単位版（_ACCIDENT_COUNTS_SQL/
# _INTERSECTION_COUNTS_SQL）と同一（半径・kindフィルタ・死亡事故重み・次数しきい値）で、
# 対象geometryだけがedge→way全体になる。`&&`前置・LATERALの流儀も既存クエリを踏襲。
# 事故はbicycle_only=true相当（involves_bicycleのみ）で固定する（edge版の実際の呼び出しが
# 常に既定値trueであるのと同じ判断、EdgeAttributeCountsRowのdocstring参照）。
_RECOMPUTE_WAY_ATTRIBUTE_COUNTS_SQL = text(
    """
    INSERT INTO way_attribute_counts
        (osm_way_id, length_m, accident_count, intersection_count, poi_counts, computed_at,
         source_accident_import_run_id, source_osm_import_run_id, algorithm_version)
    SELECT
        w.osm_way_id,
        ST_Length(w.geom::geography),
        COALESCE(acc.cnt, 0),
        COALESCE(ix.cnt, 0),
        COALESCE(pk.counts, '{}'::jsonb),
        :computed_at,
        :source_accident_import_run_id,
        :source_osm_import_run_id,
        :algorithm_version
    FROM osm_raw_ways w
    LEFT JOIN LATERAL (
        SELECT SUM(CASE WHEN a.fatal THEN :fatal_weight ELSE 1 END) AS cnt
        FROM accident_points a
        WHERE a.geom && ST_Expand(w.geom, :accident_distance_deg)
          AND ST_DWithin(a.geom::geography, w.geom::geography, :accident_distance_m)
          AND a.involves_bicycle
          AND (__NEAREST_WAY__) = w.osm_way_id
    ) acc ON true
    LEFT JOIN LATERAL (
        SELECT jsonb_object_agg(t2.kind, t2.cnt) AS counts
        FROM (
    __WAY_POI_BODY__
        ) t2
    ) pk ON true
    LEFT JOIN LATERAL (
        SELECT COUNT(*) AS cnt
        FROM raw_intersection_nodes i
        WHERE i.osm_node_id = ANY(w.node_ids)
    ) ix ON true
    WHERE w.osm_way_id = ANY(CAST(:osm_way_ids AS bigint[]))
      AND w.geom IS NOT NULL
      AND w.highway IS NOT NULL
    ON CONFLICT (osm_way_id) DO UPDATE SET
        length_m = EXCLUDED.length_m,
        accident_count = EXCLUDED.accident_count,
        intersection_count = EXCLUDED.intersection_count,
        poi_counts = EXCLUDED.poi_counts,
        computed_at = EXCLUDED.computed_at,
        source_accident_import_run_id = EXCLUDED.source_accident_import_run_id,
        source_osm_import_run_id = EXCLUDED.source_osm_import_run_id,
        algorithm_version = EXCLUDED.algorithm_version
    """.replace("__WAY_POI_BODY__", _poi_counts_body("w.node_ids", "w.node_ids[1]"))
    .replace("__NEAREST_WAY__", _NEAREST_WAY_FOR_ACCIDENT_SQL)
).bindparams(bindparam("stop_kinds", value=sorted(STOP_POI_KINDS), type_=ARRAY(Text())))

def _rows_to_road_graph(edge_rows: Iterable[RoadEdgeRow], node_rows: Iterable) -> RoadGraph:
    """`get_graph_in_bbox`用。Edgeが数万〜十数万行になる規模のため、`shapely.from_wkb()`の
    バッチAPI（GEOS呼び出しのループをPython側ではなくC側で回す）でgeometryを一括デコードし、
    Pydanticの`model_construct`（フィールド検証をスキップ。DB由来で型が保証済みのため安全）で
    DirectedEdgeを構築する（東京都心4km相当bbox、Edge151,820件・Node59,270件でCPU時間を
    約37%削減、6.11秒→3.84秒、backend/benchmarks/README.md参照）。

    `node_rows`は`Node`が`geometry`フィールドを持たない（`latitude`/`longitude`のみ）ことを
    踏まえ、`get_graph_topology_in_bbox`と同じくST_X/ST_Y列指定クエリの結果を受け取る
    （geom列自体のshapely decodeを丸ごと回避する）。
    """
    node_rows = list(node_rows)
    nodes = {
        row.node_id: Node.model_construct(
            node_id=row.node_id, latitude=row.latitude, longitude=row.longitude,
            osm_node_id=row.osm_node_id,
            has_traffic_signals=row.has_traffic_signals, max_highway_rank=row.max_highway_rank,
        )
        for row in node_rows
    }
    edges = _edge_rows_to_directed_edges(edge_rows)
    return RoadGraph(graph_version=CACHED_GRAPH_VERSION, nodes=nodes, edges=edges)


def _edge_rows_to_directed_edges(edge_rows: Iterable[RoadEdgeRow]) -> dict[str, DirectedEdge]:
    """`RoadEdgeRow`（geom込みの全カラム）のバッチをDirectedEdgeへ変換する共通ヘルパー
    （`_rows_to_road_graph`・`get_edges_with_geometry`が共有）。
    `shapely.from_wkb()`のバッチAPIで一括デコードする理由は`_rows_to_road_graph`の
    docstring参照。
    """
    edge_rows = list(edge_rows)
    edge_lines = shapely.from_wkb([bytes(row.geom.data) for row in edge_rows])
    return {
        row.edge_id: DirectedEdge.model_construct(
            edge_id=row.edge_id,
            from_node_id=row.from_node_id,
            to_node_id=row.to_node_id,
            # DirectedEdge.geometryは[[lat, lon], ...]だが、Shapely/PostGISの座標順は(lon, lat)。
            geometry=[[lat, lon] for lon, lat in line.coords],
            distance_m=row.distance_m,
            osm_way_id=row.osm_way_id,
            highway=row.highway,
            bearing_deg=row.bearing_deg,
        )
        for row, line in zip(edge_rows, edge_lines)
    }


def _topology_rows_to_road_graph(edge_rows: Iterable, node_rows: Iterable) -> LeanRoadGraph:
    """`get_graph_topology_in_bbox`用。`edge_rows`は
    `RoadEdgeRow`の全カラムではなく、探索に必要な列（geom以外）だけをSELECTした
    `Row`（SQLAlchemyの軽量タプル的な結果行）を想定する。geomカラムを一切
    SELECTしないため、`_rows_to_road_graph`が行うshapely decode（CPU時間の
    大半を占める、backend/benchmarks/README.md参照）が発生しない。
    `node_rows`も同様に`RoadNodeRow`の全カラムではなく、`node_id`・`osm_node_id`・
    `ST_X(geom)`（経度）・`ST_Y(geom)`（緯度）だけをSELECTした`Row`を想定する
    （geom列自体を取得してshapely decodeするより、PostGIS側でST_X/ST_Yを計算させ
    プレーンなfloatとして受け取る方が3倍以上速い）。

    戻り値は`RoadGraph`（Pydantic）ではなく`LeanRoadGraph`（dataclass、`domain/graph.py`）
    にする。`Node.model_construct`/`DirectedEdge.model_construct`自体（バリデーションを
    スキップしてもなおPydanticの内部簿記コストが残る）は、171,461Edge規模でDBクエリ本体
    （合計3.4秒）より支配的な11秒を占めるため、探索専用パスに限りPydanticを完全に外す。
    `LeanEdge.geometry`はプレースホルダの空リストにする（探索フェーズの評価関数は
    geometryを参照しない設計にしてある——風の材料評価（DYNAMIC_MATERIAL_EVALUATORS）は`bearing_deg`を
    直接使う、domain/evaluation.py参照。表示用の実ジオメトリが必要な最終候補は
    `get_edges_with_geometry`で別途取得する）。
    """
    nodes = {
        row.node_id: LeanNode(
            node_id=row.node_id, latitude=row.latitude, longitude=row.longitude,
            osm_node_id=row.osm_node_id,
            has_traffic_signals=row.has_traffic_signals, max_highway_rank=row.max_highway_rank,
        )
        for row in node_rows
    }
    edges = {
        row.edge_id: LeanEdge(
            edge_id=row.edge_id,
            from_node_id=row.from_node_id,
            to_node_id=row.to_node_id,
            geometry=[],
            distance_m=row.distance_m,
            osm_way_id=row.osm_way_id,
            highway=row.highway,
            bearing_deg=row.bearing_deg,
        )
        for row in edge_rows
    }
    return LeanRoadGraph(graph_version=CACHED_GRAPH_VERSION, nodes=nodes, edges=edges)


def _primary_way_conditions(envelope):
    """「主対象Way」＝bboxのenvelopeとST_Intersectsで交差するWay、を表すWHERE条件。
    `get_way_specs_with_closure`と`is_split_up_to_date`の両方が同じ「何が主対象Wayか」の
    定義を使う必要があるため、述語がずれないようここへ共通化する。
    """
    return (OsmRawWayRow.geom.is_not(None), func.ST_Intersects(OsmRawWayRow.geom, envelope))


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
    if not rows:
        return
    for chunk in _chunked(rows, _bulk_chunk_rows(rows)):
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


_STAGE_ROAD_NODES_DDL = (
    "CREATE TEMP TABLE IF NOT EXISTS _stage_road_nodes "
    "(node_id text, osm_node_id bigint, geom_wkb bytea) ON COMMIT DROP"
)
_MERGE_ROAD_NODES_SQL = (
    "INSERT INTO road_nodes (node_id, osm_node_id, geom, updated_at) "
    "SELECT node_id, osm_node_id, ST_GeomFromWKB(geom_wkb, 4326), $1 "
    "FROM _stage_road_nodes "
    "ON CONFLICT (node_id) DO UPDATE SET "
    "osm_node_id = EXCLUDED.osm_node_id, geom = EXCLUDED.geom, updated_at = EXCLUDED.updated_at"
)

_STAGE_ROAD_EDGES_DDL = (
    "CREATE TEMP TABLE IF NOT EXISTS _stage_road_edges "
    "(edge_id text, from_node_id text, to_node_id text, geom_wkb bytea, "
    "distance_m float8, osm_way_id bigint, highway text, bearing_deg float8) ON COMMIT DROP"
)
_MERGE_ROAD_EDGES_SQL = (
    "INSERT INTO road_edges "
    "(edge_id, from_node_id, to_node_id, geom, distance_m, osm_way_id, highway, bearing_deg, "
    "updated_at) "
    "SELECT edge_id, from_node_id, to_node_id, ST_GeomFromWKB(geom_wkb, 4326), "
    "distance_m, osm_way_id, highway, bearing_deg, $1 "
    "FROM _stage_road_edges "
    "ON CONFLICT (edge_id) DO UPDATE SET "
    "from_node_id = EXCLUDED.from_node_id, to_node_id = EXCLUDED.to_node_id, geom = EXCLUDED.geom, "
    "distance_m = EXCLUDED.distance_m, osm_way_id = EXCLUDED.osm_way_id, highway = EXCLUDED.highway, "
    "bearing_deg = EXCLUDED.bearing_deg, "
    "updated_at = EXCLUDED.updated_at"
)


async def _asyncpg_connection(session: AsyncSession):
    """SQLAlchemy `AsyncSession`の裏にある生のasyncpg接続を取得する。

    `_bulk_upsert`（複数行VALUESのINSERT ... ON CONFLICT、chunk=1000）は、都心規模
    （数万Node・十数万Edge）のsave_graphで数十秒〜数百秒かかりうる（王子30kmで
    edge_upsert_ms=149,235、Renderの約100秒プラットフォームタイムアウトに到達し完全
    失敗する場合もある）。PBF取込バッチ（app/batch/import_pbf.py）が既に使っている
    COPY（バイナリプロトコル、インデックス更新も1回のバルク処理にまとめられる）へ
    一時テーブル経由で置き換えることで、dev DBで5.6〜9.6倍の高速化を確認した
    （backend/benchmarks/bench_save_graph_copy.py、10km: 60.9秒→6.4秒、
    20km: 86.2秒→15.4秒）。

    SQLAlchemyの`AsyncSession`は「autobegin」のため、SQLAlchemy経由で何か実行するまで
    実トランザクション（BEGIN）がドライバへ送信されない。ここで軽いSELECTを1つ挟んで
    BEGINを確定させないと、`CREATE TEMP TABLE ... ON COMMIT DROP`が（asyncpg接続が
    autocommitのまま）即座にDROPされてしまい、直後のCOPYが存在しないテーブルへの
    アクセスになる。
    """
    await session.execute(text("SELECT 1"))
    raw_conn = await session.connection()
    pooled = await raw_conn.get_raw_connection()
    return pooled.driver_connection


async def _copy_upsert_road_nodes(session: AsyncSession, nodes: Iterable[NodeLike], now: datetime) -> None:
    records = [
        (node.node_id, node.osm_node_id, shapely.to_wkb(Point(node.longitude, node.latitude)))
        for node in nodes
    ]
    if not records:
        return
    conn = await _asyncpg_connection(session)
    await conn.execute(_STAGE_ROAD_NODES_DDL)
    await conn.execute("TRUNCATE _stage_road_nodes")
    await conn.copy_records_to_table(
        "_stage_road_nodes", records=records, columns=["node_id", "osm_node_id", "geom_wkb"]
    )
    await conn.execute(_MERGE_ROAD_NODES_SQL, now)


async def _copy_upsert_road_edges(session: AsyncSession, edges: Iterable[EdgeLike], now: datetime) -> None:
    records = [
        (
            edge.edge_id,
            edge.from_node_id,
            edge.to_node_id,
            shapely.to_wkb(LineString([(lon, lat) for lat, lon in edge.geometry])),
            edge.distance_m,
            edge.osm_way_id,
            edge.highway,
            edge.bearing_deg,
        )
        for edge in edges
    ]
    if not records:
        return
    conn = await _asyncpg_connection(session)
    await conn.execute(_STAGE_ROAD_EDGES_DDL)
    await conn.execute("TRUNCATE _stage_road_edges")
    await conn.copy_records_to_table(
        "_stage_road_edges",
        records=records,
        columns=[
            "edge_id", "from_node_id", "to_node_id", "geom_wkb",
            "distance_m", "osm_way_id", "highway", "bearing_deg",
        ],
    )
    await conn.execute(_MERGE_ROAD_EDGES_SQL, now)


class _SessionRepository:
    """1リクエスト（1トランザクション）につき1インスタンスを想定し、`AsyncSession`を
    DIで受け取る共通基底。commitは持たない（モジュールdocstringの規約参照）。"""

    def __init__(self, session: AsyncSession):
        self._session = session


# road_nodes.degree（DB全体から見た真のグローバル次数）の事前集計SQL。
# road_edges全件（呼び出し元の集合ではなくDB全体）から次数を計算するため、
# recompute_node_degrees()の呼び出し元やチャンク分割から独立した決定的な値になる。
# backend/app/batch/precompute_road_node_degrees.pyが本メソッドを呼び出す
# （新しいSQLを二重に持たない、既存の各precomputeバッチと同じ規約）。
_RECOMPUTE_NODE_DEGREES_SQL = text(
    """
    WITH endpoints AS (
        SELECT from_node_id AS node_id, to_node_id AS neighbor_id FROM road_edges
        UNION
        SELECT to_node_id AS node_id, from_node_id AS neighbor_id FROM road_edges
    ),
    degrees AS (
        SELECT node_id, COUNT(DISTINCT neighbor_id) AS degree
        FROM endpoints
        GROUP BY node_id
    )
    UPDATE road_nodes rn
    SET degree = COALESCE(d.degree, 0)
    FROM degrees d
    WHERE rn.node_id = d.node_id
    """
)

# ノードに集まる道の最大階級。`HIGHWAY_RANK`（domain/traffic.py）をそのままCASEへ写す
# ——同じ順位表をSQL側へ書き写さないため、本文はPythonの辞書から組み立てる。
_HIGHWAY_RANK_SQL_CASE = "CASE e.highway\n" + "\n".join(
    f"            WHEN '{highway}' THEN {rank}" for highway, rank in sorted(HIGHWAY_RANK.items())
) + "\n            ELSE 0\n        END"

# 全件版（バッチ）とノード限定版（分割直後の穴埋め）で対象の絞り方だけが違うため、
# 1つのテンプレートから組み立てる。
_RECOMPUTE_NODE_MAX_HIGHWAY_RANK_TEMPLATE = """
    WITH endpoints AS (
        SELECT from_node_id AS node_id, __RANK__ AS rank FROM road_edges e {from_scope}
        UNION ALL
        SELECT to_node_id AS node_id, __RANK__ AS rank FROM road_edges e {to_scope}
    ),
    ranks AS (
        SELECT node_id, MAX(rank) AS max_rank FROM endpoints GROUP BY node_id
    )
    UPDATE road_nodes rn
    SET max_highway_rank = COALESCE(r.max_rank, 0)
    FROM ranks r
    WHERE rn.node_id = r.node_id {node_scope}
      AND rn.max_highway_rank IS DISTINCT FROM COALESCE(r.max_rank, 0)
    """.replace("__RANK__", _HIGHWAY_RANK_SQL_CASE)

_RECOMPUTE_NODE_MAX_HIGHWAY_RANK_SQL = text(
    _RECOMPUTE_NODE_MAX_HIGHWAY_RANK_TEMPLATE.format(from_scope="", to_scope="", node_scope="")
)

_RECOMPUTE_NODE_MAX_HIGHWAY_RANK_FOR_NODES_SQL = text(
    _RECOMPUTE_NODE_MAX_HIGHWAY_RANK_TEMPLATE.format(
        from_scope="WHERE e.from_node_id = ANY(:node_ids)",
        to_scope="WHERE e.to_node_id = ANY(:node_ids)",
        node_scope="AND rn.node_id = ANY(:node_ids)",
    )
)

# ノードに信号があるか。信号は交差点そのもののノードではなく、流入路ごと・横断歩道位置ごとの
# 別ノードとして描かれるため、`osm_node_id`の一致では大半を取りこぼす。較正値の宣言が持つ
# 「信号とみなす半径」で拾う。
# 判定に使うkindは`_POI_COUNT_KIND_EXPR`と同じ規則（`traffic_signals`と、信号付きの
# `crossing`の2通りの書かれ方）。
_RECOMPUTE_NODE_TRAFFIC_SIGNALS_SQL = text(
    """
    WITH signals AS (
        SELECT p.geom FROM osm_raw_pois p
        WHERE p.kind = 'traffic_signals'
           OR (p.kind = 'crossing' AND p.tags->>'crossing' LIKE '%signals%')
    ),
    flagged AS (
        SELECT rn.node_id,
               EXISTS (
                   SELECT 1 FROM signals s
                   WHERE s.geom && ST_Expand(rn.geom::geometry, :signal_radius_deg)
                     AND ST_DWithin(s.geom::geography, rn.geom::geography, :signal_radius_m)
               ) AS has_signal
        FROM road_nodes rn
        WHERE rn.node_id = ANY(:node_ids)
    )
    UPDATE road_nodes rn
    SET has_traffic_signals = f.has_signal
    FROM flagged f
    WHERE rn.node_id = f.node_id
      AND rn.has_traffic_signals IS DISTINCT FROM f.has_signal
    """
)


def signal_radius_params() -> dict[str, float]:
    """信号判定の半径を、上のSQLが取るパラメータへ落とす。

    **`POI_CLUSTER_EPS_M`ではなく較正値の宣言を読む**——いまは同じ値だが別の問いで、
    片方を動かしたときにもう片方が一緒に動いてはいけない。
    """
    radius_m = tuning_value("signal.match_radius_m")
    return {
        "signal_radius_m": radius_m,
        # `&&`でGiST索引を先に効かせるための粗い矩形。緯度1度≒111kmで換算し、経度側が
        # 狭くなる高緯度でも取りこぼさないよう余裕を持たせる。
        "signal_radius_deg": radius_m / 111_000.0 * 2.0,
    }


# road_edgesから一切参照されないnode（孤立点、通常は発生しないが防御的に0へ戻す）。
_RESET_UNREFERENCED_NODE_DEGREES_SQL = text(
    """
    UPDATE road_nodes rn
    SET degree = 0
    WHERE rn.degree <> 0
      AND NOT EXISTS (
          SELECT 1 FROM road_edges e
          WHERE e.from_node_id = rn.node_id OR e.to_node_id = rn.node_id
      )
    """
)


class DerivedGraphRepository(_SessionRepository):
    """派生グラフ（road_nodes/road_edges、交差点分割の結果）の読み書きと鮮度判定。"""

    async def recompute_node_degrees(self) -> None:
        """road_nodes.degreeをroad_edges全件から再計算する。

        呼び出し元の集合に依存しないDB全体集計のため、road_edgesが変わった場合
        （PBF再取込等）は都度呼び直す必要がある派生データ（`edge_attribute_counts`と同じ
        「精密テーブル/列、バッチで再計算」パターン）。get_intersection_counts等が
        参照する`road_nodes.degree`は、本メソッドを呼ぶまでは新規ノードの初期値0のまま。
        """
        await self._session.execute(_RECOMPUTE_NODE_DEGREES_SQL)
        await self._session.execute(_RESET_UNREFERENCED_NODE_DEGREES_SQL)

    async def recompute_node_max_highway_rank(self, node_ids: list[str] | None = None) -> None:
        """road_nodes.max_highway_rankをroad_edgesから再計算する。

        `node_ids`を渡すとそのノードだけを対象にする（分割直後の穴埋め。全件版は
        road_edges全行を走査するためリクエストの経路では使えない）。
        """
        if node_ids is None:
            await self._session.execute(_RECOMPUTE_NODE_MAX_HIGHWAY_RANK_SQL)
            return
        if not node_ids:
            return
        for chunk in _chunked(node_ids, _NODE_ATTRIBUTE_CHUNK_SIZE):
            await self._session.execute(
                _RECOMPUTE_NODE_MAX_HIGHWAY_RANK_FOR_NODES_SQL, {"node_ids": list(chunk)}
            )

    async def recompute_node_intersection_attributes(self, node_ids: list[str]) -> None:
        """渡したノードの交差点属性（信号の有無・集まる道の最大階級）を再計算する。

        この2列は事前集計バッチ（`precompute_road_node_intersections.py`）が埋めるが、
        **交差点分割が新しく作ったノードはそのバッチをまだ受けていない**。分割した側が
        自分の作ったノードを埋めないと、ターンの費用が「信号が無いのに上位の道を渡る」
        側へ倒れ、同じ地点でも構築経路によって所要時間が変わる。
        """
        if not node_ids:
            return
        await self.recompute_node_max_highway_rank(node_ids)
        for chunk in _chunked(node_ids, _NODE_ATTRIBUTE_CHUNK_SIZE):
            await self.recompute_node_traffic_signals(list(chunk))

    async def get_node_intersection_attributes(
        self, node_ids: list[str]
    ) -> dict[str, tuple[bool, int]]:
        """node_id → (信号があるか, 集まる道の最大階級)。行が無いnode_idは含めない。"""
        out: dict[str, tuple[bool, int]] = {}
        for chunk in _chunked(node_ids, _NODE_ATTRIBUTE_CHUNK_SIZE):
            stmt = select(
                RoadNodeRow.node_id, RoadNodeRow.has_traffic_signals, RoadNodeRow.max_highway_rank
            ).where(RoadNodeRow.node_id == any_(cast(list(chunk), ARRAY(Text))))
            for row in (await self._session.execute(stmt)).all():
                out[row.node_id] = (bool(row.has_traffic_signals), int(row.max_highway_rank or 0))
        return out

    async def recompute_node_traffic_signals(self, node_ids: list[str]) -> None:
        """渡したノードのroad_nodes.has_traffic_signalsをosm_raw_poisから再計算する。

        半径での空間結合のため、全件を1文で処理するとプラン次第で全組み合わせ評価に落ちる
        （`get_intersection_counts`と同じ事情）。呼び出し側がノードを分割して渡す。
        """
        if not node_ids:
            return
        await self._session.execute(
            _RECOMPUTE_NODE_TRAFFIC_SIGNALS_SQL, {"node_ids": node_ids, **signal_radius_params()}
        )

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
        # `Node`は`latitude`/`longitude`のみを持ち`geometry`フィールドを持たない
        # （`DirectedEdge`と異なりgeom列自体を必要としない）ため、`get_graph_topology_in_bbox`
        # と同じくPostGIS側でST_X/ST_Yを計算させプレーンなfloatとして受け取り、
        # shapely decodeを回避する。
        node_rows = []
        for id_chunk in _chunked(node_ids, 50_000):
            node_stmt = select(
                RoadNodeRow.node_id,
                RoadNodeRow.osm_node_id,
                func.ST_X(RoadNodeRow.geom).label("longitude"),
                func.ST_Y(RoadNodeRow.geom).label("latitude"),
                RoadNodeRow.has_traffic_signals,
                RoadNodeRow.max_highway_rank,
            ).where(RoadNodeRow.node_id == any_(cast(id_chunk, ARRAY(Text))))
            node_rows.extend((await self._session.execute(node_stmt)).all())

        # 密集した都市部のbboxではEdge/Nodeが数万〜十数万行になり、shapelyへのgeometry
        # decode（to_shape）だけで数秒〜十数秒のCPU処理になる（bench_postgis_prepare.py
        # 計測でこの呼び出し単体13.3秒、東京都心4km相当bbox・Edge151,820件）。
        # asyncio.to_threadで逃さないとイベントループを塞ぐ。
        return await asyncio.to_thread(_rows_to_road_graph, edge_rows, node_rows)

    async def get_graph_topology_in_bbox(self, bbox: BoundingBox) -> LeanRoadGraph | None:
        """`get_graph_in_bbox`の軽量版。探索フェーズ
        （Dijkstra経路選択）はEdgeのトポロジ（from/to node・distance・bearing等）だけ
        あれば成立し、geometry（形状点列）は不要（domain/evaluation.py:
        風の材料評価はbearing_degを直接使う設計のため）。

        `geom`カラム自体をSELECT対象から外すことで、shapelyへのgeometry decode
        （`_rows_to_road_graph`のコメント参照、CPU時間の大半を占める）を
        丸ごと回避する。返す`RoadGraph`の`DirectedEdge.geometry`は空リストの
        プレースホルダ（`_topology_rows_to_road_graph`参照）。

        最終候補（距離フィルタ通過後の経路）のEdgeについては、表示・区間詳細の
        構築に実ジオメトリが必要なため、別途`get_edges_with_geometry`で取得し直す
        （`GraphService.get_edges_with_geometry`・`RoadGraphEngine.trace_loop`参照）。
        """
        envelope = func.ST_MakeEnvelope(
            bbox.min_longitude, bbox.min_latitude, bbox.max_longitude, bbox.max_latitude, 4326
        )
        edge_stmt = select(
            RoadEdgeRow.edge_id,
            RoadEdgeRow.from_node_id,
            RoadEdgeRow.to_node_id,
            RoadEdgeRow.distance_m,
            RoadEdgeRow.osm_way_id,
            RoadEdgeRow.highway,
            RoadEdgeRow.bearing_deg,
        ).where(func.ST_Intersects(RoadEdgeRow.geom, envelope))
        edge_rows = (await self._session.execute(edge_stmt)).all()
        if not edge_rows:
            return None

        node_ids = sorted({row.from_node_id for row in edge_rows} | {row.to_node_id for row in edge_rows})
        # `select(RoadNodeRow)`（geom列込みのORM行）+shapely decodeは、
        # 緯度経度だけが目的の探索フェーズには過剰なコスト（dev DBで
        # 68,760件でORM+shapely decode 2.76秒 → ST_X/ST_Y列指定0.89秒、3.1倍）。
        # PostGIS側でST_X/ST_Yを計算させ、緯度経度をプレーンなfloatとして直接受け取る
        # ことでshapely decode自体を丸ごと回避する。
        node_rows = []
        for id_chunk in _chunked(node_ids, 50_000):
            node_stmt = select(
                RoadNodeRow.node_id,
                RoadNodeRow.osm_node_id,
                func.ST_X(RoadNodeRow.geom).label("longitude"),
                func.ST_Y(RoadNodeRow.geom).label("latitude"),
                RoadNodeRow.has_traffic_signals,
                RoadNodeRow.max_highway_rank,
            ).where(RoadNodeRow.node_id == any_(cast(id_chunk, ARRAY(Text))))
            node_rows.extend((await self._session.execute(node_stmt)).all())

        return await asyncio.to_thread(_topology_rows_to_road_graph, edge_rows, node_rows)

    async def get_edges_with_geometry(self, edge_ids: list[str]) -> dict[str, DirectedEdge]:
        """指定edge_idぶんだけ、実ジオメトリ込みのDirectedEdgeを取得する。
        `get_graph_topology_in_bbox`でgeometry抜きに読み込んだ探索用グラフから、
        Dijkstraで確定した経路（1候補あたり数十〜数百Edge）だけへ絞ってgeometryを
        取得し直す用途。bbox全件（数万〜十数万Edge）のdecodeを避けつつ、区間詳細
        表示に必要な実ジオメトリは確保する。
        """
        if not edge_ids:
            return {}
        edges: dict[str, DirectedEdge] = {}
        for id_chunk in _chunked(edge_ids, 50_000):
            edge_stmt = select(RoadEdgeRow).where(RoadEdgeRow.edge_id == any_(cast(id_chunk, ARRAY(Text))))
            edge_rows = (await self._session.execute(edge_stmt)).scalars().all()
            edges.update(await asyncio.to_thread(_edge_rows_to_directed_edges, edge_rows))
        return edges


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

    async def save_graph(self, graph: RoadGraphLike, way_ids_to_replace: set[int] | None = None) -> None:
        """RoadGraphをroad_nodes/road_edgesへ永続化する。

        引数は`RoadGraph`ではなく`RoadGraphLike`（`Node`/`DirectedEdge`の
        Pydantic版・`LeanNode`/`LeanEdge`のdataclass版いずれも受け付ける構造的型）。
        本メソッドは`graph.nodes`/`graph.edges`とその属性（node_id/latitude/longitude等）を
        読むだけでPydantic固有機能に依存していないため、呼び出し元
        （`GraphService.get_or_build_graph_with_attributes`）が返すLeanRoadGraphを
        そのまま渡せる。

        `way_ids_to_replace`を指定した場合、それらのosm_way_idを持つ既存Edge行のうち
        「今回のgraphに同じedge_idで含まれないもの」だけを削除してから`graph`内の該当Edgeを
        UPSERTする（全削除→無条件再挿入だと、分割結果が前回と変わらない
        大多数のケースでも同じedge_idの行がDELETE→INSERTを経由してしまい、
        `ON DELETE CASCADE`のEdge派生属性（elevation_attributes等）が巻き添えで
        消える。edge_idは決定論的なため、分割結果が変わらなければ削除自体が不要。
        なおdesignation_attributesはosm_raw_ways基準のWay派生のため、
        Edgeの再splitでは影響を受けない）。
        `build_road_graph`は渡されたWay集合全体から交差点を再計算するため、
        Wayの分割結果が実際に変わっていた場合は、古い分割によるEdge行（新graphに
        存在しないedge_id）を削除して孤立させない（タイル境界依存の分割不一致問題への
        対応、本ファイル冒頭のdocstring参照）。`way_ids_to_replace`外のosm_way_idを持つEdge
        （closureで近傍として取得しただけのWay）はこの呼び出しでは保存しない
        （不完全な文脈で計算した分割結果によって、他のリクエストが正しく永続化した
        Edgeを誤って上書き・破壊しないため）。
        Noneの場合は`graph`内の全Edgeを単純にUPSERTする。

        `way_ids_to_replace`指定時は、その各osm_way_idについて`osm_raw_ways.split_at`も
        この時刻へ更新する（`is_split_up_to_date`の鮮度判定に使う。Edgeを1件も生成しなかった
        Wayでもスタンプする点に注意。road_graph_models.py: OsmRawWayRowのdocstring参照）。
        """
        started = time.monotonic()
        now = datetime.now(timezone.utc)
        # Edgeがroad_nodes.node_idを外部キー参照するため、先にNodeを一括UPSERTする
        # （同一トランザクション内のため文の実行順で制約を満たせる）。
        # 複数行VALUESのON CONFLICT（`_bulk_upsert`）は都心規模で
        # 数十秒〜数百秒かかるため、COPY経由の一時テーブルUPSERT（`_copy_upsert_road_nodes`/
        # `_copy_upsert_road_edges`、詳細は`_asyncpg_connection`のdocstring参照）へ置き換えた。
        await _copy_upsert_road_nodes(self._session, graph.nodes.values(), now)
        node_upsert_ms = round((time.monotonic() - started) * 1000)

        edges_to_save = [
            edge
            for edge in graph.edges.values()
            if way_ids_to_replace is None or edge.osm_way_id in way_ids_to_replace
        ]

        delete_started = time.monotonic()
        if way_ids_to_replace:
            new_edge_ids = sorted({edge.edge_id for edge in edges_to_save})
            # `new_edge_ids`（再構築対象の全edge_id、都心密度で数万件）を
            # `.not_in(...)`で素朴にIN句化すると、`id_chunk`（最大_ID_CHUNK_SIZE件）との
            # 合算でasyncpgのプリペアド文パラメータ上限（32,767個）を超えうる。
            # `=ANY(配列)`は要素数に関わらず1パラメータのため、
            # 本ファイルの他の大量ID参照（get_edge_attribute_counts等）と同じ
            # `=ANY(配列)`パターンへ揃える（`NOT (edge_id = ANY(配列))`でNOT IN相当）。
            #
            # ただし`NOT (edge_id = ANY(配列))`除外条件は、広域bbox（`new_edge_ids`が
            # 数十万件規模）の場合、チャンク（`id_chunk`、最大_ID_CHUNK_SIZE件ずつ）
            # 1回ごとに同じ巨大な配列フィルタを毎回再評価してしまい、チャンク数に比例して
            # 悪化する遅延を引き起こす。除外側集合を一時テーブルへ1回だけ投入・
            # PKインデックス化し、各チャンクのDELETEは`NOT EXISTS`（インデックスを使う反結合）
            # で参照する形にすることで、チャンク数ぶんの重複評価を無くす。
            if new_edge_ids:
                # 一時テーブルとroad_edgesのハッシュ結合サイズはwork_mem既定値
                # (4MB、tile配信保護用のget_engine()と共有する設定、database.pyの
                # コメント参照)を要素数万件規模で超えうる（76,221行のハッシュで5.5MB）。
                # 広域bbox（数十万件規模）ではさらに上回りディスクスピルが起きうる。
                # この操作専用にトランザクションローカルで
                # work_memを引き上げる（`SET LOCAL`のためこのトランザクション終了時に
                # 自動的に既定値へ戻り、他セッション・他クエリには影響しない）。
                await self._session.execute(text("SET LOCAL work_mem = '256MB'"))
                await self._session.execute(text("DROP TABLE IF EXISTS tmp_save_graph_new_edge_ids"))
                await self._session.execute(
                    text(
                        "CREATE TEMP TABLE tmp_save_graph_new_edge_ids (edge_id TEXT PRIMARY KEY) ON COMMIT DROP"
                    )
                )
                await self._session.execute(
                    text(
                        "INSERT INTO tmp_save_graph_new_edge_ids (edge_id) "
                        "SELECT unnest(CAST(:new_edge_ids AS TEXT[]))"
                    ),
                    {"new_edge_ids": new_edge_ids},
                )

            for id_chunk in _chunked(sorted(way_ids_to_replace), _ID_CHUNK_SIZE):
                # 今回も同じedge_idで再挿入される行はDELETE対象から除外する（上記docstring
                # 参照）。new_edge_idsが空（対象way群がEdgeを1件も生成しなかった）場合は
                # 除外条件自体を付けず全削除相当のままで問題ない。
                if new_edge_ids:
                    await self._session.execute(
                        text(
                            "DELETE FROM road_edges "
                            "WHERE road_edges.osm_way_id = ANY(CAST(:id_chunk AS BIGINT[])) "
                            "AND NOT EXISTS ("
                            "SELECT 1 FROM tmp_save_graph_new_edge_ids t "
                            "WHERE t.edge_id = road_edges.edge_id"
                            ")"
                        ),
                        {"id_chunk": id_chunk},
                    )
                else:
                    await self._session.execute(
                        delete(RoadEdgeRow).where(
                            RoadEdgeRow.osm_way_id == any_(cast(id_chunk, ARRAY(BigInteger)))
                        )
                    )
                await self._session.execute(
                    update(OsmRawWayRow)
                    .where(OsmRawWayRow.osm_way_id == any_(cast(id_chunk, ARRAY(BigInteger))))
                    .values(split_at=now)
                )
        delete_ms = round((time.monotonic() - delete_started) * 1000)

        edge_upsert_started = time.monotonic()
        await _copy_upsert_road_edges(self._session, edges_to_save, now)
        edge_upsert_ms = round((time.monotonic() - edge_upsert_started) * 1000)
        total_ms = round((time.monotonic() - started) * 1000)

        # 高コスト処理のステージ別所要時間サマリ（docs/logging.md）。この経路は低頻度だが、
        # 未splitエリアの初回タッチ時に重くなりうるため、長時間化の発生自体・どの段が
        # 支配的かを都度検知できるようにする。
        logger.info(
            "save_graph nodes=%d edges=%d way_ids_to_replace=%s "
            "node_upsert_ms=%d delete_ms=%d edge_upsert_ms=%d total_ms=%d",
            len(graph.nodes), len(edges_to_save),
            len(way_ids_to_replace) if way_ids_to_replace else 0,
            node_upsert_ms, delete_ms, edge_upsert_ms, total_ms,
        )


# get_distinct_material_valuesが対応する材料id→SQL式（正規化含む）。
# 新しい材料をこの一覧へ追加する場合、_ROAD_SURFACE_TILE_MVT_SQLの対応する正規化式と
# 揃えること（test_road_graph_repository.pyの整合性テスト参照）。値はosm_raw_waysの列名
# ・JSONB参照のみで構成された固定リテラルで、外部入力を連結しない（SQLインジェクション対象外）。
_MATERIAL_VALUE_COLUMN_EXPR: dict[str, str] = {
    "highway": HIGHWAY_SQL,
    "surface": SURFACE_NORMALIZED_SQL,
    "smoothness": SMOOTHNESS_NORMALIZED_SQL,
}


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

        次の空間検索を使う（geom列＝Phase 1で追加した実体化済みLINESTRINGが前提。
        NULLのままの旧データはcreate_tablesのバックフィルで補われる）:

        1. 主対象Way: bboxのenvelopeとST_Intersectsで交差するWay（頂点がbbox内に無くても
           bboxを横切るWayを含む）
        2. 近傍Way: 主対象Way全体のextent（全長分の外接矩形、bbox外の部分も含む。
           NEIGHBOR_EXTENT_MAX_MARGIN_M分だけ拡張した要求bboxへクランプ済み）と交差する
           Way。「主対象とノードを共有するWay」の厳密な
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
        # extentを要求bboxをNEIGHBOR_EXTENT_MAX_MARGIN_M分だけ拡張した範囲へ
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
        # 行から`WaySpec`への変換は`geom`列を一切参照しない
        # （osm_way_id/node_ids/highway/surface/tags/directionのみ）。にもかかわらず
        # `select(OsmRawWayRow)`は全列（geom＝LINESTRING込み）をORM行として取得すると、
        # DBサーバー側の実行自体はEXPLAIN ANALYZEで112msしかかからないのに対し、
        # closure_ms全体は9.7秒（約85倍、宇都宮30km・primary_ways=35,725の例）になりうる。
        # `get_graph_topology_in_bbox`がEdge側で既にgeom列を除外しているのと同じ
        # パターンで、Way側にも列指定クエリを適用してORM行構築・shapely decode・
        # ネットワーク転送量を削減する。WHERE句自体はgeom列を条件に使い続けてよい
        # （SELECTする列と条件に使う列は独立）。
        way_stmt = select(
            OsmRawWayRow.osm_way_id,
            OsmRawWayRow.node_ids,
            OsmRawWayRow.highway,
            OsmRawWayRow.surface,
            OsmRawWayRow.tags,
            OsmRawWayRow.direction,
        ).where(OsmRawWayRow.geom.is_not(None), func.ST_Intersects(OsmRawWayRow.geom, extent_envelope))
        way_rows = (await self._session.execute(way_stmt)).all()
        way_specs = [
            WaySpec(
                osm_way_id=row.osm_way_id,
                node_ids=list(row.node_ids),
                highway=row.highway,
                surface=row.surface,
                tags=row.tags or {},
                direction=row.direction,
            )
            for row in way_rows
        ]

        # ノード座標はWayが実際に参照するIDで正確に引く（=ANY(配列)は1パラメータで済み、
        # IN句のようなパラメータ数上限の問題を起こさない）。
        # ここも呼び出し元が緯度経度のみを必要とし`geom`（WKB）自体は
        # 不要なため、`select(OsmRawNodeRow)`（全列＋`to_shape`によるshapely decode）を
        # ST_X/ST_Y列指定へ変更する（way_stmt・get_graph_in_bboxのnode_stmtと同じ対応）。
        final_node_ids = sorted({node_id for way in way_specs for node_id in way.node_ids})
        node_coords: dict[int, tuple[float, float]] = {}
        for id_chunk in _chunked(final_node_ids, 50_000):
            node_stmt = select(
                OsmRawNodeRow.osm_node_id,
                func.ST_X(OsmRawNodeRow.geom).label("longitude"),
                func.ST_Y(OsmRawNodeRow.geom).label("latitude"),
            ).where(OsmRawNodeRow.osm_node_id == any_(cast(id_chunk, ARRAY(BigInteger))))
            for row in (await self._session.execute(node_stmt)).all():
                node_coords[row.osm_node_id] = (row.latitude, row.longitude)

        return way_specs, node_coords, primary_way_ids


    async def get_cached_tiles(self, zoom: int, tiles: list[tuple[int, int]]) -> set[tuple[int, int]]:
        """指定タイル群のうち、取込済み（`road_graph_tiles`に存在する）ものの(x,y)集合を返す
        （タイル数ぶん個別に問い合わせるループを集約するため。半径10kmの起点1件で
        6回の個別往復が発生しうる）。

        `road_graph_tiles`は1,000行規模の小さなテーブルで、この問い合わせ自体が数ミリ秒で
        終わる（docs/caching.md「判断をキャッシュしてよい条件」参照）。
        """
        if not tiles:
            return set()
        stmt = select(RoadGraphTileRow.x, RoadGraphTileRow.y).where(
            RoadGraphTileRow.zoom == zoom, tuple_(RoadGraphTileRow.x, RoadGraphTileRow.y).in_(tiles)
        )
        rows = (await self._session.execute(stmt)).all()
        return {(row.x, row.y) for row in rows}

    async def get_distinct_material_values(self, material_id: str) -> list[str]:
        """軸スタジオ（AxisComposer.tsx）の値入力UX向け。highway/surface/
        smoothnessのようなオープンエンドな多値材料は事前に全量を静的に列挙できないため、
        実際にDBへ取り込まれている値をここで動的取得する。

        正規化は`infrastructure/osm_way_tag_sql.py`の共有断片（`_ROAD_SURFACE_TILE_MVT_SQL`
        [RoadSurfaceTileQuery]・`material_coverage.py`と共通）を使う（surface/smoothnessは
        `lower(btrim(...))`、highwayは生値のまま——OSM取込プロファイル
        [`batch/import_profile.yaml`のhighway許可リスト]で既に許可リスト化された正準値の
        ため正規化不要）。単純な
        `SELECT DISTINCT`で足りる
        （複雑な優先順位付き分類を要する材料はこの対象外、
        material_catalog.pyのdisplay_only/dtype="categorical"のうち事前に閉じた値集合を
        持つ材料は本APIを使う必要が無い）。未対応の`material_id`は空リストを返す
        （呼び出し元のrouterが404を判断する）。
        """
        column_expr = _MATERIAL_VALUE_COLUMN_EXPR.get(material_id)
        if column_expr is None:
            return []
        result = await self._session.execute(
            text(
                f"SELECT DISTINCT {column_expr} AS value FROM osm_raw_ways AS w "  # noqa: S608 固定の内部辞書のみ使用、外部入力を連結しない
                f"WHERE {column_expr} IS NOT NULL ORDER BY value"
            )
        )
        return [row.value for row in result]


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
        返す。get_road_surface_tile_mvtと同じ契約（カバレッジ外はNone、カバレッジ内で
        対象0件は空バイト列）。クエリの設計意図は_POI_TILE_MVT_SQLのコメント参照。
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

    async def get_feature_keys_in_tile(
        self, z: int, x: int, y: int, bbox: BoundingBox, coverage_tile: tuple[int, int, int]
    ) -> list[str] | None:
        """鍵→動的値配信層（風、「評価軸」グループ）用に、指定タイルのフィーチャーの鍵を返す。

        鍵はタイルが焼いた`feature_key`と同じもの（`EDGE_UNIT_MIN_ZOOM`参照）。契約は
        get_road_surface_tile_mvtと同じ（カバレッジ外はNone、カバレッジ内0件は空リスト）。
        道路自身の向きは含まない（風の計算に不要）。
        """
        coverage_zoom, coverage_x, coverage_y = coverage_tile
        result = await self._session.execute(
            _FEATURE_KEYS_IN_TILE_SQL,
            {
                "coverage_zoom": coverage_zoom,
                "coverage_x": coverage_x,
                "coverage_y": coverage_y,
                "z": z,
                "xmin": bbox.min_longitude,
                "ymin": bbox.min_latitude,
                "xmax": bbox.max_longitude,
                "ymax": bbox.max_latitude,
            },
        )
        covered, feature_keys = result.one()
        if not covered:
            return None
        return [str(key) for key in (feature_keys or [])]

    async def get_feature_gradient_inputs_in_tile(
        self, z: int, x: int, y: int, bbox: BoundingBox, coverage_tile: tuple[int, int, int]
    ) -> dict[str, tuple[float, float]] | None:
        """鍵→勾配配信層用に、指定タイルのフィーチャーごとの`(gradient_percent,
        road_bearing_deg)`を返す。

        鍵はタイルが焼いた`feature_key`と同じもの。契約はget_feature_keys_in_tileと同じ
        （カバレッジ外はNone、カバレッジ内0件は空dict）。勾配・向きのいずれかが欠損している
        区間は除外する（_FEATURE_GRADIENT_INPUTS_IN_TILE_SQLのコメント参照）。
        """
        coverage_zoom, coverage_x, coverage_y = coverage_tile
        result = await self._session.execute(
            _FEATURE_GRADIENT_INPUTS_IN_TILE_SQL,
            {
                "coverage_zoom": coverage_zoom,
                "coverage_x": coverage_x,
                "coverage_y": coverage_y,
                "z": z,
                "xmin": bbox.min_longitude,
                "ymin": bbox.min_latitude,
                "xmax": bbox.max_longitude,
                "ymax": bbox.max_latitude,
            },
        )
        covered, inputs = result.one()
        if not covered:
            return None
        return {
            str(key): (float(value[0]), float(value[1])) for key, value in (inputs or {}).items()
        }


class AttributeRepository(_SessionRepository):
    """Edge単位のRoad Attribute（elevation_attributes）の読み書き。

    surfaceは専用テーブルを持たず、road_edges.osm_way_id経由でosm_raw_ways.surfaceを
    JOINして都度導出する。

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

    async def save_edge_attribute_counts(self, rows: list[dict]) -> None:
        """`precompute_edge_attribute_counts.py`が組み立てた行をUPSERTする。

        行の辞書のキーは`EdgeAttributeCountsRow`の列と1対1（バッチ側は集計結果を
        そのまま辞書へ入れるだけで、SQLは持たない）。
        """
        if not rows:
            return
        await _bulk_upsert(
            self._session,
            EdgeAttributeCountsRow,
            rows,
            ["edge_id"],
            [
                "accident_count", "intersection_count", "poi_counts", "computed_at",
                "source_accident_import_run_id", "source_osm_import_run_id", "algorithm_version",
            ],
        )

    async def save_way_landcover(self, records: list[WayLandcover]) -> None:
        if not records:
            return
        rows = [{"osm_way_id": r.osm_way_id, **_landcover_value_row(r)} for r in records]
        await _bulk_upsert(self._session, WayLandcoverRow, rows, ["osm_way_id"], _LANDCOVER_UPSERT_COLUMNS)

    async def save_edge_landcover(self, records: list[EdgeLandcover]) -> None:
        if not records:
            return
        rows = [
            {"osm_way_id": r.osm_way_id, "node_lo": r.node_lo, "node_hi": r.node_hi, **_landcover_value_row(r)}
            for r in records
        ]
        await _bulk_upsert(
            self._session, EdgeLandcoverRow, rows, ["osm_way_id", "node_lo", "node_hi"], _LANDCOVER_UPSERT_COLUMNS
        )

    async def get_surface_attributes(self, edge_ids: list[str]) -> dict[str, str | None]:
        if not edge_ids:
            return {}
        result: dict[str, str | None] = {}
        # road_edges.osm_way_id経由でosm_raw_ways.surfaceをJOIN導出する。JOINには
        # migration 0001のidx_road_edges_osm_way_idを使う。osm_way_idが無いEdge
        # （座標2点未満等）はLEFT JOINでsurface=Noneになる。=ANY(配列)化の理由は
        # get_elevation_attributesのコメント参照。
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

    async def get_poi_counts_by_kind(
        self,
        edge_ids: list[str],
        cluster_eps_m: float = POI_CLUSTER_EPS_M,
        on_edge_tolerance_m: float = POI_ON_EDGE_TOLERANCE_M,
    ) -> dict[str, dict[str, int]]:
        """指定edge_idそれぞれについて、停止要因の回数を集計キー別に返す
        （`domain/traffic.py: POI_COUNT_KINDS`）。

        数え方は「その区間を走って実際に遭遇する停止」に近づけている——対象をそのwayの
        構成ノードへ限り、区間の始点を除き、同じ場所の点をまとめてから数える
        （`_POI_COUNTS_BODY`のコメント参照）。

        該当が0件のedgeは空辞書（キー自体は必ず結果に含まれる）。呼び出し元は「行が無い＝
        未集計（不明）」と「空辞書＝集計済みで0件」を区別する。
        """
        if not edge_ids:
            return {}
        result: dict[str, dict[str, int]] = {}
        for id_chunk in _chunked(edge_ids, 50_000):
            rows = await self._session.execute(
                _POI_COUNTS_BY_KIND_SQL,
                {
                    "edge_ids": id_chunk,
                    "cluster_eps_m": cluster_eps_m,
                    "on_edge_tolerance_m": on_edge_tolerance_m,
                },
            )
            for edge_id, poi_counts in rows.all():
                result[edge_id] = dict(poi_counts or {})
        return result

    async def get_way_tags_by_osm_way_id(
        self, osm_way_id: int
    ) -> tuple[str | None, dict[str, str], bool, str | None] | None:
        """osm_way_id完全一致で(highway, tags, is_designated, surface)を返す。

        空間マッチ（半径内最近傍）は、交差点付近など複数の道路が近接する場所で、実際に
        クリックされたMVTフィーチャー（`_ROAD_SURFACE_TILE_MVT_SQL`が同じosm_way_idを
        プロパティとして焼き込み済み）とは別の道路を拾いうる（ポップアップの`car_stress`
        表示値と、内訳ボタンで計算した値が食い違う）。フィーチャーが指す行そのものを
        osm_way_idで引き直すことで、この不整合を構造的に防ぐ。

        該当way自体が存在しない（極端な状況、タイル生成後の再取込等）場合はNone。
        """
        result = await self._session.execute(
            _WAY_TAGS_BY_OSM_WAY_ID_SQL,
            {"osm_way_id": osm_way_id, "kinds": sorted(CAR_STRESS_DESIGNATION_KINDS)},
        )
        row = result.first()
        if row is None:
            return None
        return (row.highway, row.tags or {}, row.is_designated, row.surface)

    async def get_way_attribute_counts(self, osm_way_id: int) -> WayAttributeCounts | None:
        """osm_way_id完全一致で事前集計（way_attribute_counts）の1行を返す（区間インスペクタ）。
        行が無い場合はNone（データ無し。呼び出し元は該当軸をスコア算出不能として扱う）。
        """
        result = await self._session.execute(
            _WAY_ATTRIBUTE_COUNTS_BY_OSM_WAY_ID_SQL, {"osm_way_id": osm_way_id}
        )
        row = result.first()
        if row is None:
            return None
        return WayAttributeCounts(
            length_m=row.length_m,
            accident_count=row.accident_count,
            intersection_count=row.intersection_count,
            poi_counts=None if row.poi_counts is None else dict(row.poi_counts),
        )

    async def sample_way_rows(
        self,
        sample_percent: float = 2.0,
        limit: int = 20_000,
        bbox: BoundingBox | None = None,
    ) -> list[WayMaterialSampleRow]:
        """Way単位の材料の元データを標本として取る（軸スタジオの分布プレビュー）。材料値への
        組み立ては呼び出し元（`axis_preview_service.py`）が区間インスペクタと同じ
        `way_scalar_materials`で行う——ここで組み立てるとinfrastructureが評価ドメインへ
        依存する。

        `bbox`を渡すとその範囲内のwayだけを対象にし、抽選（`sample_percent`）は使わない。
        軸の分布は地域で大きく変わるため、全域の平均だけでは市街地の偏りが見えない。
        """
        params: dict[str, object] = {
            "limit": limit,
            "kinds": sorted(CAR_STRESS_DESIGNATION_KINDS),
        }
        if bbox is None:
            statement = _SAMPLE_WAY_MATERIALS_SQL
            params["sample_percent"] = sample_percent
        else:
            statement = _SAMPLE_WAY_MATERIALS_IN_BBOX_SQL
            params.update(
                xmin=bbox.min_longitude,
                ymin=bbox.min_latitude,
                xmax=bbox.max_longitude,
                ymax=bbox.max_latitude,
            )
        rows = await self._session.execute(statement, params)
        return [
            WayMaterialSampleRow(
                length_m=row.length_m,
                highway=row.highway,
                tags=row.tags,
                surface=row.surface,
                counts_length_m=row.counts_length_m,
                accident_count=row.accident_count,
                intersection_count=row.intersection_count,
                poi_counts=row.poi_counts,
                landcover_percents=_landcover_percents_or_none(row),
                is_designated=row.is_designated,
            )
            for row in rows
        ]

    async def get_way_landcover(self, osm_way_id: int) -> WayLandcover | None:
        """osm_way_id完全一致で土地被覆（way_landcover）の1行を返す（区間インスペクタの
        土地被覆の内訳）。行が無い場合はNone（バッチ未実行・ラスタ範囲外・画素不足）。
        """
        result = await self._session.execute(_WAY_LANDCOVER_BY_OSM_WAY_ID_SQL, {"osm_way_id": osm_way_id})
        row = result.first()
        if row is None:
            return None
        return WayLandcover(
            osm_way_id=osm_way_id,
            # 割合列がNULLの行は「計算済み・値なし」。呼び出し側からは行が無い場合と同じ
            # 欠損として扱えるよう、percentages自体をNoneで返す。
            percentages=(
                None
                if row.trees_percent is None
                else LandcoverPercentages(
                    valid_pixels=row.valid_pixels,
                    water_percent=row.water_percent,
                    trees_percent=row.trees_percent,
                    flooded_veg_percent=row.flooded_veg_percent,
                    crops_percent=row.crops_percent,
                    built_percent=row.built_percent,
                    bare_percent=row.bare_percent,
                    snow_ice_percent=row.snow_ice_percent,
                    rangeland_percent=row.rangeland_percent,
                )
            ),
            data_source=row.data_source,
            data_version=row.data_version,
            computed_at=row.computed_at,
            source_osm_import_run_id=row.source_osm_import_run_id,
            algorithm_version=row.algorithm_version,
            source_raster_set=row.source_raster_set,
        )

    async def get_intersection_counts(
        self, edge_ids: list[str]
    ) -> dict[str, int]:
        """指定edge_idそれぞれについて、**その区間を走ると通る**交差点（次数
        `INTERSECTION_DEGREE_THRESHOLD`以上のノード）の件数を返す。終点が交差点なら1、
        でなければ0になる。road_graphエンジンのcompute_edge_cost（探索コスト自体）で使う。
        edge_idリストを渡して辞書で受け取る形で、指定edge_idは（0件でも）必ず結果に含まれる。

        呼び出し元が渡すedge_ids集合やチャンク分割には依存しないため、同一edge_idを
        異なる順序・異なる集合で渡しても常に同じ結果を返す。
        """
        if not edge_ids:
            return {}
        result: dict[str, int] = {}
        for id_chunk in _chunked(edge_ids, 50_000):
            rows = await self._session.execute(
                _INTERSECTION_COUNTS_SQL,
                {"edge_ids": id_chunk, "degree_threshold": INTERSECTION_DEGREE_THRESHOLD},
            )
            for edge_id, intersection_count in rows.all():
                result[edge_id] = intersection_count
        return result

    async def get_accident_counts(
        self, edge_ids: list[str], bicycle_only: bool = True, max_distance_m: float = ACCIDENT_MATCH_MAX_DISTANCE_M
    ) -> dict[str, float]:
        """指定edge_idそれぞれについて、`max_distance_m`以内にある事故（accident_points）の
        合計件数（死亡事故は`ACCIDENT_FATAL_WEIGHT`件分の重み付け、domain/accident.py参照）を
        返す（外部静的データソース T50残作業、改善計画: 事故密度の精度改善）。
        `bicycle_only`の既定値は`True`（自転車ルート案内で自動車同士のみの事故まで
        数えるのは実質バグに近いという判断、ユーザー承認済みの既定挙動変更）。
        get_accident_countsと同じ「edge_idリストを渡して辞書で受け取る」形で、
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
                    "edge_ids": id_chunk,
                    "bicycle_only": bicycle_only,
                    "accident_distance_m": max_distance_m,
                    "accident_distance_deg": max_distance_deg,
                },
            )
            for edge_id, accident_count in rows.all():
                result[edge_id] = float(accident_count)
        return result

    async def get_accident_years_covered(self) -> int:
        """事故データの収録年数（accident_import_runsの成功run、年重複なし）を返す。
        domain/evaluation.py: compute_edge_axis_scoresの「件/(km・年)」正規化に使う。
        1リクエスト1回だけ呼ぶ想定（他の事前集計カウントと同じタイミング）。
        """
        result = await self._session.execute(_ACCIDENT_YEARS_COVERED_SQL)
        return result.scalar_one()

    async def get_derived_data_revision(self) -> int | None:
        """派生データの世代（`derived_data_meta.revision`）。バッチが中身を書き直すたびに
        進む。材料キャッシュがディスクの中身と突き合わせるのに使う
        （services/derived_data_revision_service.py）。"""
        return await derived_data_meta.get_revision(self._session)

    async def get_designated_edge_ids(self, edge_ids: list[str]) -> set[str]:
        """指定edge_idのうち、KSJ N10/N12（`domain/designation.py:
        CAR_STRESS_DESIGNATION_KINDS`）に該当するものの集合を返す（外部静的データソース
        T51）。`designation_attributes`はmatch_designations.pyの事前計算バッチが埋める
        （クエリ時にバッファ交差計算はしない）。
        """
        if not edge_ids:
            return set()
        result: set[str] = set()
        for id_chunk in _chunked(edge_ids, 50_000):
            rows = await self._session.execute(
                _DESIGNATED_EDGE_IDS_SQL,
                {"edge_ids": id_chunk, "kinds": sorted(CAR_STRESS_DESIGNATION_KINDS)},
            )
            result.update(edge_id for (edge_id,) in rows.all())
        return result

    async def get_edge_materials_batch(self, edge_ids: list[str]) -> EdgeMaterialsBatch:
        """探索フェーズ（`RoadGraphEngine.prepare`）が必要とする材料一式（surface・
        edge_attribute_counts・way_tags・elevation_attributes・designated_edge_ids・
        way_landcoverの配線済みクラス）を1回のJOINクエリへ統合して取得する。ボトルネックは
        ラウンドトリップ回数ではなく同じEdge集合に対してSQLAlchemy ORMの行構築を複数回
        繰り返すオーバーヘッドのため、個別クエリの束ではなく1クエリへ統合する
        （dev DB、71,791 Edgeで個別5クエリ8.33秒→統合1クエリ1.30秒、6.4倍）。
        `graph_service.py`の`_build_search_materials_uncached`・
        `_get_or_build_tile_materials`の両方から呼ばれる。

        戻り値はEdge単位で`EdgeMaterialBundle`（1オブジェクト）へ統合する
        （`domain/attributes.py: EdgeMaterialBundle`のdocstring参照）。各材料の
        「該当行なし」の扱い: surface・way_tagsはLEFT JOINでNone/{}を明示的に持つ
        （bundle自体はedge_idsに含まれる全Edgeぶん必ず存在する）。attribute_counts・
        elevation_attributeは対象テーブルへの行が無ければNone（NOT NULL列を「行の有無」の
        判定に使う）。`poi_counts`はNULL許容で、行があってもNULLでありうる
        （NULL＝種別別の集計が未実行、空辞書＝集計済みで0件）。is_designatedはEXISTS副問い合わせで判定する（対象kindの
        designation_attributes行が1つでもあれば該当、の意味）。`landcover_percents`は
        way_landcover行が無ければ全クラスまとめてNone
        （`WayLandcoverRow`のLEFT JOIN、`EdgeMaterialBundle`のdocstring参照）。
        """
        if not edge_ids:
            return EdgeMaterialsBatch(materials={})

        materials: dict[str, EdgeMaterialBundle] = {}

        designation_kinds = sorted(CAR_STRESS_DESIGNATION_KINDS)
        designation_exists = (
            select(DesignationAttributeRow.osm_way_id)
            .where(
                DesignationAttributeRow.osm_way_id == RoadEdgeRow.osm_way_id,
                DesignationAttributeRow.kind == any_(cast(designation_kinds, ARRAY(Text))),
            )
            .exists()
        )

        for id_chunk in _chunked(edge_ids, 50_000):
            stmt = (
                select(
                    RoadEdgeRow.edge_id,
                    OsmRawWayRow.surface,
                    OsmRawWayRow.tags,
                    EdgeAttributeCountsRow.accident_count,
                    EdgeAttributeCountsRow.intersection_count,
                    EdgeAttributeCountsRow.poi_counts,
                    ElevationAttributeRow.start_elevation_m,
                    ElevationAttributeRow.end_elevation_m,
                    ElevationAttributeRow.elevation_gain_m,
                    ElevationAttributeRow.elevation_loss_m,
                    ElevationAttributeRow.average_grade,
                    ElevationAttributeRow.max_grade,
                    ElevationAttributeRow.min_grade,
                    ElevationAttributeRow.data_source,
                    ElevationAttributeRow.data_version,
                    ElevationAttributeRow.calculated_at,
                    designation_exists.label("is_designated"),
                    *(_landcover_value_column(key) for key in WIRED_LANDCOVER_KEYS),
                )
                .select_from(RoadEdgeRow)
                .outerjoin(OsmRawWayRow, RoadEdgeRow.osm_way_id == OsmRawWayRow.osm_way_id)
                .outerjoin(EdgeAttributeCountsRow, EdgeAttributeCountsRow.edge_id == RoadEdgeRow.edge_id)
                .outerjoin(ElevationAttributeRow, ElevationAttributeRow.edge_id == RoadEdgeRow.edge_id)
                .outerjoin(WayLandcoverRow, WayLandcoverRow.osm_way_id == RoadEdgeRow.osm_way_id)
                .outerjoin(EdgeLandcoverRow, _EDGE_LANDCOVER_JOIN_ON)
                .where(RoadEdgeRow.edge_id == any_(cast(id_chunk, ARRAY(Text))))
            )
            for row in await self._session.execute(stmt):
                attribute_counts = (
                    EdgeAttributeCounts(
                        poi_counts=None if row.poi_counts is None else dict(row.poi_counts),
                        accident_count=row.accident_count,
                        intersection_count=row.intersection_count,
                    )
                    if row.intersection_count is not None
                    else None
                )
                elevation_attribute = (
                    ElevationAttribute(
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
                    if row.calculated_at is not None
                    else None
                )
                materials[row.edge_id] = EdgeMaterialBundle(
                    surface=row.surface,
                    way_tags=row.tags or {},
                    attribute_counts=attribute_counts,
                    elevation_attribute=elevation_attribute,
                    is_designated=bool(row.is_designated),
                    landcover_percents=(
                        {key: getattr(row, key) for key in WIRED_LANDCOVER_KEYS}
                        if row.trees_percent is not None
                        else None
                    ),
                )

        return EdgeMaterialsBatch(materials=materials)

    async def rebuild_raw_intersection_nodes(self) -> None:
        """raw_intersection_nodes（次数3以上の生OSMノード）を全再構築する。

        osm_raw_ways.node_idsの隣接関係から導出するRoad Graph非依存の派生データ
        （_REBUILD_RAW_INTERSECTION_NODES_SQLのコメント参照）。osm_raw_waysが変わった場合
        （PBF再取込等）はrecompute_way_attribute_countsより先に呼び直す必要がある。
        """
        await self._session.execute(text("TRUNCATE raw_intersection_nodes"))
        await self._session.execute(
            _REBUILD_RAW_INTERSECTION_NODES_SQL,
            {"degree_threshold": INTERSECTION_DEGREE_THRESHOLD},
        )

    async def recompute_way_attribute_counts(
        self,
        osm_way_ids: list[int],
        computed_at: datetime,
        source_accident_import_run_id: int | None = None,
        source_osm_import_run_id: int | None = None,
        algorithm_version: str | None = None,
    ) -> None:
        """指定osm_way_idのway_attribute_counts（way単位の事実カウント）を
        再計算しUPSERTする。事前にrebuild_raw_intersection_nodesの実行が必要
        （intersection_countの参照先。_RECOMPUTE_WAY_ATTRIBUTE_COUNTS_SQLのコメント参照）。

        source_*_import_run_id/algorithm_versionは派生データの系譜追跡
        （migration 0024）用。呼び出し元（precompute_way_attribute_counts.py）が実行時点の
        最新成功run idを一度だけ取得し、全チャンクへ同じ値を渡す想定（テスト等で省略時は
        Noneのまま書き込まれる）。
        """
        if not osm_way_ids:
            return
        await self._session.execute(
            _RECOMPUTE_WAY_ATTRIBUTE_COUNTS_SQL,
            {
                "osm_way_ids": osm_way_ids,
                "computed_at": computed_at,
                "fatal_weight": ACCIDENT_FATAL_WEIGHT,
                "accident_distance_m": ACCIDENT_MATCH_MAX_DISTANCE_M,
                "accident_distance_deg": _meters_to_bbox_margin_deg(ACCIDENT_MATCH_MAX_DISTANCE_M),
                "cluster_eps_m": POI_CLUSTER_EPS_M,
                "source_accident_import_run_id": source_accident_import_run_id,
                "source_osm_import_run_id": source_osm_import_run_id,
                "algorithm_version": algorithm_version,
            },
        )

    async def recompute_way_divided_carriageway(
        self,
        osm_way_ids: list[int],
        computed_at: datetime,
        source_osm_import_run_id: int | None = None,
        algorithm_version: str | None = None,
    ) -> None:
        """指定osm_way_idが「上下線が分かれた道の片側」かを判定しUPSERTする
        （`app/batch/precompute_way_divided_carriageway.py`）。

        """
        if not osm_way_ids:
            return
        await self._session.execute(
            _RECOMPUTE_WAY_DIVIDED_CARRIAGEWAY_SQL,
            {
                "osm_way_ids": osm_way_ids,
                "computed_at": computed_at,
                "source_osm_import_run_id": source_osm_import_run_id,
                "algorithm_version": algorithm_version,
                "bearing_tolerance_deg": DIVIDED_CARRIAGEWAY_BEARING_TOLERANCE_DEG,
                "named_gap_m": DIVIDED_CARRIAGEWAY_NAMED_GAP_M,
                "geometric_gap_m": DIVIDED_CARRIAGEWAY_GEOMETRIC_GAP_M,
                "carriageway_values": list(DIVIDED_CARRIAGEWAY_TAG_VALUES),
            },
        )


class RoadGraphRepository:
    """責務別の4リポジトリ（raw_osm/graph/attributes/tile_query属性）を束ね、
    フラットな委譲メソッド群として公開するファサード。

    **このフラットな形（`repository.save_raw_ways(...)`等、`repository.raw_osm.save_raw_ways(...)`
    ではない）が、`GraphService`/`ElevationAttributeService`/`RegionService`が依存する
    正式なインターフェースである。各サービスは`RoadGraphRepository`
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

    async def get_cached_tiles(self, zoom: int, tiles: list[tuple[int, int]]) -> set[tuple[int, int]]:
        return await self.raw_osm.get_cached_tiles(zoom, tiles)

    async def get_distinct_material_values(self, material_id: str) -> list[str]:
        return await self.raw_osm.get_distinct_material_values(material_id)

    # --- 派生グラフ（DerivedGraphRepository） ---

    async def get_graph_in_bbox(self, bbox: BoundingBox) -> RoadGraph | None:
        return await self.graph.get_graph_in_bbox(bbox)

    async def get_graph_topology_in_bbox(self, bbox: BoundingBox) -> LeanRoadGraph | None:
        return await self.graph.get_graph_topology_in_bbox(bbox)

    async def get_edges_with_geometry(self, edge_ids: list[str]) -> dict[str, DirectedEdge]:
        return await self.graph.get_edges_with_geometry(edge_ids)

    async def is_split_up_to_date(self, bbox: BoundingBox) -> bool:
        return await self.graph.is_split_up_to_date(bbox)

    async def save_graph(self, graph: RoadGraphLike, way_ids_to_replace: set[int] | None = None) -> None:
        await self.graph.save_graph(graph, way_ids_to_replace=way_ids_to_replace)

    async def recompute_node_degrees(self) -> None:
        await self.graph.recompute_node_degrees()

    async def recompute_node_max_highway_rank(self, node_ids: list[str] | None = None) -> None:
        await self.graph.recompute_node_max_highway_rank(node_ids)

    async def recompute_node_traffic_signals(self, node_ids: list[str]) -> None:
        await self.graph.recompute_node_traffic_signals(node_ids)

    async def recompute_node_intersection_attributes(self, node_ids: list[str]) -> None:
        await self.graph.recompute_node_intersection_attributes(node_ids)

    async def get_node_intersection_attributes(self, node_ids: list[str]) -> dict[str, tuple[bool, int]]:
        return await self.graph.get_node_intersection_attributes(node_ids)

    # --- Road Attribute（AttributeRepository） ---

    async def get_elevation_attributes(self, edge_ids: list[str]) -> dict[str, ElevationAttribute]:
        return await self.attributes.get_elevation_attributes(edge_ids)

    async def save_elevation_attributes(self, attributes: list[ElevationAttribute]) -> None:
        await self.attributes.save_elevation_attributes(attributes)

    async def save_way_landcover(self, records: list[WayLandcover]) -> None:
        await self.attributes.save_way_landcover(records)

    async def save_edge_landcover(self, records: list[EdgeLandcover]) -> None:
        await self.attributes.save_edge_landcover(records)

    async def save_edge_attribute_counts(self, rows: list[dict]) -> None:
        await self.attributes.save_edge_attribute_counts(rows)

    async def get_surface_attributes(self, edge_ids: list[str]) -> dict[str, str | None]:
        return await self.attributes.get_surface_attributes(edge_ids)

    async def get_poi_counts_by_kind(
        self,
        edge_ids: list[str],
        cluster_eps_m: float = POI_CLUSTER_EPS_M,
        on_edge_tolerance_m: float = POI_ON_EDGE_TOLERANCE_M,
    ) -> dict[str, dict[str, int]]:
        return await self.attributes.get_poi_counts_by_kind(
            edge_ids, cluster_eps_m=cluster_eps_m, on_edge_tolerance_m=on_edge_tolerance_m
        )

    async def get_way_tags_by_osm_way_id(
        self, osm_way_id: int
    ) -> tuple[str | None, dict[str, str], bool, str | None] | None:
        return await self.attributes.get_way_tags_by_osm_way_id(osm_way_id)

    async def get_way_attribute_counts(self, osm_way_id: int) -> WayAttributeCounts | None:
        return await self.attributes.get_way_attribute_counts(osm_way_id)

    async def sample_way_rows(
        self,
        sample_percent: float = 2.0,
        limit: int = 20_000,
        bbox: BoundingBox | None = None,
    ) -> list[WayMaterialSampleRow]:
        return await self.attributes.sample_way_rows(sample_percent, limit, bbox)

    async def get_way_landcover(self, osm_way_id: int) -> WayLandcover | None:
        return await self.attributes.get_way_landcover(osm_way_id)

    async def get_intersection_counts(
        self, edge_ids: list[str]
    ) -> dict[str, int]:
        return await self.attributes.get_intersection_counts(edge_ids)

    async def get_accident_counts(
        self, edge_ids: list[str], bicycle_only: bool = True, max_distance_m: float = ACCIDENT_MATCH_MAX_DISTANCE_M
    ) -> dict[str, float]:
        return await self.attributes.get_accident_counts(edge_ids, bicycle_only=bicycle_only, max_distance_m=max_distance_m)

    async def get_accident_years_covered(self) -> int:
        return await self.attributes.get_accident_years_covered()

    async def get_derived_data_revision(self) -> int | None:
        return await self.attributes.get_derived_data_revision()

    async def get_designated_edge_ids(self, edge_ids: list[str]) -> set[str]:
        return await self.attributes.get_designated_edge_ids(edge_ids)

    async def get_edge_materials_batch(self, edge_ids: list[str]) -> EdgeMaterialsBatch:
        return await self.attributes.get_edge_materials_batch(edge_ids)

    async def rebuild_raw_intersection_nodes(self) -> None:
        await self.attributes.rebuild_raw_intersection_nodes()

    async def recompute_way_attribute_counts(
        self,
        osm_way_ids: list[int],
        computed_at: datetime,
        source_accident_import_run_id: int | None = None,
        source_osm_import_run_id: int | None = None,
        algorithm_version: str | None = None,
    ) -> None:
        await self.attributes.recompute_way_attribute_counts(
            osm_way_ids, computed_at, source_accident_import_run_id, source_osm_import_run_id, algorithm_version
        )

    async def recompute_way_divided_carriageway(
        self,
        osm_way_ids: list[int],
        computed_at: datetime,
        source_osm_import_run_id: int | None = None,
        algorithm_version: str | None = None,
    ) -> None:
        await self.attributes.recompute_way_divided_carriageway(
            osm_way_ids, computed_at, source_osm_import_run_id, algorithm_version
        )

    # --- 表示用MVT（RoadSurfaceTileQuery） ---

    async def get_road_surface_tile_mvt(
        self, z: int, x: int, y: int, bbox: BoundingBox, coverage_tile: tuple[int, int, int]
    ) -> bytes | None:
        return await self.tile_query.get_road_surface_tile_mvt(z, x, y, bbox, coverage_tile)

    async def get_poi_tile_mvt(
        self, z: int, x: int, y: int, bbox: BoundingBox, coverage_tile: tuple[int, int, int]
    ) -> bytes | None:
        return await self.tile_query.get_poi_tile_mvt(z, x, y, bbox, coverage_tile)

    async def get_feature_keys_in_tile(
        self, z: int, x: int, y: int, bbox: BoundingBox, coverage_tile: tuple[int, int, int]
    ) -> list[str] | None:
        # 鍵→動的値配信層（風）。詳細はRoadSurfaceTileQuery.
        # get_feature_keys_in_tileのdocstring参照。
        return await self.tile_query.get_feature_keys_in_tile(z, x, y, bbox, coverage_tile)

    async def get_feature_gradient_inputs_in_tile(
        self, z: int, x: int, y: int, bbox: BoundingBox, coverage_tile: tuple[int, int, int]
    ) -> dict[str, tuple[float, float]] | None:
        # 鍵→勾配配信層。詳細はRoadSurfaceTileQuery.
        # get_feature_gradient_inputs_in_tileのdocstring参照。
        return await self.tile_query.get_feature_gradient_inputs_in_tile(z, x, y, bbox, coverage_tile)
