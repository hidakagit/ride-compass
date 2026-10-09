"""生データから導いたもののPostGISスキーマ（SQLAlchemy ORM）。

**粒度ごとに1表**にする。表がバッチの写しになると、材料を1つ足すたびに表もバッチも
増え、読む側は表の数だけLEFT JOINを組み立てることになる。

| 粒度 | 表 | 何 |
|---|---|---|
| 点 | `node_materials` | ノードに付く値 |
| 線（粗） | `way_materials` | 道1本に付く値 |
| 線（細） | `road_edges` / `edge_materials` | 交差点で切った区間の形と、区間に付く値 |
| 地点 | `stop_places` | 立ち寄り先。道の網とは別の点で、OpenStreetMap由来の値を持たない |
| 住所の区画 | `address_areas` / `address_search_keys` / `address_boundary_links` | 区画と、区画を引く鍵と、小地域の境界に当たる区画 |

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
from app.domain.address_area import ADDRESS_AREA_LEVELS
from app.domain.landcover import PERCENT_CLASSES, landcover_key
from app.domain.stop_place import StopPlaceGroup
from app.domain.traffic import DIRECTIONS, NODE_KINDS, POI_COUNT_KINDS, poi_count_column

#: 数えた値は負にならない。0は数えた結果の「1つも無い」で、値が無いNULLとは別の値として持つ。
#: 件数は小数を持つ——区間の端に乗るものは前後の区間が0.5ずつ持つ（`batch/derive_counts.py`）。
_COUNT_COLUMNS = ("accident_count", "intersection_count") + tuple(
    poi_count_column(kind) for kind in sorted(POI_COUNT_KINDS))

#: 土地被覆の割合の列。クラスが1つ増えてもここは変わらない。
_LANDCOVER_COLUMNS = tuple(
    "lc_" + landcover_key(name) for name, _ in PERCENT_CLASSES)

#: 割合の合計が100からずれてよい幅。REALの丸めだけを吸収する幅で、実際の値はちょうど
#: 100になる。
_PERCENT_SUM_TOLERANCE = 0.1


def material_value_checks(table: str) -> tuple[CheckConstraint, ...]:
    """区間・道に共通の「値が不整合になりえない」制約。

    読み出し側が毎回この条件を書かずに済むように、入れられない側で止める。
    """
    total = " + ".join(_LANDCOVER_COLUMNS)
    shares = ", ".join(_LANDCOVER_COLUMNS)
    return (
        *(CheckConstraint(f"{column} >= 0", name=f"{table}_{column}_not_negative")
          for column in _COUNT_COLUMNS),
        *(CheckConstraint(f"{column} BETWEEN 0 AND 100", name=f"{table}_{column}_is_percent")
          for column in _LANDCOVER_COLUMNS),
        # 有効画素がNULLなら割合も全部NULL、値があれば正で、割合を全部持ち合計が100。読み手は有効画素がNULLかだけで
        # 割合の有無を決める。式がNULLになる形（`IS NULL OR …`）にしない——CHECKはNULLを通すので、割合が1つ欠けた行が
        # 合計のNULLで通る。
        CheckConstraint(
            f"CASE WHEN lc_valid_pixels IS NULL THEN num_nonnulls({shares}) = 0"
            f" ELSE lc_valid_pixels > 0 AND num_nulls({shares}) = 0"
            f" AND abs(({total}) - 100) <= {_PERCENT_SUM_TOLERANCE} END",
            name=f"{table}_landcover_shares_follow_valid_pixels"),
    )


def vocabulary_check(table: str, column: str, values: frozenset[str]) -> CheckConstraint:
    """派生の段がSQLで直接書く語彙の列に、domainの宣言の外の値を入れさせない制約。NULLは通す。"""
    allowed = ", ".join("'" + value.replace("'", "''") + "'" for value in sorted(values))
    return CheckConstraint(f"{column} IN ({allowed})", name=f"{table}_{column}_known")


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

    #: 親の道。区間は道を切って作る派生なので、対応する道が必ずあり、**`way_materials`に
    #: 行がある**——読み手が道の値を内部結合で引ける（`derive_topology`が道の行を先に入れる）。
    osm_way_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("way_materials.osm_way_id"), primary_key=True, autoincrement=False)
    #: 道の何番目の区間か。
    segment_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)

    #: 区間の端点。**必ず`node_materials`に行がある**——無いと探索が既定値（信号なし・
    #: 階級0）を黙って読み、ターンの費用が実際より安く出る。親子の向きがそのままなので
    #: 外部キーで縛れる（`derive_topology`がノードを先に入れる）。
    from_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("node_materials.osm_node_id"), nullable=False)
    to_node_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("node_materials.osm_node_id"), nullable=False)

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


class EdgeMaterialRow(Base):
    """区間に付く値。**値が無ければNULL**。

    行は`road_edges`と同時に作り、値を出す段がそれぞれ自分の列を埋める。値を出せない区間（標高が取れない・
    土地被覆のタイルが無い等）の列はNULLのまま残る。

    標高は順方向の値だけ持つ。逆向きは読み出し時に入れ替えと符号反転で導く
    （始点↔終点、上り↔下り、平均勾配は符号反転）。
    """

    __tablename__ = "edge_materials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["osm_way_id", "segment_index"],
            ["road_edges.osm_way_id", "road_edges.segment_index"],
            ondelete="CASCADE",
        ),
        *material_value_checks("edge_materials"),
        # 標高の段は4列を1文で書き、戻すときも4列を空にする。読み手は標高の有無を始点の列だけで見る。
        CheckConstraint(
            "num_nonnulls(start_elevation_m, end_elevation_m, elevation_gain_m, elevation_loss_m) IN (0, 4)",
            name="edge_materials_elevation_all_or_none"),
        # 勾配は標高の段が4列と一緒に書く。標高があっても勾配を持たない区間はある（`average_grade`の列）。
        CheckConstraint("average_grade IS NULL OR start_elevation_m IS NOT NULL",
                        name="edge_materials_grade_needs_elevation"),
        {"info": DERIVED},
    )

    osm_way_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    segment_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)

    accident_count: Mapped[float | None] = mapped_column(REAL, nullable=True)
    intersection_count: Mapped[float | None] = mapped_column(REAL, nullable=True)
    poi_signal: Mapped[float | None] = mapped_column(REAL, nullable=True)
    poi_crossing: Mapped[float | None] = mapped_column(REAL, nullable=True)
    poi_stop: Mapped[float | None] = mapped_column(REAL, nullable=True)
    poi_level_crossing: Mapped[float | None] = mapped_column(REAL, nullable=True)
    poi_barrier: Mapped[float | None] = mapped_column(REAL, nullable=True)

    start_elevation_m: Mapped[float | None] = mapped_column(REAL, nullable=True)
    end_elevation_m: Mapped[float | None] = mapped_column(REAL, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(REAL, nullable=True)
    elevation_loss_m: Mapped[float | None] = mapped_column(REAL, nullable=True)
    # 標高が付いた区間でも、両端の差が道としてありえない勾配になる区間は平均勾配を持たない
    # （`domain/attributes.py: elevation_values_sql`）。
    average_grade: Mapped[float | None] = mapped_column(REAL, nullable=True)

    lc_valid_pixels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lc_water: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_trees: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_flooded_veg: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_crops: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_built: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_bare: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_snow_ice: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_rangeland: Mapped[float | None] = mapped_column(REAL, nullable=True)


class WayMaterialRow(Base):
    """道1本に付く値。

    区間粒度と重なる値（事故・交差点・停止要因・土地被覆）をここにも持つのは、低ズームの
    タイルが道1本を1フィーチャーとして塗るため。区間から集約して作ると都心のz12で
    実測1.2秒かかり、タイル生成が倍になる。

    `direction`と`divided`は道1本の性質で、区間粒度の対応物を持たない。
    """

    __tablename__ = "way_materials"
    __table_args__ = (
        *material_value_checks("way_materials"),
        vocabulary_check("way_materials", "direction", DIRECTIONS),
        {"info": DERIVED},
    )

    osm_way_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=False)

    accident_count: Mapped[float | None] = mapped_column(REAL, nullable=True)
    intersection_count: Mapped[float | None] = mapped_column(REAL, nullable=True)
    poi_signal: Mapped[float | None] = mapped_column(REAL, nullable=True)
    poi_crossing: Mapped[float | None] = mapped_column(REAL, nullable=True)
    poi_stop: Mapped[float | None] = mapped_column(REAL, nullable=True)
    poi_level_crossing: Mapped[float | None] = mapped_column(REAL, nullable=True)
    poi_barrier: Mapped[float | None] = mapped_column(REAL, nullable=True)

    lc_valid_pixels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lc_water: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_trees: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_flooded_veg: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_crops: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_built: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_bare: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_snow_ice: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_rangeland: Mapped[float | None] = mapped_column(REAL, nullable=True)

    #: 通行方向（forward/backward/both）。タグからの判断なので、生データではなくここに置く。
    #: 探索が有向グラフをメモリ上で組むときに、逆向きの枝を作ってよいかを決める。
    direction: Mapped[str] = mapped_column(String, nullable=False, server_default="both")

    #: 上下線が分かれた道の片側か。
    divided: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class NodeMaterialRow(Base):
    """ノードに付く値。

    行を持つのは「グラフの頂点になる点」か「種別が付く点」だけで、ただの形状頂点は
    持たない。**生データのノードを覆わない**。

    `branch_count`は**そこに集まる道の本数**。グラフの位相としての次数（隣接する頂点の
    数）とは別物で、2本の枝が同じ次の交差点へ向かうと次数は1つに潰れる。交差点の密度を
    測るのに要るのは枝の本数のほうで、位相としての次数は探索がメモリ上で数える。
    """

    __tablename__ = "node_materials"
    __table_args__ = (vocabulary_check("node_materials", "kind", NODE_KINDS), {"info": DERIVED})

    osm_node_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    #: 分類器が付ける種別（信号・横断歩道・車止め・コンビニ等）。ただの形状頂点・
    #: 交差点はどの種別にも当たらずNULLになる。
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    # 既定値はDB側に持つ。ORMの`default=`はPython経由の挿入にしか効かず、取込や導出が
    # 生SQLで書く行に適用されない。
    branch_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0")
    has_traffic_signals: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false")
    max_highway_rank: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0")


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


class AddressBoundaryLinkRow(Base):
    """e-Stat の小地域の境界1つと、それに当たる住所の区画（大字・町か丁目・字）。境界の多角形は生データに置いたまま読む。"""

    __tablename__ = "address_boundary_links"
    __table_args__ = ({"info": DERIVED},)

    #: 境界の小地域のコード（生データ`estat_small_area`の鍵）。
    key_code: Mapped[str] = mapped_column(String, primary_key=True)
    area_id: Mapped[str] = mapped_column(String, ForeignKey("address_areas.area_id"), nullable=False)


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
    #: 辺り（市区町村から字・丁目まで。位置を住所の辞書で逆引きした名前）。地点の検索が名前に添え、同じ名前の店を見分ける。
    #: 逆引きが旧い住所の節にしか当たらなければNULL。
    area: Mapped[str | None] = mapped_column(String, nullable=True)
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False), nullable=False)
