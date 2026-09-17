"""較正値の宣言（`domain/tuning.py`）のテスト。

宣言を1つにした狙いは「エンジンが読む値・管理画面が並べる項目・変更が効くために何をやり直す
必要があるか」を1箇所から導くこと。**宣言を変えたときに消費者へ届く**ことが守られていないと、
管理画面から変えても何も起きない状態になる。
"""

import numpy as np
import pytest

from app.domain import tuning
from app.domain.cycling_speed import RiderProfile, climb_power_ratio, crr_for_surface
from app.domain.routing import current_turn_cost
from app.domain.traffic import POI_COUNT_KINDS, stop_seconds
from app.domain.tuning import (
    TUNING_PARAMETERS,
    TUNING_PARAMETERS_BY_ID,
    stop_seconds_parameter_id,
    tuning_value,
)
from app.infrastructure.road_graph_repository import signal_radius_params


@pytest.fixture
def override(monkeypatch):
    """較正値を1つ差し替える（プロセス内の辞書を戻すのはmonkeypatchに任せる）。"""

    def apply(param_id: str, value: float) -> None:
        assert param_id in TUNING_PARAMETERS_BY_ID, param_id
        monkeypatch.setitem(tuning.TUNING_VALUES, param_id, value)

    return apply


class TestDeclaration:
    def test_every_declared_value_starts_at_its_default(self):
        for parameter in TUNING_PARAMETERS:
            assert tuning_value(parameter.id) == parameter.default

    def test_default_sits_inside_the_declared_range(self):
        for parameter in TUNING_PARAMETERS:
            assert parameter.minimum <= parameter.default <= parameter.maximum, parameter.id

    def test_unknown_id_is_an_error_rather_than_a_silent_zero(self):
        with pytest.raises(KeyError):
            tuning_value("turn.no_such_value")

    def test_every_counted_stop_kind_has_a_declared_wait(self):
        # 片方だけ増えると、その種別が所要時間へ入らないまま静かに無視される。
        declared = {p for p in TUNING_PARAMETERS_BY_ID if p.startswith("stop.")}

        assert declared == {stop_seconds_parameter_id(kind) for kind in POI_COUNT_KINDS}


class TestReachesTheConsumers:
    """宣言を変えると、実際に読んでいる側まで届くこと。

    届かない値が混ざっていると、管理画面から変えても何も起きない——しかも画面の見た目は
    変えられたのと同じになる。
    """

    def test_turn_cost(self, override):
        override("turn.right_seconds", 99.0)

        assert current_turn_cost().right_seconds == 99.0

    def test_stop_wait(self, override):
        override("stop.signal_seconds", 55.0)

        assert stop_seconds("signal") == 55.0

    def test_rider_profile(self, override):
        override("speed.cda_m2", 0.5)

        assert RiderProfile(cruise_speed_kmh=20.0).cda_m2 == 0.5

    def test_unpaved_rolling_resistance(self, override):
        override("speed.unpaved_crr", 0.077)

        assert crr_for_surface(np.array([0.0]), 1)[0] == 0.077

    def test_climb_power_ceiling(self, override):
        override("speed.max_climb_power_ratio", 9.0)

        assert climb_power_ratio(np.array([1.0]))[0] == 9.0

    def test_signal_match_radius(self, override):
        override("signal.match_radius_m", 12.0)

        assert signal_radius_params()["signal_radius_m"] == 12.0
