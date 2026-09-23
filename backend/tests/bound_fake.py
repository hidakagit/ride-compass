"""差し替えた関数を、本物の署名へ当ててから呼ぶ。

`lambda *a: 値`・`def fake(*args, **kwargs)`の形のフェイクは、呼び出し側が本物に合わない
引数（数・名前）を渡しても値を返して通す。本物の署名へ先に束縛し、合わなければ本物と同じ
`TypeError`で落とす。
"""

import functools
import inspect


def bound(real, fake):
    """`fake`を、`real`の署名で引数を確かめてから呼ぶ関数にして返す。

    numbaでコンパイルした関数は`py_func`の署名を使う。`fake`が非同期関数なら、返す関数も
    非同期にする（呼び出し側が`iscoroutinefunction`で扱いを分けるため）。名前・`__module__`は
    `fake`のものを引き継ぐ（差し替えた先を`__module__`で見分けるテストがある）。
    """
    signature = inspect.signature(getattr(real, "py_func", real))

    if inspect.iscoroutinefunction(fake):

        @functools.wraps(fake)
        async def call_async(*args, **kwargs):
            signature.bind(*args, **kwargs)
            return await fake(*args, **kwargs)

        return call_async

    @functools.wraps(fake)
    def call(*args, **kwargs):
        signature.bind(*args, **kwargs)
        return fake(*args, **kwargs)

    return call
