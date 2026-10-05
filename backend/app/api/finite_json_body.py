"""要求の本文のNaN・無限大を、どの経路でも経路の処理より前に422で断る。

Starletteは本文を標準の`json.loads`で読むため、JSONの外の`NaN`・`Infinity`・`-Infinity`も、桁あふれの
`1e999`もfloatとして通す。Pydanticのfloatの欄は既定で非有限の数を受け付けるので、制約の無い欄ではdomainへ
そのまま届き、制約や検査で断られた欄では検証エラーの応答の`input`に非有限の数が入ってJSONに書けず500になる。
アプリ全体の依存（`main.py`の`FastAPI(dependencies=...)`）として掛けるので、経路ごとに断り忘れる欄が無い。
"""

import json
import math
from collections.abc import Iterator
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError


def _non_finite_errors(value: Any, loc: tuple[str | int, ...]) -> Iterator[dict[str, Any]]:
    if isinstance(value, float) and not math.isfinite(value):
        # `input`は応答のJSONに書けるよう、JSONの綴り（`NaN`・`Infinity`）の文字列にする。
        yield {"type": "finite_number", "loc": loc, "msg": "Input should be a finite number", "input": json.dumps(value)}
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _non_finite_errors(item, (*loc, key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _non_finite_errors(item, (*loc, index))


async def reject_non_finite_json_body(request: Request) -> None:
    if not await request.body():
        return
    try:
        body = await request.json()
    except ValueError:
        # JSONとして読めない本文は、本文を受ける経路ならFastAPIがこの依存より前に422で断っており、
        # 受けない経路では誰も読まない。
        return
    errors = list(_non_finite_errors(body, ("body",)))
    if errors:
        raise RequestValidationError(errors)
