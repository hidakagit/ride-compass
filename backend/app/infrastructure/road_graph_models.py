"""Road Graph・Road AttributeのPostGISスキーマ（SQLAlchemy ORM）。

domain/graph.py・domain/attributes.pyのPydanticモデルとは別に、DBの行表現として
定義する（ドメインモデルとORMモデルを混同しない）。行⇔ドメインモデルの変換は
road_graph_repository.pyが担う。
"""

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class OsmRawNodeRow(Base):
    """OSMの生ノードデータ（Road Graph構築とは独立の永続化層）。

    Road Graphの交差点分割（domain/graph.py: build_road_graph）は「どのWayが
    どのNodeを共有しているか」を正しく知る必要があるが、タイル単位でOverpassへ
    問い合わせるとタイル境界付近でこの情報が不完全になり、同じ現実のWayが取得
    タイミングによって異なる分割結果になりうる（詳細はdocs/architecture.md
    「タイル境界依存の交差点分割不一致問題」参照）。この問題への根本対応として、
    生のOSM Way/Nodeデータをタイル取得のたびに（取得元タイルに依存しない形で）
    ここへ蓄積し、Road Graph構築時にDB上の既知の生データ全体から必要な近傍Wayを
    含めて計算し直す設計にした。
    """

    __tablename__ = "osm_raw_nodes"

    # OSMのノードIDを常に明示的に指定するため、DB側の自動採番(BIGSERIAL)にしない。
    osm_node_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    # geomへの空間索引は張らない。全コードからのアクセスは常にosm_node_id指定のみで、
    # 空間検索（ST_Intersects等）は一度も行われないため、GiSTは取込時の逐次挿入コストと
    # 容量を消費するだけの死荷重になる（PBF初回取込でチャンク処理時間が7秒→73秒へ
    # 単調増加する要因になりうる）。既存DB向けの削除はmigrations/0002参照。
    geom = mapped_column(Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OsmRawPoiRow(Base):
    """信号・横断歩道・一時停止・踏切等、停止・減速要因になるOSM nodeの生データ
    （静的道路属性P1、docs/static-road-attributes-plan.md §4）。

    osm_raw_nodesとは別テーブル。osm_raw_nodesはWayが参照する全nodeの座標を
    無差別に保持する（形状点がほとんど）のに対し、こちらは`domain/traffic.py:
    classify_stop_poi`で分類できたnode（対象タグを持つごく一部）だけを選別して
    保持する（osm_adapter.py: osm_node_to_poi_spec）。

    geomへの空間索引は必要（空間索引を張らないosm_raw_nodesとは逆）。
    road_edgesとのST_DWithin空間結合（AttributeRepository.get_stop_poi_counts等、
    静的道路属性P1）で使う、この用途で初めて生まれる空間検索アクセスパターンのため。
    """

    __tablename__ = "osm_raw_pois"

    osm_node_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    geom = mapped_column(Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OsmRawWayRow(Base):
    """OSMの生Wayデータ（WaySpec相当。domain/osm_adapter.pyでタグ解釈済みの状態で保存する）。

    node_idsはWayが参照するノードIDの順序付き配列。近傍探索
    （get_way_specs_with_closure）はgeom列の空間検索で行い、node_ids自体への
    GINインデックスは張らない（Supabaseフリープランの容量制約に対応する
    docs/osm-pbf-import.md 10章参照）。node_ids自体はbuild_road_graphへの入力として
    引き続き必要。

    Wayのタグ・ノード列自体は、それを取得したタイルに関わらず常に同じ内容になる
    （road_edgesの分割結果と異なり曖昧さが無い）ため、素直にUPSERTしてよい。
    ただし`updated_at`は内容が実際に変わった行だけを更新する（`save_raw_ways`参照）。
    1つのWayが複数タイルにまたがるのは普通にあるため、無条件に`updated_at`を
    更新すると、隣接タイルを後から取得しただけで無関係なWayの`updated_at`が
    進んでしまい、`is_split_up_to_date`の鮮度判定を誤らせる。

    `split_at`は、このWayが最後に`save_graph`でsplit処理された時刻（Edge生成が
    0件でもスタンプする）。`updated_at`と比較することで、生データが変わって
    いなければroad_edgesを再構築せず直接読める省略パスを実現する
    （`RoadGraphRepository.is_split_up_to_date`/`GraphService`参照）。
    """

    __tablename__ = "osm_raw_ways"

    # OSMのWay IDを常に明示的に指定するため、DB側の自動採番(BIGSERIAL)にしない。
    osm_way_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    node_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    highway: Mapped[str | None] = mapped_column(String, nullable=True)
    surface: Mapped[str | None] = mapped_column(String, nullable=True)
    # 静的道路属性の許可リストタグ（docs/static-road-attributes-plan.md P0、
    # osm_adapter.py: ALLOWED_WAY_TAGS）。highway/surfaceは既存の専用列のままここには
    # 含めない。本番規模で容量増加は+約9MBと軽微（無視できる）。
    tags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    direction: Mapped[str] = mapped_column(String, nullable=False)
    # Wayの実体化済みLINESTRING（PBF取込バッチ・save_raw_waysがノード座標から算出して保存）。
    # node_ids→osm_raw_nodesのJOINなしにタイルbboxの空間検索で線ジオメトリを引くための列で、
    # 地域路面レイヤー（RegionService）のPostGIS読み替え（docs/osm-pbf-import.md Phase 2）に使う。
    # 座標が判明しているノードが2点未満のWay（抽出ファイル境界等）はNULLになりうる。
    geom = mapped_column(Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # このWayが最後にsave_graph(..., way_ids_to_replace=...)でsplit処理された時刻。
    # road_edgesへ実際に1件もEdgeを生成しなかったWay（座標既知ノードが2点未満のセグメントしか
    # 無い等、domain/graph.py: build_road_graph参照）でもスタンプする（road_edges側の行の有無を
    # 鮮度シグナルにすると、そうしたWayを含むbboxが永久にstale判定され続けるため）。
    # GraphService.get_or_build_graph_with_attributesの省略パス（is_split_up_to_date）が、
    # このWayの分割結果が生データ（updated_at）より新しいかどうかの判定に使う。
    split_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RoadNodeRow(Base):
    __tablename__ = "road_nodes"

    node_id: Mapped[str] = mapped_column(String, primary_key=True)
    osm_node_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    geom = mapped_column(Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # road_edges全件から見た真のグローバル次数（事前集計、
    # backend/app/batch/precompute_road_node_degrees.pyで再計算）。DEFAULT 0は
    # ノード作成時点（PBF取込）の初期値で、バッチ実行までは未計算を意味する。
    degree: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class RoadEdgeRow(Base):
    __tablename__ = "road_edges"

    edge_id: Mapped[str] = mapped_column(String, primary_key=True)
    from_node_id: Mapped[str] = mapped_column(String, ForeignKey("road_nodes.node_id"), nullable=False)
    to_node_id: Mapped[str] = mapped_column(String, ForeignKey("road_nodes.node_id"), nullable=False)
    geom = mapped_column(Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=True), nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    osm_way_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    highway: Mapped[str | None] = mapped_column(String, nullable=True)
    # from_node→to_node方向の方位角（度、北=0、時計回り）。domain/graph.py:
    # build_road_graphが算出し、探索時の風評価（DYNAMIC_MATERIAL_EVALUATORS）が
    # geometry decodeを経由せずこの列だけで完結できるようにする。
    bearing_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ElevationAttributeRow(Base):
    __tablename__ = "elevation_attributes"

    edge_id: Mapped[str] = mapped_column(
        String, ForeignKey("road_edges.edge_id", ondelete="CASCADE"), primary_key=True
    )
    start_elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    elevation_loss_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_grade: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_source: Mapped[str] = mapped_column(String, nullable=False)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EdgeAttributeCountsRow(Base):
    """事故・停止POI・交差点の事前集計。`designation_attributes`と同じ
    「派生データ、バッチ（`app/batch/precompute_edge_attribute_counts.py`）で再計算」
    パターン。migration 0010で実テーブルは作成済み（このORMモデルはBase.metadata経由の
    型定義・create_tables()の`checkfirst`整合のためのミラーで、既存DBへの実際のCREATEは
    migrationが担う。accident_models.pyの同種コメント参照）。

    accident_countはdouble precision（死亡事故重み付けSUM、domain/accident.py:
    ACCIDENT_FATAL_WEIGHT）。bicycle_only=trueの結果のみ保持する（road_graph_engine.pyの
    実際の呼び出しが常に既定値bicycle_only=Trueであるため）。
    """

    __tablename__ = "edge_attribute_counts"

    edge_id: Mapped[str] = mapped_column(
        String, ForeignKey("road_edges.edge_id", ondelete="CASCADE"), primary_key=True
    )
    accident_count: Mapped[float] = mapped_column(Float, nullable=False)
    stop_count: Mapped[int] = mapped_column(Integer, nullable=False)
    intersection_count: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 派生データの系譜追跡（migration 0024）。source_*_import_run_idは
    # このバッチ実行時点でのstatus='succeeded'なimport_runsのMAX(id)（高水位マーク、
    # 詳細はmigrationのコメント参照）。algorithm_versionは計算ロジック自体の版数。
    # 実際のFK制約（accident_import_runs.id/osm_import_runs.id）はmigration側でのみ持つ
    # （ORM側はミラー、EdgeAttributeCountsRowクラスdocstring参照）。ここへ
    # SQLAlchemyの`ForeignKey(...)`を書くとBase.metadata経由でaccident_models.py/
    # road_graph_models.py双方のインポートを要求するようになり、precompute_edge_attribute_
    # counts.py単体実行のように参照先モデルを一切importしないプロセスで
    # `Base.metadata.sorted_tables`/`create_all`実行時にNoReferencedTableErrorを起こす。
    # 素のInteger列に留めることでこの依存を切る。
    source_accident_import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_osm_import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    algorithm_version: Mapped[str | None] = mapped_column(String, nullable=True)


class RawIntersectionNodeRow(Base):
    """次数3以上の生OSMノード（交差点）。osm_raw_ways.node_idsの隣接関係
    から導出したRoad Graph非依存の派生データで、バッチ
    （`app/batch/precompute_way_attribute_counts.py`）が全再構築する。
    way_attribute_countsのintersection_count集計だけが参照する。migration 0012で
    実テーブルは作成済み（ORMモデルはミラー、EdgeAttributeCountsRowの同種コメント参照）。
    """

    __tablename__ = "raw_intersection_nodes"

    osm_node_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    degree: Mapped[int] = mapped_column(Integer, nullable=False)
    geom = mapped_column(Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False)


class WayAttributeCountsRow(Base):
    """事故・停止POI・交差点カウントのway単位事前集計（「事実はタイルに、
    解釈はクライアントに」）。地図タイル（_ROAD_SURFACE_TILE_MVT_SQL）への焼き込み専用。

    edge_attribute_counts（edge単位、評価用）と並存する: road_edgesはルート生成時に
    遅延構築されるため地図表示の母集団として不十分（dev環境でタイル内wayの約3.6%しか
    カバーしない）で、地図タイルはosm_raw_ways全域を母集団とする本テーブルを使う。
    カウントの意味論（半径・kindフィルタ・死亡事故重み）はedge単位版と同一。
    バッチは`app/batch/precompute_way_attribute_counts.py`。migration 0012で実テーブルは
    作成済み（ORMモデルはミラー、EdgeAttributeCountsRowの同種コメント参照）。
    """

    __tablename__ = "way_attribute_counts"

    osm_way_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("osm_raw_ways.osm_way_id", ondelete="CASCADE"), primary_key=True
    )
    length_m: Mapped[float] = mapped_column(Float, nullable=False)
    accident_count: Mapped[float] = mapped_column(Float, nullable=False)
    stop_count: Mapped[int] = mapped_column(Integer, nullable=False)
    intersection_count: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 派生データの系譜追跡（migration 0024）。EdgeAttributeCountsRowと同じ
    # 高水位マーク方式・同じ理由でForeignKey()を持たない素のInteger（コメントはそちら参照）。
    source_accident_import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_osm_import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    algorithm_version: Mapped[str | None] = mapped_column(String, nullable=True)


class WayLandcoverRow(Base):
    """道路centerline周囲100mリングの土地被覆クラス別割合のway単位事前集計
    （開放度評価軸の材料）。地図タイル母集団はosm_raw_ways全域のため
    way_attribute_countsと同じくWay単位（Edge単位ではない）。

    8列は互いに独立な数値材料（domain/material_catalog.py参照）で、Python側での
    クラス分類（どれが「遮蔽」か）は行わない——分類は評価軸のterms（重み付き線形結合）が
    表現する（domain/landcover.pyのモジュールdocstring参照）。バッチは
    `app/batch/precompute_way_landcover.py`。migration 0032で実テーブルは作成済み
    （ORMモデルはミラー、EdgeAttributeCountsRowの同種コメント参照）。
    """

    __tablename__ = "way_landcover"

    osm_way_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("osm_raw_ways.osm_way_id", ondelete="CASCADE"), primary_key=True
    )
    valid_pixels: Mapped[int] = mapped_column(Integer, nullable=False)
    water_percent: Mapped[float] = mapped_column(Float, nullable=False)
    trees_percent: Mapped[float] = mapped_column(Float, nullable=False)
    flooded_veg_percent: Mapped[float] = mapped_column(Float, nullable=False)
    crops_percent: Mapped[float] = mapped_column(Float, nullable=False)
    built_percent: Mapped[float] = mapped_column(Float, nullable=False)
    bare_percent: Mapped[float] = mapped_column(Float, nullable=False)
    snow_ice_percent: Mapped[float] = mapped_column(Float, nullable=False)
    rangeland_percent: Mapped[float] = mapped_column(Float, nullable=False)
    data_source: Mapped[str] = mapped_column(String, nullable=False)
    data_version: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 派生データの系譜追跡。EdgeAttributeCountsRowと同じ高水位マーク方式・同じ理由で
    # ForeignKey()を持たない素のInteger（コメントはそちら参照）。
    source_osm_import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    algorithm_version: Mapped[str | None] = mapped_column(String, nullable=True)


class OsmImportRunRow(Base):
    """PBF取込バッチ（app/batch/import_pbf.py）の実行記録。

    pbf_timestampはPBFヘッダのosmosis_replication_timestamp（＝OSMデータの鮮度）。
    「どの時点のOSMに基づくデータか」の追跡と、Road Attributeのdata_versionの導出元に使う。
    profile_hashは取込プロファイル（YAML）のSHA-256で、どの設定で取り込んだかを追跡する。
    """

    __tablename__ = "osm_import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pbf_name: Mapped[str] = mapped_column(String, nullable=False)
    pbf_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    profile_hash: Mapped[str] = mapped_column(String, nullable=False)
    # 取込範囲（"min_lat,min_lon,max_lat,max_lon"）。--bbox未指定時はPBFヘッダのbbox、
    # それも無ければNULL。
    bbox: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # running | succeeded | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    way_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    node_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class RoadGraphTileRow(Base):
    """Road Graphのタイル単位キャッシュの「取得済みマーカー」（domain/region.py:
    ROAD_GRAPH_TILE_ZOOM）。road_nodes/road_edgesにデータが実在するかどうかではなく、
    「このタイルはOverpassへの問い合わせを完了した」こと自体を独立して記録する。
    これにより「bboxと交差するEdgeが1件でもあるか」という不正確な判定（永続化Phase時点の
    既知の制約）を廃し、「このタイルは取得済みか」という正確な真偽判定に置き換える。
    """

    __tablename__ = "road_graph_tiles"

    zoom: Mapped[int] = mapped_column(Integer, primary_key=True)
    x: Mapped[int] = mapped_column(Integer, primary_key=True)
    y: Mapped[int] = mapped_column(Integer, primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
