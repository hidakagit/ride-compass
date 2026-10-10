"""生データから導いたもののPostGISスキーマ（SQLAlchemy ORM）。

**表は「書く段 × 行の母集団」ごとに分ける**。どの表も書く段（`batch/derive_cli.py: STAGES`）は1つで、段は自分の表を
空にしてから埋める。段の指紋は書く表の列を読むので、表に列を1つ足して流れるのは、その表を書く段と後ろの段だけになる。
読む側は、材料の式が読む列を持つ表だけを主キーで結ぶ（`road_graph_repository.py: material_from_clause`）。

| 粒度 | 形・鍵の表（区間を切る段が書く） | 値の表 |
|---|---|---|
| 線（細） | `road_edges`（交差点で切った区間の形） | 値を出す段ごとに1表。区間の鍵が主キーで、`road_edges`を指す |
| 線（粗） | `road_ways`（区間を持つ道の鍵） | 値を出す段ごとに1表。道の鍵が主キーで、`road_ways`を指す |
| 点 | `road_nodes`（区間の端点と、集まる道の本数） | 頂点の値は`road_nodes`を指す。種別は頂点でない点にも付くので指さない |
| 地点 | `stop_places` | 立ち寄り先。道の網とは別の点で、OpenStreetMap由来の値を持たない |
| 住所の区画 | `address_areas` / `address_search_keys` / `address_blocks` | 区画と、区画を引く鍵と、区画の中の街区・地番 |

値の表は、段が値を出せた行だけを持つ表と、母集団の全行を持つ表がある（どちらかは表ごとのdocstringが書く）。値を出せた行だけの
表は、値の列が空を許さない——行が無いことが値が無いことを表す。

面（ラスタ）の派生は持たない——面の生データを読む出口は「そのまま見せる」か「線へ
落とす」のどちらかで、面のままの中間結果を要る相手がいない。

どの取込から作ったかは行ごとに持たず、作り直しごとに全ソースぶんを記録する
（`derived_data_meta.py: DerivedSourceRunRow`）。派生の表であることは表の印（`orm_base.py: DERIVED`）で宣言する。
"""

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    REAL,
    SmallInteger,
    String,
    column,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.orm_base import DERIVED, Base
from app.infrastructure.source_models import Source
from app.domain.address_area import ADDRESS_AREA_LEVELS, BLOCK_KINDS
from app.domain.landcover import PERCENT_CLASSES, landcover_key
from app.domain.stop_place import StopPlaceGroup
from app.domain.traffic import DIRECTIONS, NODE_KINDS, POI_COUNT_KINDS, poi_count_column

#: 数えた値は負にならない。0は数えた結果の「1つも無い」。
#: 件数は小数を持つ——区間の端に乗るものは前後の区間が0.5ずつ持つ（`batch/derive_counts.py`）。
_COUNT_COLUMNS = ("accident_count", "intersection_count") + tuple(
    poi_count_column(kind) for kind in sorted(POI_COUNT_KINDS))

#: 土地被覆の割合の列。クラスが1つ増えてもここは変わらない。
_LANDCOVER_COLUMNS = tuple(
    "lc_" + landcover_key(name) for name, _ in PERCENT_CLASSES)

#: 割合の合計が100からずれてよい幅。REALの丸めだけを吸収する幅で、実際の値はちょうど
#: 100になる。
_PERCENT_SUM_TOLERANCE = 0.1


def count_checks(table: str) -> tuple[CheckConstraint, ...]:
    """数の表（区間・道）の「値が不整合になりえない」制約。読み出し側が毎回この条件を書かずに済むように、入れられない側で止める。"""
    return tuple(CheckConstraint(f"{column} >= 0", name=f"{table}_{column}_not_negative")
                 for column in _COUNT_COLUMNS)


def landcover_checks(table: str) -> tuple[CheckConstraint, ...]:
    """土地被覆の表（区間・道）の制約。有効画素は正で、割合は全部あって合計が100。"""
    total = " + ".join(_LANDCOVER_COLUMNS)
    return (
        CheckConstraint("lc_valid_pixels > 0", name=f"{table}_lc_valid_pixels_positive"),
        *(CheckConstraint(f"{column} BETWEEN 0 AND 100", name=f"{table}_{column}_is_percent")
          for column in _LANDCOVER_COLUMNS),
        CheckConstraint(f"abs(({total}) - 100) <= {_PERCENT_SUM_TOLERANCE}", name=f"{table}_landcover_shares_sum_to_100"),
    )


