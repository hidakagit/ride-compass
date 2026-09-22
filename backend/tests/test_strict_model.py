"""`domain/strict_model.py`——未知のフィールドを黙って捨てないモデルの基底。

Pydanticの既定（`extra="ignore"`）では、モデルが知らないフィールドは例外にならず捨てられる。
値は消えてアサーションだけが残るため、フィールドを消した・改名したときの取り残しが
どこにも現れない。
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
    """Pydantic v2は`model_config`を親子でマージする。派生が別の設定だけを書いても
    `extra="forbid"`は残る——上書きだと思って書くと、その派生だけが黙って値を捨てる。
    """

    class _Frozen(StrictModel):
        model_config = ConfigDict(frozen=True)

        known: int

    assert _Frozen(known=1).model_config["frozen"] is True
    with pytest.raises(ValidationError):
        _Frozen(known=1, unknown=2)
