"""較正値の上書き（`infrastructure/tuning_overrides.py`）のテスト。

既定値は宣言が持ち、DBは差分だけを持つ。**行が1つも無くても宣言どおりに動く**ことと、
壊れた行の扱いが2通りに分かれること（宣言から消えたidは無視、範囲の外は落とす）を固定する。

ここで見ないもの:
- 書き込みの取引の区切りと、書いた値をプロセスへ反映する順 → `test_tuning_service.py`
- HTTPの受け口 → `test_tuning_admin_routes.py`、派生バッチが同じ値を読むこと → `test_derive_cli.py`
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import tuning
from app.domain.tuning import TUNING_PARAMETERS, TUNING_PARAMETERS_BY_ID
from app.infrastructure.tuning_overrides import (
    TuningOverrideError,
    TuningOverrideRow,
    clear_override,
    merge_overrides,
    read_overrides,
    set_override,
)
from app.services.tuning_service import refresh_tuning_values

# 範囲の広いものを選ぶ（値を動かしても宣言の範囲に収まるように）。
_PARAM = "turn.right_seconds"


class TestMerge:
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

    @pytest.mark.parametrize("value", [TUNING_PARAMETERS_BY_ID[_PARAM].maximum + 1.0, float("nan")],
                             ids=["範囲の外", "数値でない"])
    def test_a_broken_value_is_fatal(self, value):
        # 間違った値が静かに効く方が悪い。
        with pytest.raises(TuningOverrideError):
            merge_overrides({_PARAM: value})


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
async def test_writing_an_undeclared_id_is_rejected(road_graph_session: AsyncSession):
    with pytest.raises(TuningOverrideError):
        await set_override(road_graph_session, "turn.no_such_value", 1.0)


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.xdist_group(name="postgis")
@pytest.mark.postgis
async def test_the_row_records_when_it_was_changed(road_graph_session: AsyncSession):
    """`updated_at`が実際のDBに在って、挿入でも書き換えでも書いた時刻へ進む。"""
    default = TUNING_PARAMETERS_BY_ID[_PARAM].default
    before = datetime.now(UTC)

    async def updated_at() -> datetime:
        return (
            await road_graph_session.execute(
                select(TuningOverrideRow.updated_at).where(TuningOverrideRow.param_id == _PARAM)
            )
        ).scalar_one()

    try:
        await set_override(road_graph_session, _PARAM, default + 3.0)
        await road_graph_session.commit()
        first = await updated_at()
        assert first >= before

        # 既にある行の値を動かしたときも、動かした時刻へ進む（列の既定は挿入にしか効かない）。
        await set_override(road_graph_session, _PARAM, default + 4.0)
        await road_graph_session.commit()
        assert await updated_at() > first
    finally:
        await clear_override(road_graph_session, _PARAM)
        await road_graph_session.commit()
        await refresh_tuning_values(road_graph_session)
