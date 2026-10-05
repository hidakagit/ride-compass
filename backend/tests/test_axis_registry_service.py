"""`services/axis_registry_service.py`——起動時の読み込みと、管理APIの書き込み（DBへの反映と`AXIS_DEFINITIONS`の差し替え）。

書き込みのガード（公開の不変性・材料の排他・内部軸の公開・循環）は、書き込みが確定する前に断ることを、断る側の1本で見る。

ここで見ないもの:
- ガードの判断の両側と断りの文 → `test_axis_definitions.py`・`test_axis_hierarchy.py`
- 断りを管理APIが404・409で返すこと → `test_axis_admin_routes.py`
"""

import pytest

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDependencyCycleError,
    AxisInternalAxisPublishError,
    AxisMaterialConflictError,
    AxisPublishedImmutableError,
)
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.services.axis_registry_service import (
    AxisDefinitionSyncError,
    AxisRegistryAdminService,
    refresh_axis_definitions,
)
from tests.axis_system_fixture import axis_definition, axis_definitions_snapshot

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


@pytest.fixture(autouse=True)
def restore_axis_definitions():
    # refresh_axis_definitionsはプロセス全体で共有するAXIS_DEFINITIONSをin-place更新する
    # ため、他のテストファイルへ汚染が漏れないよう必ずスナップショット・復元する。
    with axis_definitions_snapshot():
        yield


#: `refresh_axis_definitions`は未知の材料参照を拒むため、材料が主題でない軸にもカタログに
#: 実在する材料を持たせる。
CATALOG_MATERIAL = "gradient_percent"


# --- refresh_axis_definitions（起動時ロード相当） ---


async def test_refresh_raises_when_table_empty(road_graph_session):
    # コード内蔵の既定値へフォールバックせず例外にする。AXIS_DEFINITIONSは変わらない。
    original = dict(AXIS_DEFINITIONS)
    repository = AxisDefinitionRepository(road_graph_session)

    with pytest.raises(AxisDefinitionSyncError, match="空です"):
        await refresh_axis_definitions(repository)

    assert AXIS_DEFINITIONS == original


async def test_refresh_raises_on_repository_error(road_graph_session):
    # DB接続自体が失敗した場合もfail-fast（AxisDefinitionSyncErrorへラップして再送出）。
    original = dict(AXIS_DEFINITIONS)

    class _BrokenRepository:
        async def list_all(self):
            raise RuntimeError("boom")

    with pytest.raises(AxisDefinitionSyncError, match="軸定義のDB読み込みに失敗"):
        await refresh_axis_definitions(_BrokenRepository())

    assert AXIS_DEFINITIONS == original


async def test_refresh_raises_when_axis_references_unknown_material(road_graph_session):
    # 「行は読めるが、削除済みの材料idを参照している」状態を、管理APIを通さずrepositoryへ直接
    # 書き込んで作る。検出時はfail-fastする。
    original = dict(AXIS_DEFINITIONS)
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(axis_definition("test_axis", material="deleted_material"), sort_order=0)
    await repository.commit()

    with pytest.raises(AxisDefinitionSyncError, match="deleted_material") as exc_info:
        await refresh_axis_definitions(repository)

    assert "アプリが受け入れない軸があります" in str(exc_info.value)
    assert AXIS_DEFINITIONS == original


@pytest.mark.parametrize(
    ("materials", "named"),
    [
        (("axis_b", "axis_a"), "axis_a→axis_b→axis_a"),
        (("bridge", "bridge"), "axis_b: 材料 bridge を axis_a も使っています"),
    ],
    ids=["axes_combine_in_a_cycle", "two_axes_count_one_material"],
)
async def test_refresh_raises_when_the_axes_together_break_an_invariant(road_graph_session, materials, named):
    # 1本ずつは通るが、集まると不変条件を破る軸を、管理APIを通さずに書く（バックアップから戻した行）。
    # 運用者がログから直す行を辿れるよう、軸をidで名指す。集合の検査の中身は`test_axis_definitions.py`が見る。
    original = dict(AXIS_DEFINITIONS)
    repository = AxisDefinitionRepository(road_graph_session)
    for sort_order, (axis_id, material) in enumerate(zip(("axis_a", "axis_b"), materials, strict=True)):
        await repository.upsert(axis_definition(axis_id, material=material), sort_order=sort_order)
    await repository.commit()

    with pytest.raises(AxisDefinitionSyncError, match=named):
        await refresh_axis_definitions(repository)

    assert AXIS_DEFINITIONS == original


