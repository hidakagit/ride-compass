"""取り直せない管理データの書き出しと戻し（`scripts/admin_data_backup.py`）。

VMを失ったときに頼るのは、書き出したJSONを空のDBへ戻して、アプリがそのまま起動できることだけ。
入口（`dump`・`restore`）を実DBに当て、戻した中身をアプリと同じ読み込みで読み直して確かめる。
"""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tuning import TUNING_PARAMETERS_BY_ID
from app.infrastructure.admin_data_backup import AdminDataRestoreError
from app.infrastructure.axis_definition_models import AxisDefinitionRow
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.infrastructure.tuning_overrides import TuningOverrideRow, read_overrides, set_override
from app.services.axis_registry_service import AxisDefinitionSyncError
from scripts import admin_data_backup
from tests.axis_system_fixture import axis_definition

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]

#: アプリの読み込みは未知の材料参照を拒むため、カタログに実在する材料を持たせる。
CATALOG_MATERIAL = "gradient_percent"
_PARAM = "turn.right_seconds"


@pytest.fixture
def database_url(road_graph_engine) -> str:
    return road_graph_engine.url.render_as_string(hide_password=False)


async def _write_admin_data(session: AsyncSession) -> None:
    repository = AxisDefinitionRepository(session)
    await repository.upsert(
        axis_definition("slope", material=CATALOG_MATERIAL, is_published=True,
                        display_thresholds_override=[-5.0, -1.0, 1.0, 2.0, 3.0]),
        sort_order=0,
    )
    await repository.upsert(axis_definition("draft", material="slope", label="下書き"), sort_order=1)
    await set_override(session, _PARAM, TUNING_PARAMETERS_BY_ID[_PARAM].default + 7.0)
    await session.commit()


async def _snapshot(session: AsyncSession):
    axes = await AxisDefinitionRepository(session).list_all_with_sort_order()
    stamps = dict((await session.execute(select(AxisDefinitionRow.axis_id, AxisDefinitionRow.updated_at))).all())
    return axes, stamps, await read_overrides(session)


async def _clear(session: AsyncSession) -> None:
    await session.execute(AxisDefinitionRow.__table__.delete())
    await session.execute(TuningOverrideRow.__table__.delete())
    await session.commit()


async def test_restoring_into_an_empty_database_brings_back_what_was_dumped(road_graph_session, database_url):
    await _write_admin_data(road_graph_session)
    before = await _snapshot(road_graph_session)
    text = await admin_data_backup.dump(database_url)
    await _clear(road_graph_session)

    counts = await admin_data_backup.restore(database_url, text, replace=False)

    assert counts == {"axis_definitions": 2, "tuning_overrides": 1}
    assert await _snapshot(road_graph_session) == before


async def test_a_database_that_already_has_rows_is_left_untouched_unless_replacing(road_graph_session, database_url):
    await _write_admin_data(road_graph_session)
    text = await admin_data_backup.dump(database_url)
    await AxisDefinitionRepository(road_graph_session).upsert(
        axis_definition("draft", material="slope", label="戻す前に書き換えた"), sort_order=1)
    await road_graph_session.commit()

    with pytest.raises(AdminDataRestoreError, match="戻し先に行があります"):
        await admin_data_backup.restore(database_url, text, replace=False)
    axes = await AxisDefinitionRepository(road_graph_session).list_all()
    assert axes["draft"].label == "戻す前に書き換えた"

    await admin_data_backup.restore(database_url, text, replace=True)
    axes = await AxisDefinitionRepository(road_graph_session).list_all()
    assert axes["draft"].label == "下書き"


async def test_a_backup_the_app_could_not_load_writes_nothing(road_graph_session, database_url):
    # 戻したあとにアプリが起動できない中身なら、行を残さない（残すと起動の失敗で初めて分かる）。
    await _write_admin_data(road_graph_session)
    text = (await admin_data_backup.dump(database_url)).replace(f'"{CATALOG_MATERIAL}"', '"deleted_material"')
    await _clear(road_graph_session)

    with pytest.raises(AxisDefinitionSyncError, match="deleted_material"):
        await admin_data_backup.restore(database_url, text, replace=False)

    assert await AxisDefinitionRepository(road_graph_session).list_all() == {}
    assert await read_overrides(road_graph_session) == {}


async def test_a_column_the_schema_does_not_declare_stops_the_restore(road_graph_session, database_url):
    # 捨てて進むと、戻したつもりの値が黙って欠ける。
    await _write_admin_data(road_graph_session)
    document = json.loads(await admin_data_backup.dump(database_url))
    document["tables"]["axis_definitions"][0]["renamed_column"] = 1
    await _clear(road_graph_session)

    with pytest.raises(AdminDataRestoreError, match="renamed_column"):
        await admin_data_backup.restore(database_url, json.dumps(document), replace=False)

    assert await AxisDefinitionRepository(road_graph_session).list_all() == {}


async def test_nothing_is_dumped_when_the_app_could_not_start_from_it(road_graph_session, database_url):
    # 軸が0行のDBからは起動できない。その中身で最新のバックアップを上書きさせない。
    with pytest.raises(AxisDefinitionSyncError, match="空です"):
        await admin_data_backup.dump(database_url)
