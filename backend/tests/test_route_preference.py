"""`domain/route_preference.py`——重みの値の不変条件。書き手（ルート生成の要求・研究のスクリプト・テスト）を
問わず、`RoutePreference`を組み立てた時点で成り立つ。

ここで見ないもの: 要求が公開軸の重みを全部書いているか（要求の形） → `test_routes_generate.py`
"""

import pytest
from pydantic import ValidationError

from app.domain.route_preference import RoutePreference
from tests.axis_system_fixture import axis_definition, replaced_axis_definitions


@pytest.fixture
def axes():
    """公開軸`pub`と、公開していない軸`internal`。"""
    with replaced_axis_definitions(
        {
            "pub": axis_definition("pub", is_published=True, default_weight=1.0),
            "internal": axis_definition("internal", material="material_b"),
        }
    ):
        yield


@pytest.mark.parametrize(
    ("weights", "reason"),
    [({"pub": -0.5}, ">= 0"), ({"internal": 1.0}, "unknown axis_id")],
    ids=["負の重み", "公開していない軸"],
)
def test_weights_the_composition_cannot_use_are_refused_without_the_api(axes, weights, reason):
    with pytest.raises(ValidationError, match=reason):
        RoutePreference(weights=weights)


def test_a_zero_weight_is_a_weight(axes):
    assert RoutePreference(weights={"pub": 0.0}).weights == {"pub": 0.0}
