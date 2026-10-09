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

from app.domain.accident import PartyType
from app.infrastructure.orm_base import Base


class Source(StrEnum):
    """コードが名指すソース。値は`batch/source_profile.yaml: name`と同じ綴り。

    取込の経路はソースを名指さない（プロファイルが挙げたものをそのまま取り込む）ので、
    ここに在るのは派生・読み手が中身を知って読むソースだけである。
    """

    OSM_WAY = "osm_way"
    OSM_NODE = "osm_node"
    ACCIDENT = "accident"
    OVERTURE_PLACE = "overture_place"
    BUNKA_HERITAGE = "bunka_heritage"
    ABR = "abr"
    ESTAT_SMALL_AREA = "estat_small_area"
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


#: 道の種別を持つタグ。道の生データはかならずこのタグを持つ——道路網の階級・優先関係・材料の多くが
#: この値から決まり、無い道をどう読むかを読み手ごとに決めさせないため。取込の条件（`osm_pbf.py: OsmWayRows`）と
#: 表の検査制約の両方がここを読む。
WAY_KIND_TAG = "highway"

#: 取込のrunの状態と、管理画面に出す呼び名。`running`は中断したrunも指すので、呼び名はその両方を言う。
SOURCE_RUN_STATUS_LABELS: dict[str, str] = {
    SourceRunStatus.RUNNING: "実行中か中断",
    SourceRunStatus.FAILED: "失敗",
    SourceRunStatus.SUCCEEDED: "成功",
}


class SourceRunRow(Base):
    """取込1回ぶんの記録。

    派生の作り直しはこの`run_id`を記録し（`derived_data_meta.py: DerivedSourceRunRow`）、「どの世代の
    生データから作ったか」を表す。生データを差し替えると新しいrunになり、記録したrunが最新でないことで
    派生が古いと分かる。

    `profile`はそのとき適用した絞り込みの宣言を丸ごと持つ。範囲を変えて取り直したのか、
    同じ範囲を取り直したのかは、これが無いと後から区別できない。
    """

    __tablename__ = "source_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in SourceRunStatus) + ")",
            name="source_runs_status_known"),
        # 閉じたrunだけが終わった時刻を持つ。読み手は成功のrunの時刻を必ずあるものとして読む。
        CheckConstraint(
            f"(status = '{SourceRunStatus.RUNNING}') = (finished_at IS NULL)",
            name="source_runs_finished_when_closed"),
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
        CheckConstraint(f"source <> '{Source.OSM_WAY}' OR attrs->>'{WAY_KIND_TAG}' IS NOT NULL",
                        name="source_features_way_has_kind"),
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
    #: 面のソースの画素。線・点のソースでは空。外形の索引は張らない——面のタイルは`geom`で
    #: 絞るか番地で引き、`rast`で範囲を絞る読み手はいない。
    rast: Mapped[object | None] = mapped_column(Raster(spatial_index=False), nullable=True)


def latest_succeeded_run_sql(source: Source) -> str:
    """そのソースの成功した最新の取込1行（`source_runs`の全列）を指す副問い合わせ。

    生データに入っているのはこのrunの行だけなので、派生の基準も取込の範囲もここから読む。
    """
    return latest_succeeded_run_by_column_sql(f"'{source}'")


def latest_succeeded_run_by_column_sql(source_column: str) -> str:
    """`latest_succeeded_run_sql`の、ソースを外側の問い合わせの列（`r.source`等）で指す形。
    ソースごとに並べる読み手（取込の一覧）が、行ごとに相関させて使う。"""
    return (f"(SELECT * FROM {SourceRunRow.__tablename__} WHERE source = {source_column}"
            f" AND status = '{SourceRunStatus.SUCCEEDED}' ORDER BY run_id DESC LIMIT 1)")


#: 取込の成功したソースごとに、成功した最新の取込（`source`・`run_id`）を1行ずつ出す問い合わせ。
#: 派生の作り直しが「どの取込から作ったか」として記録し（`batch/derive_cli.py`）、鮮度台帳がその記録と比べる。
LATEST_SUCCEEDED_RUNS_SQL = (
    f"SELECT DISTINCT ON (source) source, run_id FROM {SourceRunRow.__tablename__}"
    f" WHERE status = '{SourceRunStatus.SUCCEEDED}' ORDER BY source, run_id DESC")


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
               f"attrs->>'{WAY_KIND_TAG}' AS highway", "attrs->>'surface' AS surface", *extra_columns)
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


#: 本票の当事者種別のコード（警察庁のコード表 31_koudohyou_toujisyasyuetu.csv。
#: https://www.npa.go.jp/publications/statistics/koutsuu/opendata/koudohyou/）→判定が名指す種別。
PARTY_TYPE_CODES: dict[PartyType, str] = {PartyType.BICYCLE: "51", PartyType.POWER_ASSISTED_BICYCLE: "52"}


def _party_type_sql(column: str) -> str:
    """当事者種別の列を`PartyType`の値へ読み替える式。表に無いコードは`OTHER`、列が無ければNULL。"""
    raw = f"attrs->>'{column}'"
    whens = " ".join(f"WHEN '{code}' THEN '{party}'" for party, code in PARTY_TYPE_CODES.items())
    return f"CASE WHEN {raw} IS NOT NULL THEN CASE {raw} {whens} ELSE '{PartyType.OTHER}' END END"


