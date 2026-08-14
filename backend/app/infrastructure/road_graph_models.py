"""Road Graph・Road AttributeのPostGISスキーマ（SQLAlchemy ORM）。

domain/graph.py・domain/attributes.pyのPydanticモデルとは別に、DBの行表現として
定義する（ドメインモデルとORMモデルを混同しない）。行⇔ドメインモデルの変換は
road_graph_repository.pyが担う。
"""

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY
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
    geom = mapped_column(Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OsmRawWayRow(Base):
    """OSMの生Wayデータ（WaySpec相当。domain/osm_adapter.pyでタグ解釈済みの状態で保存する）。

    node_idsはWayが参照するノードIDの順序付き配列。「このノードをどのWayが参照しているか」
    という近傍探索（get_way_specs_with_closure）に使うため、GINインデックスで配列の
    重なり（&&演算子）を高速に検索できるようにする。

    Wayのタグ・ノード列自体は、それを取得したタイルに関わらず常に同じ内容になる
    （road_edgesの分割結果と異なり曖昧さが無い）ため、素直にUPSERTしてよい。
    """

    __tablename__ = "osm_raw_ways"

    # OSMのWay IDを常に明示的に指定するため、DB側の自動採番(BIGSERIAL)にしない。
    osm_way_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    node_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    highway: Mapped[str | None] = mapped_column(String, nullable=True)
    surface: Mapped[str | None] = mapped_column(String, nullable=True)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_osm_raw_ways_node_ids", "node_ids", postgresql_using="gin"),)


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
