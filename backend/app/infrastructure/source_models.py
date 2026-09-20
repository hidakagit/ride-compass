"""外部ソースの生データを、ソースによらない1つの形で持つPostGISスキーマ（SQLAlchemy ORM）。

点・線・面を同じ骨格へ載せる——ラスタはタイル1枚を1行として扱うため、面も「識別子＋
範囲＋属性＋実体」に収まる。取込の経路は1本で、ソースごとに違うのは外部の形を読む
アダプタだけである。

DBの起動時初期化（`create_tables`の`Base.metadata.create_all`）へ乗せるため、
`road_graph_models.py`と同じ`Base`を使う。
"""

from datetime import datetime

from geoalchemy2 import Geometry, Raster
from sqlalchemy import (
    DDL,
    BigInteger,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.orm_base import Base


class SourceRunRow(Base):
    """取込1回ぶんの記録。

    派生データはこの`run_id`を指し、「どの世代の生データから作ったか」を表す。生データを
    差し替えると新しいrunになり、下流は自分が指すrunが最新でないことで古いと分かる。

    `profile`はそのとき適用した絞り込みの宣言を丸ごと持つ。範囲を変えて取り直したのか、
    同じ範囲を取り直したのかは、これが無いと後から区別できない。
    """

    __tablename__ = "source_runs"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: 取得元（URL・ファイル名・配信元のタイムスタンプ）。
    origin: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: 適用した絞り込みの宣言。
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False)
    counts: Mapped[dict] = mapped_column(JSONB, nullable=False)


class SourceFeatureRow(Base):
    """外部ソースの生データ1件。

    `source`でリスト・パーティションする。あるソースを丸ごと差し替えても、他のソースの
    行を巻き込まない。**子パーティションは取込の側が作る**——どのソースが在るかはデータで
    決まり、宣言では決まらない。

    `attrs`は外部が持っていた属性をそのまま入れる袋で、取込の時点では何も捨てない。
    `payload`は解釈の要る配列実体（ラスタの画素・OSMの参照ノードid列・ベクタタイルの
    本体）で、属性として読めないものを置く。

    面（ラスタタイル）は`rast`で持つ。位置・画素の大きさ・型・欠測値をこの値自身が
    持つため、読み手が`attrs`から形を組み立てなくてよい。**圧縮しない**——画素は
    1つずつ引くので、圧縮されていると1回のアクセスごとに値全体が伸長される。代償として
    面のデータは数倍になる。
    """

    __tablename__ = "source_features"
    __table_args__ = {"postgresql_partition_by": "LIST (source)"}

    source: Mapped[str] = mapped_column(String, primary_key=True)
    #: 外部が持つ識別子（OSMのid・事故の自然キー・タイルの z/x/y 等）。
    natural_key: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_runs.run_id"), nullable=False
    )
    geom: Mapped[object] = mapped_column(Geometry(srid=4326), nullable=False)
    attrs: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    #: 面のソースの画素。線・点のソースでは空。
    rast: Mapped[object | None] = mapped_column(Raster, nullable=True)


# 圧縮しない指定は型では表せないので、表を作った直後に当てる。親へ当てれば以後の
# パーティションも引き継ぐ。
for _column in ("payload", "rast"):
    # 1文ずつ当てる。`;`でつなぐと、準備された文に複数コマンドは入らないと言って落ちる。
    event.listen(
        SourceFeatureRow.__table__,
        "after_create",
        DDL(f"ALTER TABLE source_features ALTER COLUMN {_column} SET STORAGE EXTERNAL"),
    )
