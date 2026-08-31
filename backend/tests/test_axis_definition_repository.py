import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    PriorityCondition,
)
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository

# road_graph_session（conftest.py）はファイル単位でエンジン・イベントループを共有する設計
# のため、docs/testing.mdのパターン2どおりloop_scope="module"・xdist_group="postgis"が必須。
pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


def _definition(axis_id: str = "test_axis", default_weight: float = 0.1) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="dummy")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=default_weight,
        label=f"テスト軸[{axis_id}]",
        description="テスト用ダミー軸",
        category="推定",
    )


# 改善計画T469: create/update/delete/unpublish（AxisRegistryAdminService）のTOCTOUレース
# 対策として新設したacquire_write_lockが、実際に別トランザクションをブロックすることを
# 確認する（advisory lockがトランザクションスコープで正しく機能しているかの回帰テスト）。
async def test_acquire_write_lock_blocks_until_holder_commits(road_graph_session, road_graph_engine):
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.acquire_write_lock()  # road_graph_sessionが未commitのままロックを保持

    async with AsyncSession(road_graph_engine, expire_on_commit=False) as other_session:
        other_repository = AxisDefinitionRepository(other_session)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(other_repository.acquire_write_lock(), timeout=0.5)
        await other_session.rollback()

    await repository.commit()  # ロック解放

    # 解放後は別セッションからでも即座に取得できる。
    async with AsyncSession(road_graph_engine, expire_on_commit=False) as third_session:
        third_repository = AxisDefinitionRepository(third_session)
        await asyncio.wait_for(third_repository.acquire_write_lock(), timeout=0.5)
        await third_session.rollback()


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


async def test_upsert_then_list_all_round_trips_categorical_bool_keys(road_graph_session):
    # 改善計画T292回帰テスト: CategoricalShape.mappingをdict[bool|str, float]へ広げた際、
    # 既定のPydantic smart-mode union解決だとJSON文字列"true"/"false"がbool True/Falseへ
    # 強制変換されずstr型のまま残ってしまい、DB往復後にmapping={"true": ..., "false": ...}
    # （str キー）になる回帰が実データ検証で発覚した（本来はmapping={True: ..., False: ...}）。
    # union_mode="left_to_right"でbool判定を先に試すよう修正済み。
    definition = AxisDefinition(
        axis_id="bool_categorical_axis",
        shape=CategoricalShape(material="surface_good", mapping={True: 0.0, False: 80.0}),
        default_weight=0.1,
        label="テスト軸[bool_categorical_axis]",
        description="",
        category="推定",
    )
    repository = AxisDefinitionRepository(road_graph_session)

    await repository.upsert(definition, sort_order=0)
    await repository.commit()

    result = await repository.list_all()
    loaded_shape = result["bool_categorical_axis"].shape
    assert isinstance(loaded_shape, CategoricalShape)
    assert loaded_shape.mapping == {True: 0.0, False: 80.0}
    assert all(isinstance(key, bool) for key in loaded_shape.mapping)


async def test_upsert_then_list_all_round_trips_categorical_str_keys(road_graph_session):
    # 上と対称: 通常のstr多値categorical材料（highway等）は文字列キーのまま
    # 正しく往復すること（bool優先判定の副作用で意図せずbool化されないことの確認）。
    definition = AxisDefinition(
        axis_id="str_categorical_axis",
        shape=CategoricalShape(material="bicycle_infra", mapping={"separated": -2.0, "roadway": 1.0}),
        default_weight=0.1,
        label="テスト軸[str_categorical_axis]",
        description="",
        category="推定",
    )
    repository = AxisDefinitionRepository(road_graph_session)

    await repository.upsert(definition, sort_order=0)
    await repository.commit()

    result = await repository.list_all()
    loaded_shape = result["str_categorical_axis"].shape
    assert isinstance(loaded_shape, CategoricalShape)
    assert loaded_shape.mapping == {"separated": -2.0, "roadway": 1.0}
    assert all(isinstance(key, str) for key in loaded_shape.mapping)


async def test_upsert_then_list_all_round_trips_priority_overrides(road_graph_session):
    # コードレビュー指摘の修正確認: priority_overrides（0次条件）がDB往復で
    # 失われないこと（以前はカラム自体が無く、DB経由では常に空リストへ戻っていた）。
    definition = AxisDefinition(
        axis_id="priority_override_axis",
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="dummy")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=0.1,
        label="テスト軸[priority_override_axis]",
        description="",
        category="推定",
        priority_overrides=[PriorityCondition(material="motor_vehicle_no", equals="true", value=0.0)],
    )
    repository = AxisDefinitionRepository(road_graph_session)

    await repository.upsert(definition, sort_order=0)
    await repository.commit()

    result = await repository.list_all()
    assert result["priority_override_axis"].priority_overrides == [
        PriorityCondition(material="motor_vehicle_no", equals="true", value=0.0)
    ]