def vocabulary_check(table: str, column: str, values: frozenset[str]) -> CheckConstraint:
    """派生の段がSQLで直接書く語彙の列に、domainの宣言の外の値を入れさせない制約。NULLは通す。"""
    allowed = ", ".join("'" + value.replace("'", "''") + "'" for value in sorted(values))
    return CheckConstraint(f"{column} IN ({allowed})", name=f"{table}_{column}_known")


def _edge_key(table: str) -> tuple[ForeignKeyConstraint, ...]:
    """区間の値の表が区間を指す外部キー。区間の行を作り直すと、値の行も一緒に消える。"""
    return (ForeignKeyConstraint(["osm_way_id", "segment_index"],
                                 ["road_edges.osm_way_id", "road_edges.segment_index"],
                                 ondelete="CASCADE", name=f"{table}_edge_fkey"),)


class _EdgeKey:
    osm_way_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    segment_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)


class _WayKey:
    osm_way_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("road_ways.osm_way_id", ondelete="CASCADE"), primary_key=True, autoincrement=False)


class _Counts:
    accident_count: Mapped[float] = mapped_column(REAL, nullable=False)
    intersection_count: Mapped[float] = mapped_column(REAL, nullable=False)
    poi_signal: Mapped[float] = mapped_column(REAL, nullable=False)
    poi_crossing: Mapped[float] = mapped_column(REAL, nullable=False)
    poi_stop: Mapped[float] = mapped_column(REAL, nullable=False)
    poi_level_crossing: Mapped[float] = mapped_column(REAL, nullable=False)
    poi_barrier: Mapped[float] = mapped_column(REAL, nullable=False)


class _Landcover:
    lc_valid_pixels: Mapped[int] = mapped_column(Integer, nullable=False)
    lc_water: Mapped[float] = mapped_column(REAL, nullable=False)
    lc_trees: Mapped[float] = mapped_column(REAL, nullable=False)
    lc_flooded_veg: Mapped[float] = mapped_column(REAL, nullable=False)
    lc_crops: Mapped[float] = mapped_column(REAL, nullable=False)
    lc_built: Mapped[float] = mapped_column(REAL, nullable=False)
    lc_bare: Mapped[float] = mapped_column(REAL, nullable=False)
    lc_snow_ice: Mapped[float] = mapped_column(REAL, nullable=False)
    lc_rangeland: Mapped[float] = mapped_column(REAL, nullable=False)


class RoadEdgeRow(Base):
    """道を交差点で切った区間1本。**向きでは分けない**。

    向きが持つ情報はいずれも導ける——方位は両向きぶんを列で持ち（+180°の単純反転に
    しない。地球の丸みを近似しないため）、勾配は符号を反転し、通行の可否は道の属性
    （一方通行）から決まる。有向グラフは探索がメモリ上で組む実行時の構成物で、表が
    両向きの行を持つ必要はない。
    """

    __tablename__ = "road_edges"
    __table_args__ = (
        # 長さ0・頂点1点の区間は作らない。読み出し側が毎回0除算を避ける条件を書かずに済む。
        CheckConstraint("distance_m > 0", name="road_edges_distance_m_positive"),
        CheckConstraint("NOT ST_IsEmpty(geom) AND ST_NumPoints(geom) >= 2",
                        name="road_edges_geom_has_two_points"),
        # 区間単位のズームの路面タイル・道路網の切り出し・事故の帰属は、区間を形の範囲で
        # 直接絞る。無いと区間の全件を総なめにする。
        Index("idx_road_edges_geom", "geom", postgresql_using="gist"),
        {"info": DERIVED},
    )

    #: 親の道。区間は道を切って作る派生なので、対応する道が必ず`road_ways`にある（`derive_topology`が道の行を先に入れる）。
    osm_way_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("road_ways.osm_way_id"), primary_key=True, autoincrement=False)
    #: 道の何番目の区間か。
    segment_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)

    #: 区間の端点。**必ず`road_nodes`に行がある**——頂点の値（`NodeTurnRow`）は`road_nodes`の全行に付くので、探索が
    #: 端点の値を欠かさずに読める。親子の向きがそのままなので外部キーで縛れる（`derive_topology`がノードを先に入れる）。
    from_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("road_nodes.osm_node_id"), nullable=False)
    to_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("road_nodes.osm_node_id"), nullable=False)

    geom: Mapped[object] = mapped_column(
        Geometry("LINESTRING", srid=4326, spatial_index=False), nullable=False)
    #: 長さは丸めない。4.8 cmの区間が実在し、0へ落とすと読み出し側が除算を守る羽目になる。
    distance_m: Mapped[float] = mapped_column(REAL, nullable=False)
    #: 順方向の方位。
    bearing_deg: Mapped[float] = mapped_column(REAL, nullable=False)
    #: 逆向きの方位。**+180°ではない**（球面上では往路と復路の方位はちょうど反対を
    #: 向かない）ため、形状の終点→始点から測った値を持つ。読むたびに`ST_Azimuth`で
    #: 求め直すとグラフ読み込みが目に見えて遅くなるため、列として持つ。
    reverse_bearing_deg: Mapped[float] = mapped_column(REAL, nullable=False)


