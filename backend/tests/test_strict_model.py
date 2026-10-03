"""`domain/strict_model.py`——未知のフィールドを捨てずに断るPydanticモデルの基底。

入口は基底を継承したモデルの検証（`model_validate`）とJSONスキーマの生成。基底はフィールドを持たないので、
本番と同じく継承したモデルで確かめる。

ここで見ないもの:
- `app/`のモデルが素の`BaseModel`を継承せず未知のフィールドの扱いを宣言していること → `structure/test_model_strictness.py`
"""

import pytest
from pydantic import ConfigDict, ValidationError

from app.domain.strict_model import StrictModel


class _FrozenRequest(StrictModel):
    """本番の軸の宣言と同じく、自分の設定（凍結）を足したモデル。"""

    model_config = ConfigDict(frozen=True)

    name: str
    speed_kmh: float = 20.0


def test_an_unknown_field_is_refused_even_when_the_subclass_adds_its_own_config():
    """綴りを誤ったフィールドが黙って捨てられると、指定したのに効かないという形で利用者に出る。"""
    with pytest.raises(ValidationError, match="speed_kph"):
        _FrozenRequest.model_validate({"name": "a", "speed_kph": 25.0})


def test_a_field_with_a_default_is_required_in_the_response_schema_but_not_in_the_request_schema():
    """応答には既定値のフィールドも必ず載る。スキーマがそう言わないと、生成した画面の型が欠けうる値として扱う。"""
    serialization = _FrozenRequest.model_json_schema(mode="serialization")
    validation = _FrozenRequest.model_json_schema(mode="validation")

    assert set(serialization["required"]) == {"name", "speed_kmh"}
    assert validation["required"] == ["name"]