# --- AxisRegistryAdminService（管理APIのユースケース層） ---


async def test_create_persists_and_refreshes_process_cache(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    await service.create(axis_definition("test_axis", material=CATALOG_MATERIAL))

    assert "test_axis" in AXIS_DEFINITIONS
    assert (await repository.list_all())["test_axis"] == axis_definition("test_axis", material=CATALOG_MATERIAL)


async def test_create_rejects_axis_id_colliding_with_known_material(road_graph_session):
    # MATERIAL_CATALOGに実在する材料id（例: "highway"）と同名のaxis_idは
    # 作成できない。放置すると評価時に生の材料値がdifficulty値で上書きされ、それ以降に
    # 評価される軸が黙って壊れる（axis_definitions.py: evaluate_axes_array参照）。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    with pytest.raises(ValueError, match="highway"):
        await service.create(axis_definition("highway", material="wind_drag_ratio"))

    assert "highway" not in AXIS_DEFINITIONS


async def test_create_rejects_duplicate_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("test_axis", material=CATALOG_MATERIAL))

    with pytest.raises(ValueError, match="既に存在します"):
        await service.create(axis_definition("test_axis", material=CATALOG_MATERIAL))


async def test_create_rejects_axis_reusing_existing_material(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("first_axis", material="bridge"))

    with pytest.raises(AxisMaterialConflictError, match="「橋・高架」"):
        await service.create(axis_definition("second_axis", material="bridge"))

    assert "second_axis" not in AXIS_DEFINITIONS


async def test_update_rejects_axis_reusing_another_axis_material(road_graph_session):
    # 直す軸が相手より前に並んでいても、断りは相手の軸を「すでに使っている軸」と名指す。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("first_axis", material="oneway"))
    await service.create(axis_definition("second_axis", material="motor_vehicle_no"))

    with pytest.raises(AxisMaterialConflictError, match="「自動車通行不可」") as caught:
        await service.update("first_axis", axis_definition("first_axis", material="motor_vehicle_no"))

    assert (caught.value.axis_id, caught.value.conflicting_axis_id) == ("first_axis", "second_axis")
    assert AXIS_DEFINITIONS["first_axis"].materials == ["oneway"]


async def test_update_rejects_publishing_axis_another_axis_reads(road_graph_session):
    # 他の軸が読む内部軸を公開すると、利用者のルート設定画面へ内部軸が出る。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("base_axis", material="oneway"))
    await service.create(axis_definition("dependent_axis", material="base_axis"))

    with pytest.raises(AxisInternalAxisPublishError, match="公開できません"):
        await service.update("base_axis", axis_definition("base_axis", material="oneway", is_published=True))

    assert AXIS_DEFINITIONS["base_axis"].is_published is False


async def test_update_rejects_cycle_between_two_axes(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("axis_a", material="oneway"))
    await service.create(axis_definition("axis_b", material="axis_a"))

    with pytest.raises(AxisDependencyCycleError):
        await service.update("axis_a", axis_definition("axis_a", material="axis_b"))

    assert AXIS_DEFINITIONS["axis_a"].materials == ["oneway"]


async def test_update_replaces_definition_and_keeps_sort_order(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("test_axis", default_weight=0.1, material=CATALOG_MATERIAL))
    # sort_order維持の確認用ダミー（材料はtest_axisと衝突しないよう分ける）。
    await repository.upsert(axis_definition("second", material="poi_signal_per_km"), sort_order=99)
    await repository.commit()
    _, original_sort_order = (await repository.list_all_with_sort_order())["test_axis"]

    await service.update("test_axis", axis_definition("test_axis", default_weight=0.9, material=CATALOG_MATERIAL))

    assert AXIS_DEFINITIONS["test_axis"].default_weight == 0.9
    _, sort_order_after = (await repository.list_all_with_sort_order())["test_axis"]
    assert sort_order_after == original_sort_order


