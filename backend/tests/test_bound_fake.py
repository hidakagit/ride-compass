"""`tests/bound_fake.py`——差し替えた関数を、本物の署名へ当ててから呼ぶ。

この足場が呼び出しを通してしまうと、本物に合わない引数で呼ぶ実装を、頼る全部のテストが緑のまま通す。
"""

import inspect

import pytest

from tests.bound_fake import bound


def real(path: str, *, fresh: bool = False) -> bytes:
    raise AssertionError("本物は呼ばれない")


async def real_async(path: str) -> bytes:
    raise AssertionError("本物は呼ばれない")


@pytest.mark.parametrize(("args", "kwargs"), [
    (("a.png", "extra"), {}),
    ((), {"path": "a.png", "stale": True}),
    ((), {}),
])
def test_a_call_the_real_function_would_refuse_is_refused(args, kwargs):
    fake = bound(real, lambda *a, **k: b"fake")

    with pytest.raises(TypeError):
        fake(*args, **kwargs)


def test_a_call_the_real_function_accepts_reaches_the_fake():
    fake = bound(real, lambda path, fresh=False: (path, fresh))

    assert fake("a.png", fresh=True) == ("a.png", True)


async def test_an_async_fake_stays_async_and_is_checked_against_the_real_signature():
    async def fake(*args, **kwargs):
        return b"fake"

    checked = bound(real_async, fake)

    assert inspect.iscoroutinefunction(checked)
    assert await checked("a.png") == b"fake"
    with pytest.raises(TypeError):
        await checked("a.png", "extra")
