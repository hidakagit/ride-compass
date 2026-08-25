"""app/batch/precompute_way_attribute_counts.pyの純粋ロジック（チャンク分割）の検証
（改善計画T331、兄弟モジュールprecompute_edge_attribute_counts.pyのtest_chunked相当）。
DB接続自体は実DBが要るため対象外（他のbatchスクリプトのテストと同じ切り分け方針）。
"""

from app.batch.precompute_way_attribute_counts import _chunked


def test_chunked_splits_into_fixed_size_groups():
    assert _chunked([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunked_single_chunk_when_smaller_than_size():
    assert _chunked([1, 2], 10) == [[1, 2]]


def test_chunked_empty_list_returns_empty():
    assert _chunked([], 5) == []
