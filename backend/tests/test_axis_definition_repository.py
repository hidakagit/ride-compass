"""`infrastructure/axis_definition_repository.py`——評価軸の定義を表へ書き、読み戻す。

入口は`AxisDefinitionRepository`の公開のメソッド。テスト用DBの本物の表へ書き、読み戻した定義を
書いた定義と比べる。軸は架空のもの（`axis_a`等。材料の名前も架空）で、本番の軸定義には踏み込まない。

ここで見ないもの:
- 書く前の検証（材料の排他・公開済みの不変・循環）と、操作ごとの確定 → `test_axis_registry_service.py`
- 定義そのものの値の検証（折れ点の並び・段のラベルの件数等） → `test_axis_definitions.py`
- `list_all`の並び → `list_all_with_sort_order`から順の値を落として詰め替えるだけで、判断を持たない
"""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


def _linear(axis_id: str, **overrides) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="num_a", weight=0.5), MaterialTerm(material="num_b", required=False)],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (10.0, 100.0)],
        ),
        default_weight=1.5,
        label=f"{axis_id}の表示名",
        **overrides,
    )


def _with_every_field_set(axis_id: str) -> AxisDefinition:
    """既定値から外した値をすべての欄に置いた定義（列の型との往復で値が変わると、読み戻しで既定値や別の値に化ける）。

    読み書きする欄の顔ぶれは、実装が軸定義の欄から導く。欄を足して列を足し忘れると、どの書き込みも断られる。"""
    return AxisDefinition(
        axis_id=axis_id,
        shape=CategoricalShape(material="cat_a", mapping={"paved": 10.0, "yes": 20.0, "1": 30.0}),
        default_weight=0.25,
        label="全部の欄",
        description="説明",
        category="観測",
        is_published=True,
        priority_overrides=[PriorityCondition(material="bool_a", equals="true", value=5.0)],
        icon_id="icon",
        chip_label="チップ",
        panel_hint="ヒント",
        show_map_icon=False,
        time_scope="night_only",
        display_thresholds_override=[10.0, 20.0],
        display_band_labels_override=["低", "中", "高"],
        dedicated_way_value_layer=True,
    )


@pytest_asyncio.fixture(loop_scope="module")
async def repository(road_graph_session: AsyncSession) -> AxisDefinitionRepository:
    return AxisDefinitionRepository(road_graph_session)


@pytest.mark.parametrize("definition", [
    _with_every_field_set("axis_a"),
    # JSONのキーは文字列になるので、真偽の対応表は読み戻しで真偽へ戻る（値の名前"yes"・"1"は上の行が見る）。
    _linear("axis_a").model_copy(
        update={"shape": CategoricalShape(material="bool_a", mapping={True: 1.0, False: 2.0})}),
])
async def test_a_written_definition_reads_back_with_every_field_and_its_order(repository, definition):
    await repository.upsert(definition, sort_order=3)

    assert await repository.get("axis_a") == (definition, 3)


async def test_writing_an_existing_axis_replaces_every_field_and_its_order(repository):
    await repository.upsert(_linear("axis_a"), sort_order=1)
    replacement = _with_every_field_set("axis_a")

    await repository.upsert(replacement, sort_order=7)

    assert await repository.get("axis_a") == (replacement, 7)
    assert list(await repository.list_all()) == ["axis_a"]


async def test_the_axes_are_listed_in_their_order_not_in_the_order_they_were_written(repository):
    """並びは合成の加算順で、順が変わると合成の得点がビット単位で変わりうる。"""
    await repository.upsert(_linear("axis_c"), sort_order=30)
    await repository.upsert(_linear("axis_a"), sort_order=10)
    await repository.upsert(_linear("axis_b"), sort_order=20)

    with_order = await repository.list_all_with_sort_order()

    assert [(axis_id, order) for axis_id, (_, order) in with_order.items()] == [
        ("axis_a", 10), ("axis_b", 20), ("axis_c", 30)]


async def test_deleting_tells_whether_there_was_an_axis_to_delete(repository):
    await repository.upsert(_linear("axis_a"), sort_order=1)

    assert await repository.delete("axis_a") is True
    assert await repository.get("axis_a") is None
    assert await repository.delete("axis_a") is False


async def test_writes_are_seen_by_others_only_after_the_commit(repository, road_graph_engine):
    await repository.upsert(_linear("axis_a"), sort_order=1)

    async with AsyncSession(road_graph_engine) as other:
        assert await AxisDefinitionRepository(other).get("axis_a") is None
        await repository.commit()
        assert await AxisDefinitionRepository(other).get("axis_a") == (_linear("axis_a"), 1)


async def test_the_write_lock_makes_a_second_writer_wait_until_the_first_commits(repository, road_graph_engine):
    await repository.acquire_write_lock()

    async with AsyncSession(road_graph_engine) as other:
        second = AxisDefinitionRepository(other)
        waiting = asyncio.ensure_future(second.acquire_write_lock())
        await asyncio.sleep(0.2)
        assert not waiting.done()
        await repository.commit()
        await asyncio.wait_for(waiting, timeout=5)
        await other.rollback()
