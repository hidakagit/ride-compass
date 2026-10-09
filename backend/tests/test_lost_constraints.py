"""2つの版のORM宣言から消えた制約を出す（scripts/lost_constraints.py）。

版の取り出し（git archive）とimportは子プロセスの境界なので通さず、宣言の突き合わせだけを確かめる。
実行口（`main`）は、確かめる担当が Pull Request ごとに本物の2つの版へ流す（docs/conventions/pull-requests.md「確かめる」の1）。
"""

from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Index, MetaData, Table, UniqueConstraint, text

from scripts.lost_constraints import constraint_items, lost


def _parent(metadata: MetaData) -> Table:
    return Table("ways", metadata, Column("osm_way_id", BigInteger, primary_key=True))


def test_a_rewrite_that_drops_a_foreign_key_and_not_null_reports_both() -> None:
    before = MetaData()
    _parent(before)
    Table("edges", before,
          Column("edge_id", BigInteger, primary_key=True),
          Column("osm_way_id", BigInteger, ForeignKey("ways.osm_way_id", ondelete="CASCADE"), nullable=False))
    after = MetaData()
    _parent(after)
    Table("edges", after,
          Column("edge_id", BigInteger, primary_key=True),
          Column("osm_way_id", BigInteger))

    assert lost(constraint_items([before]), constraint_items([after])) == [
        ("NOT NULL", "edges", "osm_way_id"),
        ("外部キー", "edges", "(osm_way_id) -> ways.osm_way_id ON DELETE CASCADE"),
    ]


def test_a_constraint_that_only_changed_its_name_is_not_lost() -> None:
    before = MetaData()
    Table("edges", before, Column("edge_id", BigInteger, primary_key=True),
          Column("distance_m", BigInteger),
          CheckConstraint("distance_m > 0", name="old_name"),
          Index("ix_old", "distance_m", unique=True))
    after = MetaData()
    Table("edges", after, Column("edge_id", BigInteger, primary_key=True),
          Column("distance_m", BigInteger),
          CheckConstraint("distance_m  >  0", name="new_name"),
          Index("ix_new", "distance_m", unique=True))

    assert lost(constraint_items([before]), constraint_items([after])) == []


def _edges(metadata: MetaData, *unique) -> Table:
    return Table("edges", metadata, Column("edge_id", BigInteger, primary_key=True),
                 Column("from_node", BigInteger), Column("to_node", BigInteger), *unique)


def test_a_unique_constraint_rewritten_as_a_unique_index_on_the_same_columns_is_not_lost() -> None:
    before, after = MetaData(), MetaData()
    _edges(before, UniqueConstraint("from_node", "to_node"))
    _edges(after, Index("ix_edges_nodes", "from_node", "to_node", unique=True))

    assert constraint_items([before]) == constraint_items([after])


def test_a_unique_constraint_narrowed_to_a_partial_unique_index_is_lost() -> None:
    before, after = MetaData(), MetaData()
    _edges(before, UniqueConstraint("from_node", "to_node"))
    _edges(after, Index("ix_edges_nodes", "from_node", "to_node", unique=True, postgresql_where=text("from_node > 0")))

    assert lost(constraint_items([before]), constraint_items([after])) == [("一意", "edges", "(from_node,to_node)")]


def test_a_dropped_table_is_reported_as_one_line() -> None:
    before = MetaData()
    _parent(before)
    Table("edges", before, Column("edge_id", BigInteger, primary_key=True),
          Column("osm_way_id", BigInteger, ForeignKey("ways.osm_way_id"), nullable=False))
    after = MetaData()
    _parent(after)

    assert lost(constraint_items([before]), constraint_items([after])) == [("表", "edges", "")]