class RoadWayRow(Base):
    """区間を持つ道1本の鍵。道の値の表と区間が指す親で、値を持たない。"""

    __tablename__ = "road_ways"
    __table_args__ = ({"info": DERIVED},)

    osm_way_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)


class RoadNodeRow(Base):
    """区間の端点（グラフの頂点）1つ。ただの形状頂点は持たない。**生データのノードを覆わない**。

    `branch_count`は**そこに集まる道の本数**。グラフの位相としての次数（隣接する頂点の
    数）とは別物で、2本の枝が同じ次の交差点へ向かうと次数は1つに潰れる。交差点の密度を
    測るのに要るのは枝の本数のほうで、位相としての次数は探索がメモリ上で数える。
    """

    __tablename__ = "road_nodes"
    __table_args__ = ({"info": DERIVED},)

    osm_node_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    branch_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class EdgeElevationRow(_EdgeKey, Base):
    """区間の標高と勾配。値の出た区間だけが行を持つ。

    標高は順方向の値だけ持つ。逆向きは読み出し時に入れ替えと符号反転で導く
    （始点↔終点、上り↔下り、平均勾配は符号反転）。
    """

    __tablename__ = "edge_elevation"
    __table_args__ = (*_edge_key("edge_elevation"), {"info": DERIVED})

    start_elevation_m: Mapped[float] = mapped_column(REAL, nullable=False)
    end_elevation_m: Mapped[float] = mapped_column(REAL, nullable=False)
    elevation_gain_m: Mapped[float] = mapped_column(REAL, nullable=False)
    elevation_loss_m: Mapped[float] = mapped_column(REAL, nullable=False)
    # 標高が付いた区間でも、両端の差が道としてありえない勾配になる区間は平均勾配を持たない
    # （`domain/attributes.py: elevation_values_sql`）。
    average_grade: Mapped[float | None] = mapped_column(REAL, nullable=True)
    #: 作り直しの時点の道のタグで、区間が橋かトンネルだったか。値はこれに依る（両端だけを使う）ので、形が同じでも
    #: これが変われば前回の値を使い回せない。
    on_structure: Mapped[bool] = mapped_column(Boolean, nullable=False)


class EdgeLandcoverRow(_EdgeKey, _Landcover, Base):
    """区間の周りの帯の土地被覆の割合。有効画素の足りた区間だけが行を持つ。"""

    __tablename__ = "edge_landcover"
    __table_args__ = (*_edge_key("edge_landcover"), *landcover_checks("edge_landcover"), {"info": DERIVED})


class EdgeCountsRow(_EdgeKey, _Counts, Base):
    """区間に付く数（事故・交差点・停止要因）。全区間が行を持つ。"""

    __tablename__ = "edge_counts"
    __table_args__ = (*_edge_key("edge_counts"), *count_checks("edge_counts"), {"info": DERIVED})


