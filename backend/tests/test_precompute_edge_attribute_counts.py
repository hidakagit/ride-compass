"""app/batch/precompute_edge_attribute_counts.pyの純粋ロジック（チャンク分割）の検証
（改善計画T144）。DB接続自体は実DBが要るため対象外（他のbatchスクリプトのテストと同じ
切り分け方針）。
"""

from app.batch.precompute_edge_attribute_counts import _chunked


def test_chunked_splits_into_fixed_size_groups():
    assert _chunked(["a", "b", "c", "d", "e"], 2) == [["a", "b"], ["c", "d"], ["e"]]


def test_chunked_single_chunk_when_smaller_than_size():
    assert _chunked(["a", "b"], 10) == [["a", "b"]]


def test_chunked_empty_list_returns_empty():
    assert _chunked([], 5) == []
