"""生データから導いたもののPostGISスキーマ（SQLAlchemy ORM）。

**粒度ごとに1表**にする。表がバッチの写しになると、材料を1つ足すたびに表もバッチも
増え、読む側は表の数だけLEFT JOINを組み立てることになる。

| 粒度 | 表 | 何 |
|---|---|---|
| 点 | `node_materials` | ノードに付く値 |
| 線（粗） | `way_materials` | 道1本に付く値 |
| 線（細） | `road_edges` / `edge_materials` | 交差点で切った区間の形と、区間に付く値 |

面（ラスタ）の派生は持たない——面の生データを読む出口は「そのまま見せる」か「線へ
落とす」のどちらかで、面のままの中間結果を要る相手がいない。

`source_run_id`はどの取込世代から作ったかを指す。生データを差し替えると新しいrunになり、
これが最新でないことで古いと分かる。
"""

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    REAL,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.orm_base import Base

#: NULLが「まだ計算していない」ではなく「確定して値が無い」を意味する列に付ける印。
#: 鮮度台帳（`derived_data_freshness.py`）はこの印のある列を未計算として数えない——
#: 付け忘れても安全側（未計算として鳴る）に倒れる。
ABSENT_OK = {"null_means_absent": True}


class RoadEdgeRow(Base):
    """道を交差点で切った区間1本。**向きでは分けない**。

    向きが持つ情報はいずれも導ける——方位は両向きぶんを列で持ち（+180°の単純反転に
    しない。地球の丸みを近似しないため）、勾配は符号を反転し、通行の可否は道の属性
    （一方通行）から決まる。有向グラフは探索がメモリ上で組む実行時の構成物で、表が
    両向きの行を持つ必要はない。

    空間の索引は持たない。範囲で絞るときは親の道（`osm_way`）を先に絞り、その区間を
    主キーの先頭列で引く。
    """

    __tablename__ = "road_edges"

    #: 親の道。区間は道を切って作る派生なので、対応する道が必ずある。
    osm_way_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    #: 道の何番目の区間か。
    segment_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)

    from_node_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    to_node_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    geom: Mapped[object] = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False)
    distance_m: Mapped[float] = mapped_column(REAL, nullable=False)
    #: 順方向の方位。
    bearing_deg: Mapped[float] = mapped_column(REAL, nullable=False)
    #: 逆向きの方位。**+180°ではない**（球面上では往路と復路の方位はちょうど反対を
    #: 向かない）ため、形状の終点→始点から測った値を持つ。読むたびに`ST_Azimuth`で
    #: 求め直すとグラフ読み込みが目に見えて遅くなるため、列として持つ。
    reverse_bearing_deg: Mapped[float] = mapped_column(REAL, nullable=False)

    source_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_runs.run_id"), nullable=False
    )


class EdgeMaterialRow(Base):
    """区間に付く値。**未計算はNULL**。

    行は`road_edges`と同時に作り、値を出すバッチがそれぞれ自分の列を埋める。どの列が
    まだ埋まっていないかは「その列がNULLの行数」で一様に数えられる。

    標高は順方向の値だけ持つ。逆向きは読み出し時に入れ替えと符号反転で導く
    （始点↔終点、上り↔下り、平均勾配は符号反転、最大↔最小は入れ替えて符号反転）。
    """

    __tablename__ = "edge_materials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["osm_way_id", "segment_index"],
            ["road_edges.osm_way_id", "road_edges.segment_index"],
            ondelete="CASCADE",
        ),
    )

    osm_way_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    segment_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)

    accident_count: Mapped[float | None] = mapped_column(REAL, nullable=True)
    intersection_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    poi_signal: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    poi_crossing: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    poi_stop: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    poi_level_crossing: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    poi_barrier: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    start_elevation_m: Mapped[float | None] = mapped_column(REAL, nullable=True)
    end_elevation_m: Mapped[float | None] = mapped_column(REAL, nullable=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(REAL, nullable=True)
    elevation_loss_m: Mapped[float | None] = mapped_column(REAL, nullable=True)
    # 橋・高架・トンネルは値を持たない（地表面の標高は道の勾配ではない）。
    average_grade: Mapped[float | None] = mapped_column(REAL, nullable=True, info=ABSENT_OK)
    max_grade: Mapped[float | None] = mapped_column(REAL, nullable=True)
    min_grade: Mapped[float | None] = mapped_column(REAL, nullable=True)

    lc_valid_pixels: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lc_water: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_trees: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_flooded_veg: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_crops: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_built: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_bare: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_snow_ice: Mapped[float | None] = mapped_column(REAL, nullable=True)
    lc_rangeland: Mapped[float | None] = mapped_column(REAL, nullable=True)

    source_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_runs.run_id"), nullable=False
    )


class WayMaterialRow(Base):
    """道1本に付く値。

    区間粒度と重なる値（事故・交差点・停止要因・土地被覆）をここにも持つのは、低ズームの
    タイルが道1本を1フィーチャーとして塗るため。区間から集約して作ると都心のz12で
    実測1.2秒かかり、タイル生成が倍になる。

    `divided`と指定路線のマッチ率は道1本の性質で、区間粒度の対応物を持たない。
    """

    __tablename__ = "way_materials"

    osm_way_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    accident_count: Mapped[float | None] = mapped_column(REAL, nullable=True)
    intersection_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    poi_signal: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    poi_crossing: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    poi_stop: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    poi_level_crossing: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    poi_barrier: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

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
    # 指定路線のマッチ率（0〜1）。指定が無ければNULL。列名は`designation_`＋種別名で、
    # 種別が増えたときに列を機械的に決められるようにする（`domain/designation.py:
    # DESIGNATION_IMPORT_KINDS`）。
    designation_emergency_transport: Mapped[float | None] = mapped_column(
        Float, nullable=True, info=ABSENT_OK)
    designation_critical_logistics: Mapped[float | None] = mapped_column(
        Float, nullable=True, info=ABSENT_OK)

    source_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_runs.run_id"), nullable=False
    )


class NodeMaterialRow(Base):
    """ノードに付く値。

    行を持つのは「グラフの頂点になる点」か「種別が付く点」だけで、ただの形状頂点は
    持たない。

    `branch_count`は**そこに集まる道の本数**。グラフの位相としての次数（隣接する頂点の
    数）とは別物で、2本の枝が同じ次の交差点へ向かうと次数は1つに潰れる。交差点の密度を
    測るのに要るのは枝の本数のほうで、位相としての次数は探索がメモリ上で数える。
    """

    __tablename__ = "node_materials"

    osm_node_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    #: 分類器が付ける種別（信号・横断歩道・車止め・コンビニ等）。ただの形状頂点・
    #: 交差点はどの種別にも当たらずNULLになる。
    kind: Mapped[str | None] = mapped_column(String, nullable=True, info=ABSENT_OK)
    # 既定値はDB側に持つ。ORMの`default=`はPython経由の挿入にしか効かず、取込や導出が
    # 生SQLで書く行に適用されない。
    branch_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0")
    has_traffic_signals: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false")
    max_highway_rank: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0")

    source_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_runs.run_id"), nullable=False
    )
