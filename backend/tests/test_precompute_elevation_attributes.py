"""precompute系バッチが共通ドライバをそのまま使っていることの確認。

対象IDのチャンク分割・進捗ログ・dry-run/0件の扱いは`app/batch/_common.py`の
`run_chunked_precompute`（実装のテストは`tests/test_batch_common.py`）が持つ。ここでは
各バッチが自前のドライバを書き直していないこと（同じ骨格が写経で増え、片方だけ直されて
体裁や0件時の扱いがズレる事故の再発防止）だけを確認する。DB接続・外部HTTP呼び出し自体は
実DB/実APIが要るため対象外（他のbatchスクリプトのテストと同じ切り分け方針）。
"""

import pytest

from app.batch import (
    precompute_edge_attribute_counts,
    precompute_elevation_attributes,
    precompute_way_attribute_counts,
    precompute_way_curvature,
)
from app.batch._common import run_chunked_precompute as common_run_chunked_precompute


@pytest.mark.parametrize(
    "module",
    [
        precompute_edge_attribute_counts,
        precompute_elevation_attributes,
        precompute_way_attribute_counts,
        precompute_way_curvature,
    ],
)
def test_uses_the_shared_chunked_precompute_driver(module):
    assert module.run_chunked_precompute is common_run_chunked_precompute
