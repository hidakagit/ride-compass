"""指定路線コンフレーション機構のPostGISスキーマ（SQLAlchemy ORM）。

外部静的データソース T51（docs/external-data-sources-review-2026-08-16.md §4.3）。
取込元がOSMではないため road_graph_models.py の osm_raw_ways 等とはテーブルを分けるが
（accident_models.pyと同じ判断）、DBの起動時初期化（create_tables の
Base.metadata.create_all）に乗せるため同じ Base を使う。

`route_designations`（raw層、外部指定線形の生値）・`designation_attributes`
（Way派生、1Wayが複数kindに該当しうるため複合PK。改善計画T74でedge_id基準からosm_way_id基準へ
変更、road_edgesの遅延構築に依存しない全域表示のため）・
`designation_import_runs`（osm_import_runs型の取込記録）の3テーブル。
"""

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
    """osm_raw_waysへのバッファマッチ結果（Way派生）。

    改善計画T74: road_edges（ルート生成地点周辺のみ遅延構築）ではなくosm_raw_ways
    （関東全域自己完結）を対象にすることで、ルート生成履歴に関係なく全域で表示できるようにする。
    1つのWayがN10・N12双方に該当しうるため、複合PK(osm_way_id, kind)にする
    （docs/external-data-sources-review-2026-08-16.md §4.3）。
    """

    __tablename__ = "designation_attributes"

    osm_way_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("osm_raw_ways.osm_way_id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    matched_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    data_version: Mapped[str | None] = mapped_column(String, nullable=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 派生データの系譜追跡（改善計画T351、migration 0024）。matched_route_designation_idsは
    # このWay×kindのmatched_ratioへ実際に寄与した全route_designations.id（複数可、
    # ST_Unionで集約されるため1:多になりうる。match_designations.pyのdocstring参照）。
    # source_osm_import_run_idはEdgeAttributeCountsRow（road_graph_models.py）と同じ
    # 高水位マーク方式・同じ理由でForeignKey()を持たない素のInteger（road_graph_models.py:
    # EdgeAttributeCountsRowのコメント参照。実FK制約はmigrationのみで持つ）。
    matched_route_designation_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    source_osm_import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
