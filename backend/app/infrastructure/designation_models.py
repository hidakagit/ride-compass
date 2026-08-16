"""指定路線コンフレーション機構のPostGISスキーマ（SQLAlchemy ORM）。

外部静的データソース T51（docs/external-data-sources-review-2026-08-16.md §4.3）。
取込元がOSMではないため road_graph_models.py の osm_raw_ways 等とはテーブルを分けるが
（accident_models.pyと同じ判断）、DBの起動時初期化（create_tables の
Base.metadata.create_all）に乗せるため同じ Base を使う。

`route_designations`（raw層、外部指定線形の生値）・`designation_attributes`
（Edge派生、elevation_attributes型だが1エッジが複数kindに該当しうるため複合PK）・
`designation_import_runs`（osm_import_runs型の取込記録）の3テーブル。
"""

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.road_graph_models import Base


class RouteDesignationRow(Base):
    """外部指定線形の生値（N10=緊急輸送道路・N12=重要物流道路。将来のナショナル
    サイクルルート追加に備えkindは汎用文字列のまま持つが、今回はN10/N12の2値のみ投入）。
    """

    __tablename__ = "route_designations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    pref_code: Mapped[str | None] = mapped_column(String, nullable=True)
    attrs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    # ksj_n10 | ksj_n12（将来: mlit_kml | gpx）。
    source: Mapped[str] = mapped_column(String, nullable=False)
    geom = mapped_column(Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DesignationAttributeRow(Base):
    """road_edgesへのバッファマッチ結果（Edge派生、elevation_attributes型）。

    1エッジがN10・N12双方に該当しうるため、elevation_attributesと違い
    複合PK(edge_id, kind)にする（docs/external-data-sources-review-2026-08-16.md §4.3）。
    """

    __tablename__ = "designation_attributes"

    edge_id: Mapped[str] = mapped_column(
        String, ForeignKey("road_edges.edge_id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    matched_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DesignationImportRunRow(Base):
    """指定路線データ取込バッチ（app/batch/import_designations.py）の実行記録
    （osm_import_runs型）。"""

    __tablename__ = "designation_import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # running | succeeded | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    designation_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
