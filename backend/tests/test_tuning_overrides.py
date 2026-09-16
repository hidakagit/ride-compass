"""較正値の上書き（`infrastructure/tuning_overrides.py`）のテスト。

既定値は宣言が持ち、DBは差分だけを持つ。**行が1つも無くても宣言どおりに動く**ことと、
壊れた行の扱いが2通りに分かれること（宣言から消えたidは無視、範囲の外は落とす）を固定する。
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import tuning
from app.domain.tuning import TUNING_PARAMETERS, TUNING_PARAMETERS_BY_ID
from app.infrastructure.tuning_overrides import (
    TuningOverrideError,
    clear_override,
    merge_overrides,
    read_overrides,
    refresh_tuning_values,
    set_override,
)

# 範囲の広いものを選ぶ（値を動かしても宣言の範囲に収まるように）。
_PARAM = "turn.right_seconds"


class TestMerge:
    def test_no_override_means_the_declared_defaults(self):
        assert merge_overrides({}) == {p.id: p.default for p in TUNING_PARAMETERS}

    def test_an_override_replaces_only_that_value(self):
        merged = merge_overrides({_PARAM: 30.0})

        assert merged[_PARAM] == 30.0
        others = {k: v for k, v in merged.items() if k != _PARAM}
        assert others == {p.id: p.default for p in TUNING_PARAMETERS if p.id != _PARAM}

    def test_a_row_for_a_removed_parameter_is_ignored_rather_than_fatal(self, caplog):
        # 宣言から1つ減らしただけで本番の起動が失敗するのは割に合わない。
        merged = merge_overrides({"turn.no_longer_declared": 1.0})

        assert merged == {p.id: p.default for p in TUNING_PARAMETERS}
        assert "宣言に無いid" in caplog.text

    def test_a_value_outside_the_declared_range_is_fatal(self):
        # 間違った値が静かに効く方が悪い。
        too_big = TUNING_PARAMETERS_BY_ID[_PARAM].maximum + 1.0

        with pytest.raises(TuningOverrideError):
            merge_overrides({_PARAM: too_big})

    def test_a_non_numeric_value_is_fatal(self):
        with pytest.raises(TuningOverrideError):
            merge_overrides({_PARAM: float("nan")})


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.xdist_group(name="postgis")
@pytest.mark.postgis
async def test_override_round_trip_reaches_the_running_value(road_graph_session: AsyncSession):
    """書いた値が、プロセス内の`TUNING_VALUES`まで届いて消費者に効く。"""
    default = TUNING_PARAMETERS_BY_ID[_PARAM].default
    changed = default + 7.0
    try:
        await set_override(road_graph_session, _PARAM, changed)
        await road_graph_session.commit()

        assert await read_overrides(road_graph_session) == {_PARAM: changed}

        await refresh_tuning_values(road_graph_session)
        assert tuning.tuning_value(_PARAM) == changed

        # 既定値と同じ値を書くと行が消える（差分だけを持つ形を保つ）。
        await set_override(road_graph_session, _PARAM, default)
        await road_graph_session.commit()
        assert await read_overrides(road_graph_session) == {}

        await refresh_tuning_values(road_graph_session)
        assert tuning.tuning_value(_PARAM) == default
    finally:
        await clear_override(road_graph_session, _PARAM)
        await road_graph_session.commit()
        await refresh_tuning_values(road_graph_session)


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.xdist_group(name="postgis")
@pytest.mark.postgis
async def test_an_empty_table_leaves_every_declared_default(road_graph_session: AsyncSession):
    """行が1つも無くても宣言どおりに動く（fresh bootstrapで投入が要らない）。"""
    await refresh_tuning_values(road_graph_session)

    for parameter in TUNING_PARAMETERS:
        assert tuning.tuning_value(parameter.id) == parameter.default


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.xdist_group(name="postgis")
@pytest.mark.postgis
async def test_writing_an_undeclared_id_is_rejected(road_graph_session: AsyncSession):
    with pytest.raises(TuningOverrideError):
        await set_override(road_graph_session, "turn.no_such_value", 1.0)