async def test_update_rejects_published_axis(road_graph_session):
    # 公開済み軸は不変。更新しようとしたpayload自体がis_published=False
    # （下書きへ戻そうとする値）でも、既存が公開済みなら拒否される（抜け道防止）。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("test_axis", default_weight=0.1, is_published=True, material=CATALOG_MATERIAL))

    with pytest.raises(AxisPublishedImmutableError, match="表示以外は変えられません"):
        await service.update(
            "test_axis", axis_definition("test_axis", default_weight=0.9, is_published=False, material=CATALOG_MATERIAL)
        )

    assert AXIS_DEFINITIONS["test_axis"].default_weight == 0.1


@pytest.mark.parametrize(
    "operation",
    [
        lambda service: service.update("unknown", axis_definition("unknown", material=CATALOG_MATERIAL)),
        lambda service: service.delete("unknown"),
        lambda service: service.unpublish("unknown"),
    ],
    ids=["update", "delete", "unpublish"],
)
async def test_an_operation_on_an_unknown_axis_raises_key_error(road_graph_session, operation):
    with pytest.raises(KeyError):
        await operation(AxisRegistryAdminService(AxisDefinitionRepository(road_graph_session)))


async def test_delete_rejects_removing_the_last_remaining_axis(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("test_axis", material=CATALOG_MATERIAL))

    with pytest.raises(ValueError, match="最後の1本の軸なので削除できません"):
        await service.delete("test_axis")

    assert "test_axis" in AXIS_DEFINITIONS  # 削除されず、キャッシュも変わっていない


async def test_delete_rejects_axis_another_axis_still_refers_to(road_graph_session):
    # 参照している軸を残して消すと、残った軸が存在しない軸を指し、次の起動の読み込みが止まる。
    # 参照している側を先に消せば、参照されていた軸も消せる。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("base_axis", material="oneway", label="路面"))
    await service.create(axis_definition("dependent_axis", material="base_axis", label="登り"))

    with pytest.raises(ValueError) as refusal:
        await service.delete("base_axis")

    # 画面の管理者が読む断り: 軸を表示名で名指し、次の手を添える（idは画面に出ない）。
    assert str(refusal.value) == (
        "「路面」は「登り」が組み合わせに使っているため削除できません。"
        "先に「登り」の組み合わせる軸から「路面」を外すか、「登り」を削除してください。"
    )

    assert (await repository.list_all_with_sort_order()).get("base_axis") is not None
    await refresh_axis_definitions(repository)  # 次の起動と同じ読み込みが通る

    await service.delete("dependent_axis")
    await service.create(axis_definition("other_axis", material=CATALOG_MATERIAL))
    await service.delete("base_axis")

    assert set(AXIS_DEFINITIONS) == {"other_axis"}


async def test_create_rejects_axis_the_startup_loading_would_reject(road_graph_session):
    # 管理APIの本文の検証を通らずにサービスへ来た軸も、確定する前に起動時の読み込みと同じ判定で止まる。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    with pytest.raises(ValueError, match="deleted_material"):
        await service.create(axis_definition("test_axis", material="deleted_material"))

    assert (await repository.list_all_with_sort_order()).get("test_axis") is None


# --- unpublish ---


async def test_unpublish_flips_published_axis_to_draft(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("test_axis", default_weight=0.3, is_published=True, material=CATALOG_MATERIAL))

    await service.unpublish("test_axis")

    assert AXIS_DEFINITIONS["test_axis"].is_published is False
    # is_published以外のフィールドは変わらないこと。
    assert AXIS_DEFINITIONS["test_axis"].default_weight == 0.3
    persisted, _ = (await repository.list_all_with_sort_order()).get("test_axis")
    assert persisted.is_published is False


async def test_unpublish_is_idempotent_for_already_draft_axis(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("test_axis", is_published=False, material=CATALOG_MATERIAL))

    await service.unpublish("test_axis")  # 例外にならないこと

    assert AXIS_DEFINITIONS["test_axis"].is_published is False


async def test_unpublish_then_delete_succeeds_where_direct_delete_was_rejected(road_graph_session):
    # 公開済み軸は直接削除できないが、unpublish→deleteの2段階なら削除できる。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(axis_definition("test_axis", is_published=True, material=CATALOG_MATERIAL))
    await service.create(axis_definition("other_axis", material="wind_drag_ratio"))

    with pytest.raises(AxisPublishedImmutableError):
        await service.delete("test_axis")

    await service.unpublish("test_axis")
    await service.delete("test_axis")

    assert "test_axis" not in AXIS_DEFINITIONS
