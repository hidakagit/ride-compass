import pytest

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.infrastructure.axis_definition_models import AxisRegistryMetaRow
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.services.axis_registry_service import AxisRegistryAdminService, refresh_axis_definitions

pytestmark = [pytest.mark.asyncio(loop_scope="module"), pytest.mark.xdist_group(name="postgis")]


@pytest.fixture(autouse=True)
def restore_axis_definitions():
    # refresh_axis_definitionsはグローバルなAXIS_DEFINITIONS（プロセス全体で共有）をin-place
    # 更新するため、他のテストファイルへ汚染が漏れないよう必ずスナップショット・復元する
    # （services/axis_registry_service.pyのdocstring参照）。
    snapshot = dict(AXIS_DEFINITIONS)
    yield
    AXIS_DEFINITIONS.clear()
    AXIS_DEFINITIONS.update(snapshot)


def _definition(axis_id: str = "test_axis", default_weight: float = 0.1) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="dummy")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=default_weight,
    )


# --- refresh_axis_definitions（起動時ロード相当） ---


async def test_refresh_keeps_builtin_defaults_when_table_empty(road_graph_session, caplog):
    original = dict(AXIS_DEFINITIONS)
    repository = AxisDefinitionRepository(road_graph_session)

    await refresh_axis_definitions(repository)

    assert AXIS_DEFINITIONS == original
    assert "コード内蔵の既定値を使用します" in caplog.text


async def test_refresh_replaces_axis_definitions_with_db_content(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("test_axis"), sort_order=0)
    await repository.commit()

    await refresh_axis_definitions(repository)

    assert set(AXIS_DEFINITIONS.keys()) == {"test_axis"}


async def test_refresh_falls_back_on_repository_error(road_graph_session, caplog):
    original = dict(AXIS_DEFINITIONS)

    class _BrokenRepository:
        async def list_all(self):
            raise RuntimeError("boom")

    await refresh_axis_definitions(_BrokenRepository())

    assert AXIS_DEFINITIONS == original
    assert "軸定義のDB読み込みに失敗" in caplog.text


# --- AxisRegistryAdminService（管理APIのユースケース層） ---


async def test_create_persists_and_refreshes_process_cache(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    await service.create(_definition("test_axis"))

    assert "test_axis" in AXIS_DEFINITIONS
    assert (await repository.list_all())["test_axis"] == _definition("test_axis")


async def test_create_rejects_duplicate_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis"))

    with pytest.raises(ValueError, match="既に存在します"):
        await service.create(_definition("test_axis"))


async def test_update_replaces_definition_and_keeps_sort_order(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis", default_weight=0.1))
    await repository.upsert(_definition("second"), sort_order=99)  # sort_order維持の確認用ダミー
    await repository.commit()
    _, original_sort_order = await repository.get("test_axis")

    await service.update("test_axis", _definition("test_axis", default_weight=0.9))

    assert AXIS_DEFINITIONS["test_axis"].default_weight == 0.9
    _, sort_order_after = await repository.get("test_axis")
    assert sort_order_after == original_sort_order


async def test_update_raises_key_error_for_unknown_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    with pytest.raises(KeyError):
        await service.update("unknown", _definition("unknown"))


async def test_delete_removes_definition_and_refreshes_process_cache(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis"))
    await service.create(_definition("other_axis"))  # 最後の1軸削除ガードに引っかからないための2軸目

    await service.delete("test_axis")

    assert "test_axis" not in AXIS_DEFINITIONS
    assert await repository.get("test_axis") is None


async def test_delete_raises_key_error_for_unknown_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    with pytest.raises(KeyError):
        await service.delete("unknown")


async def test_delete_rejects_removing_the_last_remaining_axis(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis"))

    with pytest.raises(ValueError, match="最後の1軸"):
        await service.delete("test_axis")

    assert "test_axis" in AXIS_DEFINITIONS  # 削除されず、キャッシュも変わっていない


async def test_get_returns_none_for_unknown_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    assert await service.get("unknown") is None
