"""キャッシュ鍵の導出（app/infrastructure/cache_identity.py）。

見るのは「列やSQLを変えたら鍵が変わる」という性質そのもので、特定の署名値ではない
（値を固定すると、鍵を導出にした意味が無くなり「定数を更新せよ」というテストへ戻る）。
"""

import dataclasses

from app.domain.attributes import EdgeMaterialTable
from app.domain.evaluation import StaticEdgeScoreMatrix
from app.infrastructure import cache_identity as ci


def _with_extra_column(source: type) -> type:
    """`source`の列構成の末尾に1列だけ足したdataclass。"""
    fields = [(f.name, f.type) for f in dataclasses.fields(source)]
    return dataclasses.make_dataclass(
        source.__name__ + "Plus", [*fields, ("zzz_added_column", object)], frozen=True, slots=True)


class TestShapeDigest:
    def test_adding_a_column_changes_the_digest(self):
        # pickleは状態を列の位置で持つため、列が1つ増えた新コードが旧キャッシュを復元すると
        # 最後の列が設定されないまま実体化し、最初にその列へ触れた場所でAttributeErrorになる
        # （test_graph_material_cache.py: test_old_pickle_...が壊れ方そのものを固定している）。
        for table in (EdgeMaterialTable, StaticEdgeScoreMatrix):
            assert ci.shape_digest(table) != ci.shape_digest(_with_extra_column(table))

    def test_reordering_columns_changes_the_digest(self):
        reordered = dataclasses.make_dataclass(
            "Reordered",
            [(f.name, object) for f in reversed(dataclasses.fields(EdgeMaterialTable))],
            frozen=True, slots=True)

        assert ci.shape_digest(EdgeMaterialTable) != ci.shape_digest(reordered)

    def test_changing_the_sql_changes_the_digest(self):
        assert ci.shape_digest("SELECT a FROM t") != ci.shape_digest("SELECT a, b FROM t")

    def test_the_same_shape_gives_the_same_digest(self):
        # 鍵が安定しないと、内容が変わっていないのにデプロイのたびに冷パスを踏む。
        assert ci.shape_digest(EdgeMaterialTable) == ci.shape_digest(EdgeMaterialTable)

    def test_sources_are_separated(self):
        # 区切り無しで連結すると、("ab", "c")と("a", "bc")が同じ鍵になる。
        assert ci.shape_digest("ab", "c") != ci.shape_digest("a", "bc")


class TestCacheIdentity:
    def test_revision_is_visible_in_the_key(self):
        # 運用でディスクの世代ディレクトリを目で追えるようにする（旧世代の削除導線が
        # どの世代を残すかを人が判断できる必要がある）。
        assert ci.cache_identity("7", "x").startswith("7-")

    def test_bumping_the_revision_changes_the_key(self):
        assert ci.cache_identity("7", "x") != ci.cache_identity("8", "x")
