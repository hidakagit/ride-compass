"""警察庁交通事故統計データのPostGISスキーマ（SQLAlchemy ORM）。

外部静的データソース T50（docs/external-data-sources-review-2026-08-16.md §4.1）。
取込元がOSMではないため road_graph_models.py の osm_raw_pois 等とはテーブルを分けるが、
DBの起動時初期化（create_tables の Base.metadata.create_all）に乗せるため同じ Base を使う。
"""

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.road_graph_models import Base


class AccidentPointRow(Base):
    """警察庁本票CSV1行＝1事故の生データ（選別済み点＋GiST、osm_raw_pois型）。

    accident_idは都道府県コード・警察署等コード・本票番号・発生年を連結した文字列
    （domain/accident.py: build_accident_id）。年次再取込みで冪等にUPSERTできるよう、
    本票のIDそのものではなく取込側で組み立てる合成キーにしている。
    """

    __tablename__ = "accident_points"

    accident_id: Mapped[str] = mapped_column(String, primary_key=True)
    occurred_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fatal: Mapped[bool] = mapped_column(Boolean, nullable=False)
    involves_bicycle: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # 昼夜・天候・道路形状等、許可リストの生コードのみ（根拠のない推測をしない方針をここにも適用）。
    attrs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    geom = mapped_column(Geometry(geometry_type="POINT", srid=4326, spatial_index=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccidentImportRunRow(Base):
    """事故データ取込バッチ（app/batch/import_accidents.py）の実行記録（osm_import_runs型）。"""

    __tablename__ = "accident_import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_year: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # running | succeeded | failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accident_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
