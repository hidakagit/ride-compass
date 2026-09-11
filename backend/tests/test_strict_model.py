"""`StrictModel`（extra="forbid"）が実際にモデルを守っていること。

`scripts/review_checks.py`の`find_bare_basemodel_violations`が「素のBaseModelを
継承していないこと」を静的に見るのに対し、こちらは**実際に弾けること**を見る。
静的チェックだけだと、基底の`model_config`がいつか外れても検知できない。
"""

import pytest
from pydantic import ValidationError

from app.domain.attributes import EdgeAttributeCounts
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
        (EdgeAttributeCounts, {"accident_count": 0.0, "intersection_count": 0}, "stop_count"),
        (BoundingBox, {"min_latitude": 35.0, "min_longitude": 139.0,
          "max_latitude": 36.0, "max_longitude": 140.0}, "min_lat"),
        (RoutePreference, {}, "stop_weight"),
    ],
)
def test_representative_models_reject_removed_or_mistyped_fields(model, kwargs, typo):
    """撤去済み・typoしたフィールド名を渡すと落ちる。

    `stop_count`は実際に撤去した列（T719）で、これが素通りしたために古い引数を渡す
    テストが通り続けた。`stop_weight`も同じく過去に存在した名前。
    """
    model(**kwargs)
    with pytest.raises(ValidationError):
        model(**kwargs, **{typo: 1})