class WayDirectionRow(_WayKey, Base):
    """道1本の性質（通行方向・上下線分離）。区間粒度の対応物を持たない。全部の道が行を持つ
    （`batch/derive_way_directions.py`が段の最後に数を比べて守る）。"""

    __tablename__ = "way_directions"
    __table_args__ = (vocabulary_check("way_directions", "direction", DIRECTIONS), {"info": DERIVED})

    #: 通行方向（forward/backward/both）。タグからの判断なので、生データではなくここに置く。
    #: 探索が有向グラフをメモリ上で組むときに、逆向きの枝を作ってよいかを決める。
    direction: Mapped[str] = mapped_column(String, nullable=False, server_default="both")

    #: 上下線が分かれた道の片側か。
    divided: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class WayLandcoverRow(_WayKey, _Landcover, Base):
    """道1本の土地被覆の割合（区間の値の長さで重み付けた平均）。割合を持つ区間がある道だけが行を持つ。

    区間の値を道にも持つのは、低ズームのタイルが道1本を1フィーチャーとして塗るため（数も同じ）。区間から集約して作ると
    都心のz12で実測1.2秒かかり、タイル生成が倍になる。
    """

    __tablename__ = "way_landcover"
    __table_args__ = (*landcover_checks("way_landcover"), {"info": DERIVED})


class WayCountsRow(_WayKey, _Counts, Base):
    """道1本の数（区間の和）。全部の道が行を持つ。"""

    __tablename__ = "way_counts"
    __table_args__ = (*count_checks("way_counts"), {"info": DERIVED})


class NodeKindRow(Base):
    """種別（信号・横断歩道・車止め・コンビニ等）の付いたノード。グラフの頂点でない点も持つ。"""

    __tablename__ = "node_kinds"
    __table_args__ = (vocabulary_check("node_kinds", "kind", NODE_KINDS), {"info": DERIVED})

    osm_node_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    #: 分類器が付けた種別。
    kind: Mapped[str] = mapped_column(String, nullable=False)
    #: 近くに信号があるか。交差点の段が頂点の値（`NodeTurnRow`）と1回の探索から書き、種別の信号の読み替え
    #: （`domain/traffic.py: stop_kind_sql`）が読む。
    has_traffic_signals: Mapped[bool] = mapped_column(Boolean, nullable=False)


class NodeTurnRow(Base):
    """グラフの頂点の、曲がる費用が読む値。`road_nodes`の全行が行を持つ。"""

    __tablename__ = "node_turns"
    __table_args__ = ({"info": DERIVED},)

    osm_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("road_nodes.osm_node_id", ondelete="CASCADE"), primary_key=True, autoincrement=False)
    has_traffic_signals: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: そこに集まる道の最大階級。
    max_highway_rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class AddressAreaRow(Base):
    """住所の区画1つ（都道府県・市区町村・区・大字/町・丁目/字）。アドレス・ベース・レジストリから作る
    （`batch/derive_addresses.py`）。表示の名前（全名・辺り）は持たず、`parent_id`をたどって組み立てる。"""

    __tablename__ = "address_areas"
    __table_args__ = (
        vocabulary_check("address_areas", "level", frozenset(ADDRESS_AREA_LEVELS)),
        CheckConstraint("(level = 'prefecture') = (parent_id IS NULL)", name="address_areas_root_is_prefecture"),
        # 境界の中の代表点で区画を探す（境界と区画の結び付け）。
        Index("idx_address_areas_geom", "geom", postgresql_using="gist"),
        {"info": DERIVED},
    )

    #: 都道府県・市区町村・区は全国地方公共団体コード（6桁）、町字はそれに町字ID（7桁）をつないだもの。ABR に大字自身の
    #: 行が無い大字は、子の町字IDの頭4桁に`000`をつないだもの（大字自身の行の町字IDの形）。
    area_id: Mapped[str] = mapped_column(String, primary_key=True)
    #: 1つ粗い区画。丁目・字 → 大字（大字の無い字は市区町村か区）→ 区か市区町村 → 政令市 → 都道府県。都道府県はNULL。
    parent_id: Mapped[str | None] = mapped_column(String, ForeignKey("address_areas.area_id"), nullable=True)
    level: Mapped[str] = mapped_column(String, nullable=False)
    #: 自分の段の名前だけ（「西新宿」「二丁目」）。
    name: Mapped[str] = mapped_column(String, nullable=False)
    #: 郡に属す町村の行だけが持つ郡の名前。
    county_name: Mapped[str | None] = mapped_column(String, nullable=True)
    #: 代表点。大字自身の行の無い大字は子の代表点の重心。
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False), nullable=False)


