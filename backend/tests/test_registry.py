"""`domain/registry.py`——地図表示の宣言の型が、読む側に届く形へ正規化すること。"""

from app.domain.registry import TileInputSpec


class TestTileInputSpec:
    def test_a_category_table_given_as_none_stays_absent(self):
        """空辞書へ倒すと、「分類ではない材料」と「分類だが値が無い材料」を読む側が
        区別できない。
        """
        assert TileInputSpec(property="p", categories=None).categories is None

    def test_the_category_table_is_stored_in_a_fixed_order(self):
        """順序が違うだけで生成物の差分が出ると、意味の無い再デプロイが要る。"""
        spec = TileInputSpec(property="p", categories={"c": 3.0, "a": 1.0, "b": 2.0})

        assert list(spec.categories) == ["a", "b", "c"]
