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
    # geomへの空間索引は張らない（改善計画T28）。全コードからのアクセスは常にosm_node_id
    # 指定のみで、空間検索（ST_Intersects等）は一度も行われない。以前はGiSTを張っていたが、
    # 「取込時の逐次挿入コストと容量を消費するだけの死荷重」と判明した（PBF初回取込で
    # チャンク処理時間が7秒→73秒へ単調増加した事象の主因調査で発覚。エントリ数が最も多い
    # インデックスだった）。既存DB向けの削除はmigrations/0002参照。
    geom = mapped_column(Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OsmRawWayRow(Base):
    """OSMの生Wayデータ（WaySpec相当。domain/osm_adapter.pyでタグ解釈済みの状態で保存する）。

    node_idsはWayが参照するノードIDの順序付き配列。当初は近傍探索
    （get_way_specs_with_closure）のためにGINインデックス（&&演算子）を張っていたが、
    実データ規模でスケールしないことが判明しgeom列の空間検索へ置き換えたため、
    GINインデックスは廃止した（28MBの容量削減にもなる。Supabaseフリープランの
    容量制約に対応するdocs/osm-pbf-import.md 10章参照）。node_ids自体は
    build_road_graphへの入力として引き続き必要。

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
    # 含めない。容量実測（2026-08-15）で本番規模+約9MBと軽微（無視できる）。
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


class RoadEdgeRow(Base):
    __tablename__ = "road_edges"

    edge_id: Mapped[str] = mapped_column(String, primary_key=True)
    from_node_id: Mapped[str] = mapped_column(String, ForeignKey("road_nodes.node_id"), nullable=False)
    to_node_id: Mapped[str] = mapped_column(String, ForeignKey("road_nodes.node_id"), nullable=False)
    geom = mapped_column(Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=True), nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    osm_way_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    highway: Mapped[str | None] = mapped_column(String, nullable=True)
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


class SurfaceAttributeRow(Base):
    __tablename__ = "surface_attributes"

    edge_id: Mapped[str] = mapped_column(
        String, ForeignKey("road_edges.edge_id", ondelete="CASCADE"), primary_key=True
    )
    surface_type: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_source: Mapped[str] = mapped_column(String, nullable=False)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
