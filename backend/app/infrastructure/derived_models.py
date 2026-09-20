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


class RoadEdgeRow(Base):
    """道を交差点で切った区間1本。**向きでは分けない**。

    向きが持つ情報（方位・勾配の符号・通行の可否）はいずれも導ける——方位は+180°、
    勾配は符号反転、通行の可否は道の属性（一方通行）である。有向グラフは探索が
    メモリ上で組む実行時の構成物で、表が両向きを持つ必要はない。

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
    #: 進行方向。逆向きは+180°で導く。
    bearing_deg: Mapped[float] = mapped_column(REAL, nullable=False)

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
    average_grade: Mapped[float | None] = mapped_column(REAL, nullable=True)
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

    #: 上下線が分かれた道の片側か。
    divided: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    #: 指定路線のマッチ率（0〜1）。指定が無ければNULL。
    designation_emergency: Mapped[float | None] = mapped_column(Float, nullable=True)
    designation_logistics: Mapped[float | None] = mapped_column(Float, nullable=True)

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

    #: 分類器が付ける種別（信号・横断歩道・車止め・コンビニ等）。付かない点はNULL。
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    branch_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    has_traffic_signals: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_highway_rank: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    source_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("source_runs.run_id"), nullable=False
    )
