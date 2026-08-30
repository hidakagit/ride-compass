"""app/batch/precompute_elevation_attributes.pyの純粋ロジック検証（改善計画T331残り5項目）。

チャンク分割自体の実装・テストは改善計画T467でapp/batch/_common.py: chunked（tests/
test_batch_common.py）へ統合済み。ここでは、このバッチが自前実装を持たず共通実装を
そのままimportして使っていること（同期ペアの片側だけ更新して実体がズレる事故の再発防止）
のみを確認する。DB接続・外部HTTP呼び出し自体は実DB/実APIが要るため対象外
（他のbatchスクリプトのテストと同じ切り分け方針）。
"""

from app.batch._common import chunked as common_chunked
from app.batch.precompute_elevation_attributes import chunked


def test_chunked_is_the_shared_common_implementation():
    assert chunked is common_chunked