class AddressSearchKeyRow(Base):
    """住所の区画を引く鍵（表記の揺れを除いた形。`domain/address_area.py: standardize_address`）。1つの区画が書き始める段の
    違う別形を何本も持つ。主キーの索引で等号と前方一致の両方を引く（照合順序`C`）。"""

    __tablename__ = "address_search_keys"
    __table_args__ = (
        # 続きを引くとき、長さごとの件数を数えて短い鍵から引く。
        Index("idx_address_search_keys_continuable", func.length(column("key")), "key",
              postgresql_where=column("continuable")),
        {"info": DERIVED},
    )

    key: Mapped[str] = mapped_column(String(collation="C"), primary_key=True)
    area_id: Mapped[str] = mapped_column(String, ForeignKey("address_areas.area_id"), primary_key=True)
    #: 続き（打ちかけの語を頭に持つ区画）に使う鍵か。大字・町の段までの区画の鍵が真。
    continuable: Mapped[bool] = mapped_column(Boolean, nullable=False)


class AddressBlockRow(Base):
    """住所の区画（丁目・字か大字・町）の中の街区1つ。住居表示の区域はアドレス・ベース・レジストリの街区、それ以外の区域は
    街区レベル位置参照情報の地番から作る（`batch/derive_addresses.py`）。番地まで打った入力が、区画の鍵と番号で引く。"""

    __tablename__ = "address_blocks"
    __table_args__ = (
        vocabulary_check("address_blocks", "kind", frozenset(BLOCK_KINDS)),
        {"info": DERIVED},
    )

    area_id: Mapped[str] = mapped_column(String, ForeignKey("address_areas.area_id"), primary_key=True)
    #: 街区符号か地番（配布の表記のまま。「8」「123」「乙45」）。
    number: Mapped[str] = mapped_column(String(collation="C"), primary_key=True)
    #: 住居表示の街区（`residential`）か地番（`parcel`）。表示名で番号の後ろに付ける語が決まる（`BLOCK_KINDS`）。
    kind: Mapped[str] = mapped_column(String, nullable=False)
    #: 代表点。
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False), nullable=False)


#: 立ち寄り先の表へ地点を入れるソース。
STOP_PLACE_SOURCES: frozenset[str] = frozenset({Source.OVERTURE_PLACE, Source.BUNKA_HERITAGE})


class StopPlaceRow(Base):
    """立ち寄り先1つ。群へ入れ、近くの同じ店をまとめたあとの地点（`batch/derive_stop_places.py`）。

    **OpenStreetMap由来の値（最寄りの道・道へ寄せた座標）を持たない**——ODbLの共有の義務が表にかかる。
    経由地へ寄せるのは要求のたびに計算する。出どころの違う地点（文化財の一覧等）も同じ表へ、`source`で分けて入れる。
    """

    __tablename__ = "stop_places"
    __table_args__ = (
        vocabulary_check("stop_places", "source", STOP_PLACE_SOURCES),
        vocabulary_check("stop_places", "place_group", frozenset(StopPlaceGroup)),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="stop_places_confidence_is_ratio"),
        # タイルが範囲で引く。
        Index("idx_stop_places_geom", "geom", postgresql_using="gist"),
        {"info": DERIVED},
    )

    #: 地点を入れたソース（`source_features.source`と同じ綴り）。
    source: Mapped[str] = mapped_column(String, primary_key=True)
    #: そのソースでの識別子（Overtureの地点のID・まとめた文化財の鍵等）。
    source_key: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    #: 名前の表記の揺れを除いた形（`domain/stop_place.py: normalized_sql`）。地点の検索が引く。
    search_name: Mapped[str] = mapped_column(String, nullable=False)
    place_group: Mapped[str] = mapped_column(String, nullable=False)
    #: 地点が実在する見込み（0〜1）。地図で重なった点のどれを残すかに使う。
    confidence: Mapped[float] = mapped_column(REAL, nullable=False)
    #: チェーンの名前。無ければ個店。
    brand: Mapped[str | None] = mapped_column(String, nullable=True)
    #: 辺り（市区町村から字・丁目まで。位置を含む小地域の境界の名前）。地点の検索が名前に添え、同じ名前の店を見分ける。
    #: 位置を含む名前のある境界が無ければNULL。
    area: Mapped[str | None] = mapped_column(String, nullable=True)
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False), nullable=False)
