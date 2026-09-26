"""キャッシュ鍵の導出（app/infrastructure/cache_identity.py）。

見るのは「列やSQLを変えたら鍵が変わる」という性質そのもので、特定の署名値ではない
（値を固定すると、鍵を導出にした意味が無くなり「定数を更新せよ」というテストへ戻る）。
"""

import dataclasses

from app.domain.road_network import RoadNetwork
from app.infrastructure import cache_identity as ci


def _with_extra_column(source: type) -> type:
    """`source`の列構成の末尾に1列だけ足したdataclass。"""
    fields = [(f.name, f.type) for f in dataclasses.fields(source)]
    return dataclasses.make_dataclass(
        source.__name__ + "Plus", [*fields, ("zzz_added_column", object)], frozen=True, slots=True)


class TestShapeDigest:
    def test_adding_a_column_changes_the_digest(self):
        # 道路網の置き場は列ごとのファイルを列名で読むため、列が1つ増えたコードが古い置き場を
        # 選ぶと、その列のファイルが無いまま読みに行く。
        assert ci.shape_digest(RoadNetwork) != ci.shape_digest(_with_extra_column(RoadNetwork))

    def test_reordering_columns_changes_the_digest(self):
        reordered = dataclasses.make_dataclass(
            "Reordered",
            [(f.name, object) for f in reversed(dataclasses.fields(RoadNetwork))],
            frozen=True, slots=True)

        assert ci.shape_digest(RoadNetwork) != ci.shape_digest(reordered)

    def test_changing_the_sql_changes_the_digest(self):
        assert ci.shape_digest("SELECT a FROM t") != ci.shape_digest("SELECT a, b FROM t")

    def test_the_same_shape_gives_the_same_digest(self):
        # 鍵が安定しないと、内容が変わっていないのにデプロイのたびに冷パスを踏む。
        assert ci.shape_digest(RoadNetwork) == ci.shape_digest(RoadNetwork)

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


class TestBoundValuesAreSigned:
    """SQLへあらかじめ束ねた値（分類タグ集合等）が署名へ入ること。

    `str(TextClause)`にはプレースホルダ名しか現れないため、ここが抜けるとタグを足しても
    鍵が動かない。焼き込み値だけが変わって配信は古い値のまま、という気づきにくい形になる。
    """

    def _sql(self, tags: list[str]):
        from sqlalchemy import bindparam, text
        from sqlalchemy.dialects.postgresql import ARRAY
        from sqlalchemy.types import Text

        return text("SELECT :tags AS t").bindparams(
            bindparam("tags", value=tags, type_=ARRAY(Text()))
        )

    def test_changing_a_bound_value_changes_the_digest(self):
        assert ci.shape_digest(self._sql(["asphalt"])) != ci.shape_digest(self._sql(["asphalt", "sett"]))

    def test_same_bound_values_keep_the_digest(self):
        assert ci.shape_digest(self._sql(["asphalt"])) == ci.shape_digest(self._sql(["asphalt"]))

    def test_runtime_parameters_without_a_value_are_not_signed(self):
        # タイル座標のように実行時へ委ねるパラメータは値を持たない。署名へ入れると
        # 「値が無い」ことを毎回同じに書き出すだけで、意味のある差にならない。
        from sqlalchemy import bindparam, text

        sql = text("SELECT :z AS z").bindparams(bindparam("z"))
        assert ci.bound_values(sql) == []
