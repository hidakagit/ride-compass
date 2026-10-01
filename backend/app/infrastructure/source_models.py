"""外部ソースの生データを、ソースによらない1つの形で持つPostGISスキーマ（SQLAlchemy ORM）。

点・線・面を同じ骨格へ載せる——ラスタはタイル1枚を1行として扱うため、面も「識別子＋
範囲＋属性＋実体」に収まる。取込の経路は1本で、ソースごとに違うのは外部の形を読む
アダプタだけである。

まっさらなDBのスキーマ作成（`create_tables`）と実DBとの突き合わせは`declared_metadata()`の
全表を見るため、他のORMと同じ`Base`（`orm_base.py`）を使う。
"""

from datetime import datetime
from enum import StrEnum

from geoalchemy2 import Geometry, Raster
from sqlalchemy import (
    DDL,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    event,
    func,
    select,
)
from sqlalchemy.sql.selectable import ScalarSelect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.orm_base import Base


class Source(StrEnum):
    """コードが名指すソース。値は`batch/source_profile.yaml`の`name`と同じ綴り。

    取込の経路はソースを名指さない（プロファイルが挙げたものをそのまま取り込む）ので、
    ここに在るのは派生・読み手が中身を知って読むソースだけである。
    """

    OSM_WAY = "osm_way"
    OSM_NODE = "osm_node"
    ACCIDENT = "accident"
    DEM = "dem"
    LULC = "lulc"


class SourceRunStatus(StrEnum):
    """取込のrunの状態。取込は開くときに`running`を書き、失敗すれば`failed`、書き終えれば
    `succeeded`で閉じる（`batch/ingest.py`）。プロセスごと止まったrunは閉じる者がいないので
    `running`のまま残る。生データは`succeeded`のrunの行だけが入っている。表の`status`は
    この値しか入れさせない。"""

    RUNNING = "running"
    FAILED = "failed"
    SUCCEEDED = "succeeded"


#: 取込のrunの状態と、管理画面に出す呼び名。`running`は中断したrunも指すので、呼び名はその両方を言う。
SOURCE_RUN_STATUS_LABELS: dict[str, str] = {
    SourceRunStatus.RUNNING: "実行中か中断",
    SourceRunStatus.FAILED: "失敗",
    SourceRunStatus.SUCCEEDED: "成功",
}


class SourceRunRow(Base):
    """取込1回ぶんの記録。

    派生データはこの`run_id`を指し、「どの世代の生データから作ったか」を表す。生データを
    差し替えると新しいrunになり、下流は自分が指すrunが最新でないことで古いと分かる。

    `profile`はそのとき適用した絞り込みの宣言を丸ごと持つ。範囲を変えて取り直したのか、
    同じ範囲を取り直したのかは、これが無いと後から区別できない。
    """

    __tablename__ = "source_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in SourceRunStatus) + ")",
            name="source_runs_status_known"),
    )

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
    __table_args__ = (
        # 生データは範囲や近さで引かれる（事故を区間へ割り当てる、信号を交差点へ割り当てる）。
        # パーティションした表の索引なので、取込が作る子パーティションにもPostgreSQLが同じ
        # 索引を張る。
        Index("idx_source_features_geom", "geom", postgresql_using="gist"),
        {"postgresql_partition_by": "LIST (source)"},
    )

    source: Mapped[str] = mapped_column(String, primary_key=True)
    #: 外部が持つ識別子（OSMのid・事故の自然キー・タイルの z/x/y 等）。
    natural_key: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_runs.run_id"), nullable=False
    )
    geom: Mapped[object] = mapped_column(Geometry(srid=4326, spatial_index=False), nullable=False)
    attrs: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    #: 面のソースの画素。線・点のソースでは空。
    rast: Mapped[object | None] = mapped_column(Raster, nullable=True)


def latest_succeeded_run_sql(source: Source) -> str:
    """そのソースの成功した最新の取込1行（`source_runs`の全列）を指す副問い合わせ。

    生データに入っているのはこのrunの行だけなので、派生の基準も取込の範囲もここから読む。
    """
    return latest_succeeded_run_by_column_sql(f"'{source}'")


def latest_succeeded_run_by_column_sql(source_column: str) -> str:
    """`latest_succeeded_run_sql`の、ソースを外側の問い合わせの列（`r.source`等）で指す形。
    ソースごとに並べる読み手（取込の一覧・鮮度台帳）が、行ごとに相関させて使う。"""
    return (f"(SELECT * FROM {SourceRunRow.__tablename__} WHERE source = {source_column}"
            f" AND status = '{SourceRunStatus.SUCCEEDED}' ORDER BY run_id DESC LIMIT 1)")


