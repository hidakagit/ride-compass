"""`tests/fake_external_log.py`——`debug_log.log_external_call`の代役。

同じ呼び方を本物と代役の両方へ流し、記録に残る`fields`（呼び出し元が渡したもの・書き足したもの・
抜け方で足されるもの）が揃うことを見る。本物では、抜けるときに集計へ渡す`fields`は、ブロックが受け取った
dictそのものである。

ここで見ないもの: 本物が`fields`から集計・警告を作ること → `test_debug_log.py`
"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.infrastructure.debug_log import log_external_call
from tests.fake_external_log import record_external_calls


@pytest.fixture(params=["本物", "代役"])
def logger(request, monkeypatch, empty_debug_counters):
    """`log_external_call`と同じ口と、抜けたあとに記録された`fields`を読む関数。"""
    if request.param == "代役":
        module = SimpleNamespace(log_external_call=log_external_call)
        recorded = record_external_calls(monkeypatch, module)
        return module.log_external_call, lambda: recorded[-1].fields
    opened: list[dict] = []

    @contextmanager
    def call(category, **fields):
        with log_external_call(category, **fields) as written:
            opened.append(written)
            yield written

    return call, lambda: opened[-1]


def test_the_given_fields_and_what_the_caller_wrote_are_recorded(logger):
    call, recorded_fields = logger

    with call("cat", tile="14/1/2") as fields:
        fields["cache"] = "hit"

    assert recorded_fields() == {"tile": "14/1/2", "cache": "hit"}


def test_an_exception_that_escapes_the_block_is_recorded_by_its_type(logger):
    call, recorded_fields = logger

    with pytest.raises(ValueError), call("cat", tile="14/1/2"):
        raise ValueError("boom")

    assert recorded_fields() == {"tile": "14/1/2", "error_type": "ValueError"}