async def test_upsert_then_list_all_round_trips_display_fields(road_graph_session):
    # 改善計画T310/T318回帰テスト: 地図チップ表示要素（icon_id/chip_label/panel_hint/
    # show_map_icon）がDB往復で失われないこと（priority_overridesの0018回帰と同じ
    # パターン、先回りしてテストを用意する）。show_map_iconは既定Trueとは違う値
    # （False）を設定し、既定値と取り違えていないことを確認する。
    definition = AxisDefinition(
        axis_id="display_fields_axis",
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="dummy")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=0.1,
        label="テスト軸[display_fields_axis]",
        description="",
        category="推定",
        icon_id="incline",
        chip_label="テスト",
        panel_hint="パネル向け説明文",
        show_map_icon=False,
    )
    repository = AxisDefinitionRepository(road_graph_session)

    await repository.upsert(definition, sort_order=0)
    await repository.commit()

    result = await repository.list_all()
    assert result == {"display_fields_axis": definition}


async def test_upsert_then_list_all_round_trips_display_fields_when_unset(road_graph_session):
    # icon_id/chip_label/panel_hintの未設定（None）は「フロント側の汎用フォールバックを
    # 使う」の意味であり、priority_overridesの`[]`既定と違ってNoneのままdb往復する必要が
    # ある。show_map_iconはこれらと違い常に確定した真偽値（既定True）を持つフィールドの
    # ため、未設定でもTrueとして往復することを確認する（改善計画T318）。
    definition = _definition("no_display_fields_axis")
    repository = AxisDefinitionRepository(road_graph_session)

    await repository.upsert(definition, sort_order=0)
    await repository.commit()

    result = await repository.list_all()
    loaded = result["no_display_fields_axis"]
    assert loaded.icon_id is None
    assert loaded.chip_label is None
    assert loaded.panel_hint is None
    assert loaded.show_map_icon is True


async def test_upsert_then_list_all_round_trips_dedicated_way_value_layer(road_graph_session):
    # 改善計画T440フォローアップ: dedicated_way_value_layer=True（非既定値）がDB往復で
    # 失われないことの回帰テスト。UPSERT文のvalues()にこのフィールドを渡し忘れていても
    # ON CONFLICT SET句のexcluded参照だけでは値が反映されず、常に既定のFalseへ静かに
    # 戻ってしまう不具合が実際にあった（axis_admin API経由での手動確認で発覚、
    # test_axis_admin_routes.pyの往復テストはoverride_service[実DBを使わないフェイク]
    # 経由のためこの種の不具合を検出できなかった）。
    definition = AxisDefinition(
        axis_id="dedicated_way_value_layer_axis",
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="dummy")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=0.1,
        label="テスト軸[dedicated_way_value_layer_axis]",
        description="",
        category="推定",
        dedicated_way_value_layer=True,
    )
    repository = AxisDefinitionRepository(road_graph_session)

    await repository.upsert(definition, sort_order=0)
    await repository.commit()

    result = await repository.list_all()
    assert result["dedicated_way_value_layer_axis"].dedicated_way_value_layer is True


async def test_upsert_then_list_all_round_trips_dynamic_way_value_needs(road_graph_session):
    # 改善計画T458: dynamic_way_value_needs_time/dynamic_way_value_needs_bearing
    # （非既定値）がDB往復で失われないことの回帰テスト（dedicated_way_value_layerの
    # 上記回帰テストと同型）。
    definition = AxisDefinition(
        axis_id="dynamic_way_value_needs_axis",
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="dummy")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=0.1,
        label="テスト軸[dynamic_way_value_needs_axis]",
        description="",
        category="推定",
        dedicated_way_value_layer=True,
        dynamic_way_value_needs_time=True,
        dynamic_way_value_needs_bearing=True,
    )
    repository = AxisDefinitionRepository(road_graph_session)

    await repository.upsert(definition, sort_order=0)
    await repository.commit()

    result = await repository.list_all()
    assert result["dynamic_way_value_needs_axis"].dynamic_way_value_needs_time is True
    assert result["dynamic_way_value_needs_axis"].dynamic_way_value_needs_bearing is True


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


async def test_list_all_with_sort_order_returns_empty_dict_when_empty(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)

    assert await repository.list_all_with_sort_order() == {}


async def test_list_all_with_sort_order_returns_definitions_and_sort_order(road_graph_session):
    # 改善計画T271のレビュー指摘の修正: AxisRegistryAdminService.create/updateが
    # 既存軸一覧の取得とsort_order算出を1回のSELECTで済ませられるよう新設したメソッド。
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("a"), sort_order=0)
    await repository.upsert(_definition("b"), sort_order=5)
    await repository.commit()

    result = await repository.list_all_with_sort_order()

    assert result["a"] == (_definition("a"), 0)
    assert result["b"] == (_definition("b"), 5)


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
