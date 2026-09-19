"""較正値の宣言（`domain/tuning.py`）のテスト。

宣言を1つにした狙いは「エンジンが読む値・管理画面が並べる項目・変更が効くために何をやり直す
必要があるか」を1箇所から導くこと。**宣言を変えたときに消費者へ届く**ことが守られていないと、
管理画面から変えても何も起きない状態になる。
"""

import numpy as np
import pytest

from app.domain import tuning
from app.domain.cycling_speed import (
    RiderProfile,
    climb_power_ratio,
    crr_for_surface,
    speed_ms,
)
from app.domain.evaluation import resolve_penalty_strength
from app.domain.routing import current_turn_cost
from app.domain.traffic import POI_COUNT_KINDS, stop_seconds
from app.domain.tuning import (
    TUNING_PARAMETERS,
    TUNING_PARAMETERS_BY_ID,
    TuningEffect,
    client_tuning_values,
    stop_seconds_parameter_id,
    tuning_value,
    turn_parameter_ids,
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


class TestReachesTheClient:
    """フロントが使う値も、宣言を変えれば届くこと。"""

    def test_what_goes_to_the_client_comes_from_the_declaration(self):
        # 配信側とフロント側で別々に並べると、1つ足したときに片方だけが古くなる。
        assert set(client_tuning_values()) == {
            p.id for p in TUNING_PARAMETERS if p.effect is TuningEffect.CLIENT_RELOAD
        }

    def test_the_client_gets_the_value_in_effect_rather_than_the_default(self, override):
        param_id = sorted(client_tuning_values())[0]
        override(param_id, 9.5)

        assert client_tuning_values()[param_id] == 9.5


def _turn_probe(param_id: str):
    """`turn.right_seconds` → `current_turn_cost().right_seconds`。"""
    field = param_id.split(".", 1)[1]
    return lambda: float(getattr(current_turn_cost(), field))


def _speed_kmh_at(grade: float) -> float:
    """その勾配での走行速度（km/h）。

    極端な勾配では解が探索範囲の外へ出るため、二分法は**上下限そのもの**（歩く速さ・
    最高速度）へ収束する——その2つはここを通さないと観測できない。
    """
    profile = RiderProfile(cruise_speed_kmh=20.0)
    solved = speed_ms(profile, np.array([grade]), np.zeros(1))
    return float(solved[0]) * 3.6


#: 較正値id → (上書きする値, その値が届いたことを観測する読み出し)。
#: そのまま読み返せる値ばかりではない——上下限として効く値は、頭打ちになる入力を1つ
#: 通して初めて「届いた」と言える。
CONSUMER_PROBES: dict[str, tuple[float, object]] = {
    **{pid: (91.0 + i, _turn_probe(pid)) for i, pid in enumerate(turn_parameter_ids())},
    **{
        stop_seconds_parameter_id(kind): (51.0 + i, lambda kind=kind: stop_seconds(kind))
        for i, kind in enumerate(POI_COUNT_KINDS)
    },
    "signal.match_radius_m": (12.0, lambda: signal_radius_params()["signal_radius_m"]),
    "speed.cda_m2": (0.5, lambda: RiderProfile(cruise_speed_kmh=20.0).cda_m2),
    "speed.crr": (0.009, lambda: RiderProfile(cruise_speed_kmh=20.0).crr),
    "speed.mass_kg": (70.0, lambda: RiderProfile(cruise_speed_kmh=20.0).mass_kg),
    "speed.unpaved_crr": (0.077, lambda: float(crr_for_surface(np.array([0.0]), 1)[0])),
    # 勾配100%では`1 + 係数 × 1.0`が上限を超えるため、上限の側が観測できる。
    "speed.max_climb_power_ratio": (9.0, lambda: float(climb_power_ratio(np.array([1.0]))[0])),
    # 逆に上限（既定2.5）へ届かない係数を入れれば、係数の側が観測できる。
    "speed.climb_power_per_grade": (
        0.5,
        lambda: float(climb_power_ratio(np.array([1.0]))[0]) - 1.0,
    ),
    # 登れない急勾配では歩く速さで、止まらない急な下りでは最高速度で頭打ちになる。
    "speed.walking_kmh": (36.0, lambda: _speed_kmh_at(1.0)),
    "speed.max_descent_kmh": (7.2, lambda: _speed_kmh_at(-1.0)),
    "splice.min_stretch_km": (0.9, lambda: client_tuning_values()["splice.min_stretch_km"]),
    # リクエストが省略したときの値は、**呼ばれた時点で**較正値から読む。
    "evaluation.penalty_strength": (1.5, lambda: resolve_penalty_strength(None)),
}


class TestReachesTheConsumers:
    """宣言を変えると、実際に読んでいる側まで届くこと。

    届かない値が混ざっていると、管理画面から変えても何も起きない——それでいて画面の
    表示は変えられたのと同じになる。

    **母集団は`TUNING_PARAMETERS`から導く**。手で選んだ数件を並べていたときは、
    唯一実際に届かなかった1件がちょうどその外にあった（`evaluation.penalty_strength`
    がimport時に束ねられていた）。
    """

    def test_every_declared_value_has_a_probe(self):
        missing = sorted(p.id for p in TUNING_PARAMETERS if p.id not in CONSUMER_PROBES)

        assert missing == [], (
            f"届くことを確かめる読み出しが無い較正値: {missing}。"
            "CONSUMER_PROBESへ「上書きした値が観測できる読み出し」を1件足すこと。"
        )

    def test_no_probe_outlives_the_value_it_watches(self):
        declared = {p.id for p in TUNING_PARAMETERS}

        assert sorted(k for k in CONSUMER_PROBES if k not in declared) == []

    @pytest.mark.parametrize("param_id", sorted(CONSUMER_PROBES))
    def test_reaches_its_consumer(self, override, param_id):
        sentinel, observe = CONSUMER_PROBES[param_id]
        override(param_id, sentinel)

        assert observe() == pytest.approx(sentinel, rel=2e-3)
