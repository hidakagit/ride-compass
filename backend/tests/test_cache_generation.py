"""`infrastructure/cache_generation.py`——DBが持つ世代と、ディスクを書いた時点の記録の突き合わせ。

ここで見ないもの:
- 記録を置くディスクそのもの（読み書き・掃除）→ `test_tile_persistent_cache.py`
- 世代をDBのどこから読むか・誰がこの確認を呼ぶか → `test_derived_data_revision_service.py`
- 食い違ったとき何を捨てるか → `test_graph_material_cache.py`・`test_tile_score_matrix_cache.py`
"""

from app.infrastructure import cache_generation, tile_persistent_cache

NAMESPACE = "materials"
VERSION = "v1"


def _check(revision: int | None, *, namespace: str = NAMESPACE, version: str = VERSION):
    """捨てたかどうか（戻り値）と、実際に捨てた回数の対。契約はこの2つが一致すること。"""
    cleared: list[int] = []
    reported = cache_generation.sync_with_revision(namespace, version, revision, lambda: cleared.append(1))
    return reported, len(cleared)


class TestTheFirstLookAtADiskCache:
    def test_a_cache_with_no_record_is_thrown_away(self):
        """前のデプロイ・前のバッチが書いたものかもしれない。"""
        assert _check(5) == (True, 1)


class TestWhenNothingHasChanged:
    def test_the_same_generation_keeps_the_cache(self):
        """確認はキャッシュを読む経路の入口にある。毎回捨てると一度も効かない。"""
        _check(5)

        assert _check(5) == (False, 0)


class TestWhenTheGenerationMoves:
    def test_a_newer_generation_throws_the_cache_away(self):
        """バッチが作り直した値を、古い派生データのまま配り続ける。"""
        _check(5)

        assert _check(6) == (True, 1)


class TestWhenTheGenerationCannotBeRead:
    def test_it_throws_the_cache_away_once(self):
        assert _check(None) == (True, 1)

    def test_it_does_not_keep_throwing_it_away(self):
        """記録しないと、確認のたびに全消去が走る——確認の発火点が増えるほど消える。"""
        _check(None)

        assert _check(None) == (False, 0)

    def test_a_generation_that_became_readable_is_a_change(self):
        """読めなかったことを世代の値そのもので表すと、この切り替わりを取りこぼす。"""
        _check(None)

        assert _check(5) == (True, 1)


class TestTheRecordOutlivesTheClearing:
    def test_a_clear_that_wipes_the_whole_place_does_not_take_the_record_with_it(self):
        """記録はキャッシュと同じ置き場にある。捨ててから記録し直さないと、確認のたびに
        捨て直すことになり、ディスクキャッシュが一度も効かない。
        """

        def clear() -> None:
            tile_persistent_cache.clear_namespace(NAMESPACE)

        cache_generation.sync_with_revision(NAMESPACE, VERSION, 5, clear)

        assert cache_generation.sync_with_revision(NAMESPACE, VERSION, 5, clear) is False


class TestEachCacheIsTrackedOnItsOwn:
    def test_another_namespace_has_its_own_record(self):
        _check(5, namespace="materials")

        assert _check(5, namespace="scores") == (True, 1)

    def test_another_version_has_its_own_record(self):
        """形が変われば置き場ごと別になる。前の形の記録を引き継ぐと、新しい形の
        ディスクを一度も確かめないまま使い始める。
        """
        _check(5, version="v1")

        assert _check(5, version="v2") == (True, 1)
