"""`StrictModel`（extra="forbid"）が実際にモデルを守っていること。

`tests/structure/test_model_strictness.py`が「素の`BaseModel`を継承していないこと」を
静的に見るのに対し、こちらは**実際に弾けること**を見る。静的な検査だけだと、基底の
`model_config`がいつか外れても気づけない。
"""

import pytest
from pydantic import ValidationError

from app.domain.region import BoundingBox
from app.domain.route_preference import RoutePreference
from app.domain.strict_model import StrictModel


def test_unknown_fields_raise_instead_of_being_dropped():
    """既定（ignore）のままだと、値が捨てられてアサーションだけが残る。"""

    class Sample(StrictModel):
        known: int

    assert Sample(known=1).known == 1
    with pytest.raises(ValidationError):
        Sample(known=1, unknown=2)


def test_subclasses_keep_their_own_config_and_still_forbid_extras():
    """派生側が`frozen`等を指定しても`extra`は引き継がれる（Pydanticのconfigマージ）。

    ここが壊れると、`frozen=True`を持つ軸定義の一群だけが黙って`ignore`へ戻る。
    """
    from app.domain.axis_definitions import MaterialTerm

    assert MaterialTerm.model_config["extra"] == "forbid"
    assert MaterialTerm.model_config["frozen"] is True
    with pytest.raises(ValidationError):
        MaterialTerm(material="gradient_percent", weigth=1.0)  # weight のtypo


@pytest.mark.parametrize(
    ("model", "kwargs", "typo"),
    [
        (BoundingBox, {"min_latitude": 35.0, "min_longitude": 139.0,
          "max_latitude": 36.0, "max_longitude": 140.0}, "min_lat"),
        (RoutePreference, {}, "weigths"),
    ],
)
def test_representative_models_reject_mistyped_fields(model, kwargs, typo):
    """typoしたフィールド名を渡すと落ちる（素通りすると、指定したのに効かない形で
    利用者に出る）。"""
    model(**kwargs)
    with pytest.raises(ValidationError):
        model(**kwargs, **{typo: 1})
