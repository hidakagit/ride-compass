"""`domain/route_preference.py`——ルート生成の重み指定（`RoutePreference`）と、重みの値の検査（`check_axis_weights`）。

軸の集合は本番ではDBが正本なので、見たい性質（公開か・既定の重み・時間帯）だけを持つ架空の軸へ差し替える。

ここで見ないもの:
- 要求で上書きするなら公開軸を全部書く、という要求の形 → `test_routes_generate.py`
- 重みを使ったコストの合成 → `test_leg_costs.py`
"""

import pytest
from pydantic import ValidationError

from app.domain.route_preference import RoutePreference, check_axis_weights
from tests.axis_system_fixture import axis_definition, replaced_axis_definitions

pytestmark = pytest.mark.usefixtures("fictional_axes")


@pytest.fixture
def fictional_axes():
    """公開軸2本（`axis_b`は夜だけ効く）と、内部軸1本。並びが合成の加算順になる。"""
    with replaced_axis_definitions({
        "axis_a": axis_definition("axis_a", is_published=True, default_weight=0.4),
        "axis_internal": axis_definition("axis_internal", material="material_b", default_weight=0.9),
        "axis_b": axis_definition("axis_b", material="material_c", is_published=True, default_weight=0.2,
                                  time_scope="night_only"),
    }):
        yield


def test_without_weights_every_published_axis_gets_its_default_weight():
    assert RoutePreference().weights == {"axis_a": 0.4, "axis_b": 0.2}


def test_weights_left_out_are_filled_with_defaults_in_the_order_of_the_axes():
    weights = RoutePreference(weights={"axis_b": 0.7}).weights

    assert weights == {"axis_a": 0.4, "axis_b": 0.7}
    assert list(weights) == ["axis_a", "axis_b"]


@pytest.mark.parametrize(
    "weights",
    [
        {"no_such_axis": 0.1},
        # 内部軸は公開軸から参照されるだけで、重みを付ける対象ではない。
        {"axis_internal": 0.1},
        # 負の重みは合成の分母と分子の符号を食い違わせ、良い道ほど点が高くなる。
        {"axis_a": -0.1},
    ],
)
def test_weights_for_unknown_axes_or_below_zero_are_refused(weights):
    with pytest.raises(ValidationError):
        RoutePreference(weights=weights)
    with pytest.raises(ValueError):
        check_axis_weights(weights)


def test_a_zero_weight_is_kept_rather_than_replaced_by_the_default():
    """重み0は「この軸を気にしない」という指定で、書かれなかった軸と違い既定で補わない。"""
    assert RoutePreference(weights={"axis_a": 0.0}).weights == {"axis_a": 0.0, "axis_b": 0.2}


def test_a_weight_above_the_screen_limit_is_accepted():
    """画面で1軸へ寄せられる上限は、保存された配分や既定がそれを超えていても生成を断らない。"""
    assert RoutePreference(weights={"axis_a": 1.0}).weights["axis_a"] == 1.0


def test_an_axis_limited_to_a_time_of_day_weighs_nothing_outside_it():
    preference = RoutePreference(weights={"axis_a": 0.5, "axis_b": 0.3})

    assert preference.with_time_scope(frozenset()).weights == {"axis_a": 0.5, "axis_b": 0.0}
    assert preference.with_time_scope(frozenset({"night_only"})).weights == {"axis_a": 0.5, "axis_b": 0.3}


def test_limiting_to_a_time_of_day_leaves_the_shared_preference_as_it_was():
    """リクエストの間で共有する重みを書き換えない。"""
    preference = RoutePreference(weights={"axis_a": 0.5, "axis_b": 0.3})

    preference.with_time_scope(frozenset())

    assert preference.weights == {"axis_a": 0.5, "axis_b": 0.3}
