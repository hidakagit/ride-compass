"""`domain/strict_model.py`——未知のフィールドを黙って捨てないモデルの基底。

この基底をapp配下の全モデルが使っているかは`tests/structure/test_model_strictness.py`が持つ。
ここで見るのは基底そのものの挙動。
"""

import pytest
from pydantic import ConfigDict, ValidationError

from app.domain.strict_model import StrictModel


class _Known(StrictModel):
    known: int


def test_unknown_field_is_rejected_instead_of_dropped():
    with pytest.raises(ValidationError):
        _Known(known=1, unknown=2)


def test_known_fields_still_build_the_model():
    assert _Known(known=1).known == 1


def test_subclasses_keep_the_rejection_while_adding_their_own_config():
    """上書きだと思って別の設定を書くと、その派生だけが黙って値を捨てる。"""

    class _Frozen(StrictModel):
        model_config = ConfigDict(frozen=True)

        known: int

    assert _Frozen(known=1).model_config["frozen"] is True
    with pytest.raises(ValidationError):
        _Frozen(known=1, unknown=2)
