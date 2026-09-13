"""DBの世代とディスクの記録を突き合わせる共通機構（改善計画T851）。

軸定義と派生データが別々に持っていた同型の判断を1箇所へ畳んだもの。ここが唯一の実装のため、
判断の分岐（一致・不一致・読めない）をここで直接固定する。
"""

from app.infrastructure import cache_generation, tile_persistent_cache

NAMESPACE = "test-cache-generation"
VERSION = "v1"


def setup_function():
    tile_persistent_cache.clear_namespace(NAMESPACE)


def teardown_function():
    tile_persistent_cache.clear_namespace(NAMESPACE)


def _sync(revision, cleared):
    """`clear`は実物と同じくnamespaceごと消す（記録もそこに在るため、消えた後に
    書き直されるかどうかが判定の分かれ目になる）。"""

    def clear():
        cleared.append(revision)
        tile_persistent_cache.clear_namespace(NAMESPACE)

    return cache_generation.sync_with_revision(NAMESPACE, VERSION, revision, clear)


def test_first_call_has_no_record_so_it_clears_and_records():
    cleared = []

    assert _sync(1, cleared) is True
    assert cleared == [1]
    assert cache_generation.read_persisted_revision(NAMESPACE, VERSION) == 1


def test_same_revision_keeps_the_disk_cache():
    cleared = []
    _sync(1, cleared)

    assert _sync(1, cleared) is False
    assert cleared == [1]  # 2回目は呼ばれない


def test_changed_revision_clears_and_records_the_new_one():
    cleared = []
    _sync(1, cleared)

    assert _sync(2, cleared) is True
    assert cleared == [1, 2]
    assert cache_generation.read_persisted_revision(NAMESPACE, VERSION) == 2


def test_unreadable_revision_always_clears_and_records_nothing():
    # 記録し直さないため、次回も同じ安全側の判定になる（読めない状態が続く間ずっと捨てる）。
    cleared = []
    _sync(1, cleared)

    assert _sync(None, cleared) is True
    assert cache_generation.read_persisted_revision(NAMESPACE, VERSION) is None
    assert _sync(None, cleared) is True
