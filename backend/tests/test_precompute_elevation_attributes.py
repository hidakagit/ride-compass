"""app/batch/precompute_elevation_attributes.pyの純粋ロジック検証（改善計画T331残り5項目）。

対象IDの取得（サーバーサイドカーソルによるチャンク分割）の実装・テストは
app/batch/_common.py: stream_id_chunks（tests/test_batch_common.py）にある。ここでは、
このバッチが自前実装を持たず共通実装をそのままimportして使っていること（同期ペアの片側だけ
更新して実体がズレる事故の再発防止）のみを確認する。DB接続・外部HTTP呼び出し自体は
実DB/実APIが要るため対象外（他のbatchスクリプトのテストと同じ切り分け方針）。
"""

from app.batch._common import stream_id_chunks as common_stream_id_chunks
from app.batch.precompute_elevation_attributes import stream_id_chunks


def test_stream_id_chunks_is_the_shared_common_implementation():
    assert stream_id_chunks is common_stream_id_chunks
