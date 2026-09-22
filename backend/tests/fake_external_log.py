"""`debug_log.log_external_call`を差し替え、呼び出し元が書いた`fields`を集める。

外部を叩くクライアントは、キャッシュの当たり外れ・成否・エラーの種別を`fields`へ書く。
これは`/api/debug/stats`の集計とWARNINGの出し分けに使われるため、**`fields`の中身自体が
クライアントの外向きの成果物**であり、テストの観測点になる。

差し替え先はモジュールごとに違う（各クライアントが`from ... import log_external_call`で
自分の名前空間へ取り込んでいる）ため、対象モジュールを引数で受け取る。
"""

import contextlib
from dataclasses import dataclass


@dataclass
class ExternalCall:
    """1回の外部呼び出し。`category`は分類名、`fields`は呼び出し元が書き込んだ内容。"""

    category: str
    fields: dict


def record_external_calls(monkeypatch, module) -> list[ExternalCall]:
    """`module.log_external_call`を差し替え、記録先のリストを返す。"""
    recorded: list[ExternalCall] = []

    @contextlib.contextmanager
    def fake_log_external_call(category, **log_fields):
        call = ExternalCall(category, dict(log_fields))
        recorded.append(call)
        yield call.fields

    monkeypatch.setattr(module, "log_external_call", fake_log_external_call)
    return recorded
