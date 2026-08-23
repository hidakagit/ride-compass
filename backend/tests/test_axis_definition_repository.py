import pytest

from app.domain.axis_definitions import AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository

# road_graph_session（conftest.py）はファイル単位でエンジン・イベントループを共有する設計
# のため、docs/testing.mdのパターン2どおりloop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis")]


def _definition(axis_id: str = "test_axis", default_weight: float = 0.1) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="dummy")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=default_weight,
    )


async def test_list_all_returns_empty_dict_when_no_rows(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)

    assert await repository.list_all() == {}


async def test_upsert_then_list_all_round_trips_shape_and_weight(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    definition = _definition()

    await repository.upsert(definition, sort_order=0)
    await repository.commit()

    result = await repository.list_all()
    assert result == {"test_axis": definition}


async def test_upsert_orders_by_sort_order_not_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("z_axis"), sort_order=0)
    await repository.upsert(_definition("a_axis"), sort_order=1)
    await repository.commit()

    assert list((await repository.list_all()).keys()) == ["z_axis", "a_axis"]


async def test_upsert_on_existing_axis_id_updates_in_place(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("test_axis", default_weight=0.1), sort_order=0)
    await repository.commit()

    await repository.upsert(_definition("test_axis", default_weight=0.9), sort_order=0)
    await repository.commit()

    result = await repository.list_all()
    assert len(result) == 1
    assert result["test_axis"].default_weight == 0.9


async def test_get_returns_definition_and_sort_order(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("test_axis"), sort_order=3)
    await repository.commit()

    result = await repository.get("test_axis")

    assert result is not None
    definition, sort_order = result
    assert definition == _definition("test_axis")
    assert sort_order == 3


async def test_get_returns_none_for_unknown_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)

    assert await repository.get("unknown") is None


async def test_next_sort_order_is_zero_when_empty(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)

    assert await repository.next_sort_order() == 0


async def test_next_sort_order_continues_after_max(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("a"), sort_order=0)
    await repository.upsert(_definition("b"), sort_order=5)
    await repository.commit()

    assert await repository.next_sort_order() == 6


async def test_delete_removes_row_and_returns_true(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("test_axis"), sort_order=0)
    await repository.commit()

    deleted = await repository.delete("test_axis")
    await repository.commit()

    assert deleted is True
    assert await repository.list_all() == {}


async def test_delete_returns_false_for_unknown_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)

    assert await repository.delete("unknown") is False


# --- axis_registry_meta.revision（改善計画T221 Stage D、将来のマルチプロセス対応・監査用） ---


async def test_get_revision_is_none_before_meta_row_exists(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)

    assert await repository.get_revision() is None


async def test_upsert_and_delete_each_bump_revision(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    # axis_registry_metaの初期行はmigration（0014_axis_definitions.sql）が投入する。
    # テストDBはBase.metadata.create_allのみでmigrationを経由しないため、ここで模擬する。
    from app.infrastructure.axis_definition_models import AxisRegistryMetaRow

    road_graph_session.add(AxisRegistryMetaRow(id=1, revision=1))
    await road_graph_session.commit()

    await repository.upsert(_definition("test_axis"), sort_order=0)
    await repository.commit()
    assert await repository.get_revision() == 2

    await repository.delete("test_axis")
    await repository.commit()
    assert await repository.get_revision() == 3