def succeeded_run_count() -> ScalarSelect[int]:
    """成功した取込の数（全ソース通し）を出す副問い合わせ。生データの世代として使う。

    どのソースの取込が成功しても1つ増え、失敗した取込では動かない（runの行は消さず、成功は
    別の状態へ戻らない）。成功した`run_id`の最大では代用できない——`run_id`は開いた順に振られる
    ため、先に開いた取込が後に開いた取込より遅れて成功すると、最大は動かない。
    """
    return (select(func.count()).select_from(SourceRunRow)
            .where(SourceRunRow.status == SourceRunStatus.SUCCEEDED).scalar_subquery())


# --- ソースごとの生データを読む副問い合わせ ---
#
# 生データの入れ方（`source`の値・キーの型）はここだけが知る。読み手は`source_features`を
# ソース名で絞らず、ここの副問い合わせを置く。
#
# 道とノードは、材料の式（`domain/material_sql.py`）が読む別名`w`（道）とノードの別名の中身。
# よく引くタグを列として出し、式の側が`attrs`の構造を知らなくて済むようにする。

_TABLE = SourceFeatureRow.__tablename__


def _ways_select(extra_columns: tuple[str, ...]) -> str:
    columns = ("natural_key::bigint AS osm_way_id", "geom", "attrs AS tags",
               "attrs->>'highway' AS highway", "attrs->>'surface' AS surface", *extra_columns)
    return "SELECT " + ", ".join(columns) + f" FROM {_TABLE}"


def ways_source_sql(sampling: str = "", *, extra_columns: tuple[str, ...] = ()) -> str:
    """道の生データの全行を指す副問い合わせ（別名`w`で置く）。

    `sampling`は`TABLESAMPLE ...`を入れる口。抽選は副問い合わせの**中**へ置く
    （外に付けると構文エラーになる）。`extra_columns`は生データの表の列を
    そのまま足す口（構成ノードの並び`payload`等、材料の式が読まない列を要る読み手向け）。
    """
    return f"({_ways_select(extra_columns)} {sampling} WHERE source = '{Source.OSM_WAY}')"


WAYS_SOURCE_SQL = ways_source_sql()


def ways_lookup_sql(key_expr: str) -> str:
    """道を1本だけ引くときの副問い合わせ（LATERALの中に置く）。

    **照合はtextのまま行う。** 主キーは`(source, natural_key)`で、`natural_key::bigint`
    と比べると索引が使えず、道の全件に対する総当たりになる（実測: 区間1,766本の材料
    取得で2,124万行を捨てて2.95秒）。
    """
    return (f"({_ways_select(())} "
            f"WHERE source = '{Source.OSM_WAY}' AND natural_key = ({key_expr})::text)")


_NODES_SELECT = f"SELECT natural_key::bigint AS osm_node_id, geom, attrs AS tags FROM {_TABLE}"

#: ノードの生データの全件を指す副問い合わせ（空間で絞る読み手・全件を流す派生の段向け）。
#: キーで引くなら`nodes_lookup_sql`を使う——ここの`osm_node_id`で突き合わせると、
#: `ways_lookup_sql`と同じ理由で主キーの索引が使えない。
NODES_SOURCE_SQL = f"({_NODES_SELECT} WHERE source = '{Source.OSM_NODE}')"


def nodes_lookup_sql(key_expr: str) -> str:
    """ノードを1点だけ引くときの副問い合わせ（LATERALの中に置く）。照合をtextのまま
    行う理由は`ways_lookup_sql`と同じ。"""
    return f"({_NODES_SELECT} WHERE source = '{Source.OSM_NODE}' AND natural_key = ({key_expr})::text)"


#: 事故の生データ（1件=1点）。判定の式（`domain/accident.py`）が読む別名`a`の中身。
ACCIDENTS_SOURCE_SQL = f"(SELECT geom, attrs FROM {_TABLE} WHERE source = '{Source.ACCIDENT}')"


def _raster_tiles_sql(source: Source) -> str:
    return f"(SELECT rast, attrs, geom FROM {_TABLE} WHERE source = '{source}')"


#: 標高タイル（1枚=1行）。`attrs`に製品・ズーム・番地・幅・尺度を持つ。
DEM_TILES_SQL = _raster_tiles_sql(Source.DEM)

#: 土地被覆タイル（1枚=1行）。
LANDCOVER_TILES_SQL = _raster_tiles_sql(Source.LULC)


def source_keys_sql(source: Source) -> str:
    """そのソースの生データの識別子（`natural_key`、text）を全件指す副問い合わせ。
    派生が生データを1件残らず覆うかを数える読み手（鮮度台帳）向け。"""
    return f"(SELECT natural_key FROM {_TABLE} WHERE source = '{source}')"


# 圧縮しない指定は型では表せないので、表を作った直後に当てる。親へ当てれば以後の
# パーティションも引き継ぐ。
for _column in ("payload", "rast"):
    # 1文ずつ当てる。`;`でつなぐと、準備された文に複数コマンドは入らないと言って落ちる。
    event.listen(
        SourceFeatureRow.__table__,
        "after_create",
        DDL(f"ALTER TABLE source_features ALTER COLUMN {_column} SET STORAGE EXTERNAL"),
    )