#: 事故の生データ（1件=1点）。判定の式（`domain/accident.py`）が読む別名`a`の中身。本票CSVの列名（日本語。
#: 取込は列を捨てずに`attrs`へ入れる）はここだけが名指し、式へは読み替えた列で渡す。死者数と発生年は
#: ゼロ埋めの数字列で入っている。
ACCIDENTS_SOURCE_SQL = (
    "(SELECT geom,"
    " (attrs->>'死者数')::int AS deaths,"
    f" {_party_type_sql('当事者種別（当事者A）')} AS party_type_a,"
    f" {_party_type_sql('当事者種別（当事者B）')} AS party_type_b,"
    " (attrs->>'発生日時　　年')::int AS occurred_year"
    f" FROM {_TABLE} WHERE source = '{Source.ACCIDENT}')"
)


#: Overture の地点の生データ（1件=1点）。群の判断（`domain/stop_place.py`）が読む列へ読み替える。配布の列の
#: 入れ子（`names.primary` 等）はここだけが名指す。ウェブサイト・電話は文字列の配列か、無ければ null（jsonb）。
OVERTURE_PLACES_SOURCE_SQL = (
    "(SELECT natural_key AS overture_id, geom,"
    " attrs->'names'->>'primary' AS name,"
    " attrs->'brand'->'names'->>'primary' AS brand,"
    " (attrs->>'confidence')::float8 AS confidence,"
    " attrs->'taxonomy'->'hierarchy' AS hierarchy,"
    " attrs->'websites' AS websites,"
    " attrs->'phones' AS phones"
    f" FROM {_TABLE} WHERE source = '{Source.OVERTURE_PLACE}')"
)

#: 国の指定・登録の文化財の建造物（1件=1つの建物）。寺社の判断（`domain/stop_place.py`）が読む列へ読み替える。
#: ジャパンサーチの項目の列（文化遺産オンラインの所有者の項目`bunka-14-s`）はここだけが名指す。
BUNKA_HERITAGES_SOURCE_SQL = (
    "(SELECT natural_key AS heritage_id, geom,"
    " attrs->>'bunka-14-s' AS owners"
    f" FROM {_TABLE} WHERE source = '{Source.BUNKA_HERITAGE}')"
)


def _abr_sql(columns: dict[str, str], kind: str) -> str:
    """アドレス・ベース・レジストリの生データのうち`kind`の行。列は ABR の列の名前 → 出す名前（空の値は空の文字列）。"""
    selected = ", ".join(f"coalesce(attrs->>'{raw}', '') AS {name}" for raw, name in columns.items())
    return (f"(SELECT {selected}, ST_X(geom) AS lon, ST_Y(geom) AS lat"
            f" FROM {_TABLE} WHERE source = '{Source.ABR}' AND {kind})")


#: アドレス・ベース・レジストリ（1回の取込に都道府県・市区町村・町字が混ざる）の都道府県（1件=1つの代表点）。
#: 3種は持つ列で分ける（町字だけが`machiaza_id`を、市区町村と町字だけが`city`を持つ）。ABR の列の名前はここだけが名指す。
ABR_PREFECTURES_SOURCE_SQL = _abr_sql(
    {"lg_code": "code", "pref": "name", "ablt_date": "abolished"}, "NOT attrs ? 'city'")

#: ABR の市区町村（政令市の区を含む。区の行は`ward`を持つ）。
ABR_CITIES_SOURCE_SQL = _abr_sql(
    {"lg_code": "code", "pref": "prefecture", "county": "county", "city": "city", "ward": "ward",
     "ablt_date": "abolished"},
    "attrs ? 'city' AND NOT attrs ? 'machiaza_id'")

#: ABR の町字（大字・町、丁目、小字等。町字区分`machiaza_type`で分かれる）。`city_code`は属す市区町村（区）の`code`。
ABR_TOWNS_SOURCE_SQL = _abr_sql(
    {"lg_code": "city_code", "machiaza_id": "town_id", "machiaza_type": "town_type", "pref": "prefecture",
     "county": "county", "city": "city", "ward": "ward", "oaza_cho": "oaza", "chome": "chome", "koaza": "koaza",
     "ablt_date": "abolished"},
    "attrs ? 'machiaza_id'")

#: e-Stat の小地域の境界（1件=1つの小地域の多角形）。`city_code`は都道府県＋市区町村の5桁、`name`は小地域の名前
#: （町丁・字等。名前の無い小地域は空）。配布の dbf の列の名前はここだけが名指す。
ESTAT_SMALL_AREAS_SOURCE_SQL = (
    "(SELECT natural_key AS key_code, (attrs->>'PREF') || (attrs->>'CITY') AS city_code,"
    " coalesce(attrs->>'S_NAME', '') AS name, geom"
    f" FROM {_TABLE} WHERE source = '{Source.ESTAT_SMALL_AREA}')"
)


def _raster_tiles_sql(source: Source) -> str:
    return f"(SELECT rast, attrs, geom FROM {_TABLE} WHERE source = '{source}')"


#: 標高タイル（1枚=1行）。`attrs`に製品・ズーム・番地・幅・尺度を持つ。
DEM_TILES_SQL = _raster_tiles_sql(Source.DEM)

#: 土地被覆タイル（1枚=1行）。
LANDCOVER_TILES_SQL = _raster_tiles_sql(Source.LULC)


# 圧縮しない指定は型では表せないので、表を作った直後に当てる。親へ当てれば以後の
# パーティションも引き継ぐ。
for _column in ("payload", "rast"):
    # 1文ずつ当てる。`;`でつなぐと、準備された文に複数コマンドは入らないと言って落ちる。
    event.listen(
        SourceFeatureRow.__table__,
        "after_create",
        DDL(f"ALTER TABLE source_features ALTER COLUMN {_column} SET STORAGE EXTERNAL"),
    )
