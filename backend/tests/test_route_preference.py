"""`domain/route_preference.py`——ルート生成の重み指定（`RoutePreference`）と、重みの値の検査（`check_axis_weights`）。

軸の集合は本番ではDBが正本なので、見たい性質（公開か・既定の重み）だけを持つ架空の軸へ差し替える。

ここで見ないもの:
- 要求で上書きするなら公開軸を全部書く、という要求の形 → `test_routes_generate.py`
- 重みを使ったコストの合成 → `test_leg_costs.py`
"""

import math

import pytest
from pydantic import ValidationError

from app.domain.route_preference import RoutePreference, check_axis_weights
from tests.axis_system_fixture import axis_definition, replaced_axis_definitions

pytestmark = pytest.mark.usefixtures("fictional_axes")


@pytest.fixture
def fictional_axes():
    """公開軸2本と、内部軸1本。並びが合成の加算順になる。"""
    with replaced_axis_definitions({
        "axis_a": axis_definition("axis_a", is_published=True, default_weight=0.4),
        "axis_internal": axis_definition("axis_internal", material="material_b", default_weight=0.9),
        "axis_b": axis_definition("axis_b", material="material_c", is_published=True, default_weight=0.2),
    }):
        yield


def test_weights_left_out_are_filled_with_defaults_in_the_order_of_the_axes():
    weights = RoutePreference(weights={"axis_b": 0.7}).weights

    assert weights == {"axis_a": 0.4, "axis_b": 0.7}
    assert list(weights) == ["axis_a", "axis_b"]


@pytest.mark.parametrize(
    "weights",
    [
        # 内部軸は公開軸から参照されるだけで、重みを付ける対象ではない。
        {"axis_internal": 0.1},
        # 負の重みは合成の分母と分子の符号を食い違わせ、良い道ほど点が高くなる。
        {"axis_a": -0.1},
        # NaN・無限大は合成difficultyと寄与を黙って欠損にする。NaNは負かどうかの比べをすり抜ける。
        {"axis_a": math.nan},
        {"axis_a": math.inf},
    ],
)
def test_weights_for_unpublished_axes_or_below_zero_or_not_finite_are_refused(weights):
    with pytest.raises(ValueError):
        check_axis_weights(weights)


def test_the_request_refuses_the_weights_the_check_refuses():
    with pytest.raises(ValidationError):
        RoutePreference(weights={"axis_a": -0.1})


def test_a_zero_weight_is_kept_rather_than_replaced_by_the_default():
    """重み0は「この軸を気にしない」という指定で、書かれなかった軸と違い既定で補わない。"""
    assert RoutePreference(weights={"axis_a": 0.0}).weights == {"axis_a": 0.0, "axis_b": 0.2}

