import logging

import numpy as np
import pytest

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    AxisDefinition,
    AxisDependencyCycleError,
    AxisInternalAxisPublishError,
    AxisMaterialConflictError,
    AxisPublishedImmutableError,
    BreakpointLinearShape,
    MaterialTerm,
)
from app.domain.evaluation import StaticEdgeScoreMatrix
from app.infrastructure import tile_score_matrix_cache
from app.infrastructure.axis_definition_models import AxisRegistryMetaRow
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository
from app.services import axis_registry_service
from app.services.axis_registry_service import (
    AxisDefinitionSyncError,
    AxisRegistryAdminService,
    refresh_axis_definitions,
)
from tests.realistic_axis_fixtures import axis_definitions_snapshot

pytestmark = [
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.xdist_group(name="postgis"),
    pytest.mark.postgis,
]


@pytest.fixture(autouse=True)
def restore_axis_definitions():
    # refresh_axis_definitionsはグローバルなAXIS_DEFINITIONS（プロセス全体で共有）をin-place
    # 更新するため、他のテストファイルへ汚染が漏れないよう必ずスナップショット・復元する
    # （services/axis_registry_service.pyのdocstring参照）。改善計画T350のcode-review対応:
    # スナップショット/復元の仕組み自体はtests/realistic_axis_fixtures.py:
    # axis_definitions_snapshot()へ集約済み（3重実装を解消）。
    with axis_definitions_snapshot():
        yield


def _definition(
    axis_id: str = "test_axis",
    default_weight: float = 0.1,
    # 改善計画T295: refresh_axis_definitionsが未知の材料参照を検出しフォールバックする
    # ようになったため、既定材料は`MATERIAL_CATALOG`に実在するもの（gradient_percent）に
    # しておく（以前の"dummy"のままだと、大半のテストがrefresh呼び出しのたびに
    # フォールバックし、AXIS_DEFINITIONSへ反映されず失敗する）。
    material: str = "gradient_percent",
    is_published: bool = False,
) -> AxisDefinition:
    return AxisDefinition(
        axis_id=axis_id,
        shape=BreakpointLinearShape(terms=[MaterialTerm(material=material)], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=default_weight,
        label=f"テスト軸[{axis_id}]",
        description="テスト用ダミー軸",
        category="推定",
        is_published=is_published,
    )


# --- refresh_axis_definitions（起動時ロード相当） ---


async def test_refresh_raises_when_table_empty(road_graph_session):
    # 改善計画T349: 以前はコード内蔵の既定値へ安全側フォールバックしていたが、
    # fail-fastへ変更した（AXIS_DEFINITIONSは変更されないまま例外が送出される）。
    original = dict(AXIS_DEFINITIONS)
    repository = AxisDefinitionRepository(road_graph_session)

    with pytest.raises(AxisDefinitionSyncError, match="空です"):
        await refresh_axis_definitions(repository)

    assert AXIS_DEFINITIONS == original


async def test_refresh_replaces_axis_definitions_with_db_content(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("test_axis"), sort_order=0)
    await repository.commit()

    await refresh_axis_definitions(repository)

    assert set(AXIS_DEFINITIONS.keys()) == {"test_axis"}


async def test_refresh_clears_tile_score_matrix_cache(road_graph_session):
    # 改善計画T536（旧T534のaxis_score_cacheを置き換え）: タイル単位の静的Edge×公開軸
    # スコア行列キャッシュ（tile_score_matrix_cache）はAXIS_DEFINITIONSと同じタイミングで
    # クリアされる必要がある——古いままだと軸編集後も編集前のスコアを返し続けてしまう
    # （infrastructure/tile_score_matrix_cache.pyのdocstring参照）。
    dummy_matrix = StaticEdgeScoreMatrix(
        edge_ids=["edge-1"],
        axis_ids=["gradient"],
        axis_scores=np.array([[50.0]]),
        distance_m=np.array([100.0]),
        bearing_deg=np.array([np.nan]),
        is_motorway=np.array([False]),
        is_trunk=np.array([False]),
        no_bicycle=np.array([False]),
        gradient_percent=np.array([np.nan]),
    )
    tile_score_matrix_cache.set(12, 1, 1, dummy_matrix)
    assert tile_score_matrix_cache.get(12, 1, 1) is not None

    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("test_axis"), sort_order=0)
    await repository.commit()

    await refresh_axis_definitions(repository)

    assert tile_score_matrix_cache.get(12, 1, 1) is None


async def test_refresh_raises_on_repository_error(road_graph_session):
    # 改善計画T349: DB接続自体が失敗した場合もfail-fast（AxisDefinitionSyncErrorへラップして再送出）。
    original = dict(AXIS_DEFINITIONS)

    class _BrokenRepository:
        async def list_all(self):
            raise RuntimeError("boom")

    with pytest.raises(AxisDefinitionSyncError, match="軸定義のDB読み込みに失敗"):
        await refresh_axis_definitions(_BrokenRepository())

    assert AXIS_DEFINITIONS == original


async def test_refresh_raises_when_axis_references_unknown_material(road_graph_session):
    # 改善計画T294/T295の教訓（DBの行は読めるが、削除済み材料idを参照する「半端に古い」
    # 状態）の再現。AxisRegistryAdminService.createは材料の実在チェックを行わない
    # （そのチェックはAPI層のAxisDefinitionPayloadのみが持つ）ため、ここでは
    # repositoryへ直接、未知の材料を参照する軸を書き込む形で「半端に古いDB」を再現する。
    # 改善計画T349: 検出時は以前のフォールバックではなくfail-fastする。
    original = dict(AXIS_DEFINITIONS)
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("test_axis", material="deleted_material"), sort_order=0)
    await repository.commit()

    with pytest.raises(AxisDefinitionSyncError, match="deleted_material") as exc_info:
        await refresh_axis_definitions(repository)

    assert "未知の材料/軸参照を検出しました" in str(exc_info.value)
    assert AXIS_DEFINITIONS == original


async def test_refresh_allows_axis_referencing_another_axis_in_same_batch(road_graph_session):
    # 改善計画T295: 軸id参照（改善計画T292の階層構造）は「未知の材料」ではないため、
    # 参照先の軸が同じDB読み込み結果に含まれていれば正常に読み込まれる（誤検知しない）。
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("base_axis", material="oneway"), sort_order=0)
    await repository.upsert(_definition("dependent_axis", material="base_axis"), sort_order=1)
    await repository.commit()

    await refresh_axis_definitions(repository)

    assert set(AXIS_DEFINITIONS) == {"base_axis", "dependent_axis"}


async def test_refresh_logs_axis_count(road_graph_session, caplog):
    # 改善計画T350: AXIS_DEFINITIONSのPython literal撤去に伴い、コード内蔵axis_id集合との
    # 差分ログ（_CODE_BUILTIN_AXIS_IDS、改善計画T295）は撤去した——DBが唯一の正本になった
    # ため「コード側にだけある/DB側にだけある」という差分の概念自体が意味を失う
    # （AXIS_DEFINITIONSは常に空スタートのため、この差分は常に全件db_onlyになるだけ）。
    # 読み込み件数のINFOログのみ残る。
    caplog.set_level(logging.INFO, logger="ridecompass.axis_registry")
    repository = AxisDefinitionRepository(road_graph_session)
    await repository.upsert(_definition("test_axis"), sort_order=0)
    await repository.commit()

    await refresh_axis_definitions(repository)

    assert "axes=1" in caplog.text


# --- AxisRegistryAdminService（管理APIのユースケース層） ---


async def test_create_persists_and_refreshes_process_cache(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    await service.create(_definition("test_axis"))

    assert "test_axis" in AXIS_DEFINITIONS
    assert (await repository.list_all())["test_axis"] == _definition("test_axis")


async def test_create_rejects_axis_id_colliding_with_known_material(road_graph_session):
    # 改善計画T296: MATERIAL_CATALOGに実在する材料id（例: "highway"）と同名のaxis_idは
    # 作成できない。放置すると評価時に生の材料値がdifficulty値で上書きされ、それ以降に
    # 評価される軸が黙って壊れる（axis_definitions.py: evaluate_axes_scalar参照）。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    with pytest.raises(ValueError, match="highway"):
        await service.create(_definition("highway", material="wind_penalty"))

    assert "highway" not in AXIS_DEFINITIONS


async def test_create_rejects_duplicate_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis"))

    with pytest.raises(ValueError, match="既に存在します"):
        await service.create(_definition("test_axis"))


async def test_create_rejects_axis_reusing_existing_material(road_graph_session):
    # 改善計画T268: 材料の排他帰属チェック。既存軸が使用中の材料を参照する新軸の
    # 登録は管理APIレベル（サービス層）で拒否される。改善計画T292: 排他チェックは
    # MATERIAL_CATALOGに実在する材料だけを対象にする（軸参照との区別のため）ので、
    # ここではMATERIAL_CATALOGに実在するが既存7軸には未使用の材料（"bridge"）を使う。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("first_axis", material="bridge"))

    with pytest.raises(AxisMaterialConflictError, match="bridge"):
        await service.create(_definition("second_axis", material="bridge"))

    assert "second_axis" not in AXIS_DEFINITIONS


async def test_update_allows_keeping_own_materials(road_graph_session):
    # 更新時、材料構成を変えなければ自分自身との衝突にはならない。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis", default_weight=0.1, material="wind_penalty"))

    await service.update("test_axis", _definition("test_axis", default_weight=0.5, material="wind_penalty"))

    assert AXIS_DEFINITIONS["test_axis"].default_weight == 0.5


async def test_update_rejects_axis_reusing_another_axis_material(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("first_axis", material="motor_vehicle_no"))
    await service.create(_definition("second_axis", material="oneway"))

    with pytest.raises(AxisMaterialConflictError, match="motor_vehicle_no"):
        await service.update("second_axis", _definition("second_axis", material="motor_vehicle_no"))

    assert AXIS_DEFINITIONS["second_axis"].materials == ["oneway"]


async def test_create_allows_axis_referencing_another_axis(road_graph_session):
    # 改善計画T292: 軸間参照（内部軸→公開軸の階層構造）。既存軸のaxis_idをmaterialとして
    # 参照する新規軸の作成は、材料の排他チェック・循環検証のどちらにも引っかからず
    # 正常に作成できる。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("base_axis", material="oneway"))

    await service.create(_definition("dependent_axis", material="base_axis"))

    assert "dependent_axis" in AXIS_DEFINITIONS
    assert AXIS_DEFINITIONS["dependent_axis"].materials == ["base_axis"]


async def test_create_rejects_publishing_axis_referenced_by_another_axis(road_graph_session):
    # T311フォローアップ回帰テスト: 軸スタジオの操作ミスでcar_stress内部軸のような
    # 「他の軸から参照される内部軸」がis_published=Trueのまま保存され、一般ユーザー向け
    # ルート設定画面へ漏れ出た実障害を受けたガード。既にdependent_axisがbase_axisを
    # 参照している状態で、base_axis自身を公開しようとすると拒否される。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("base_axis", material="oneway"))
    await service.create(_definition("dependent_axis", material="base_axis"))

    with pytest.raises(AxisInternalAxisPublishError, match="base_axis"):
        await service.update("base_axis", _definition("base_axis", material="oneway", is_published=True))

    assert AXIS_DEFINITIONS["base_axis"].is_published is False


async def test_create_allows_publishing_axis_with_no_dependents(road_graph_session):
    # 上のテストと対になる確認: 誰からも参照されていない軸は公開してよい（過検出しない）。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("standalone_axis", material="oneway"))

    await service.update("standalone_axis", _definition("standalone_axis", material="oneway", is_published=True))

    assert AXIS_DEFINITIONS["standalone_axis"].is_published is True


async def test_create_rejects_direct_cycle_between_two_axes(road_graph_session):
    # 改善計画T292: axis_a→axis_bの参照が既に存在する状態でaxis_b→axis_aを作ろうとすると
    # （2軸間の循環）、AxisDependencyCycleErrorで拒否される。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("axis_a", material="oneway"))
    await service.create(_definition("axis_b", material="axis_a"))

    with pytest.raises(AxisDependencyCycleError):
        await service.update("axis_a", _definition("axis_a", material="axis_b"))

    # 循環が拒否された結果、axis_aは元の材料参照のまま変わっていないこと。
    assert AXIS_DEFINITIONS["axis_a"].materials == ["oneway"]


async def test_create_rejects_self_referencing_axis(road_graph_session):
    # 改善計画T292: 軸が自分自身のaxis_idを材料として参照する（自己循環）ケースも
    # AxisDependencyCycleErrorで拒否される。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("first_axis", material="oneway"))

    with pytest.raises(AxisDependencyCycleError):
        await service.update("first_axis", _definition("first_axis", material="first_axis"))


async def test_update_replaces_definition_and_keeps_sort_order(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis", default_weight=0.1))
    # sort_order維持の確認用ダミー（材料はtest_axisと衝突しないよう分ける、改善計画T268）。
    await repository.upsert(_definition("second", material="stop_count_per_km"), sort_order=99)
    await repository.commit()
    _, original_sort_order = await repository.get("test_axis")

    await service.update("test_axis", _definition("test_axis", default_weight=0.9))

    assert AXIS_DEFINITIONS["test_axis"].default_weight == 0.9
    _, sort_order_after = await repository.get("test_axis")
    assert sort_order_after == original_sort_order


async def test_update_rejects_published_axis(road_graph_session):
    # 改善計画T271: 公開済み軸は不変。更新しようとしたpayload自体がis_published=False
    # （下書きへ戻そうとする値）でも、既存が公開済みなら拒否される（抜け道防止）。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis", is_published=True))

    with pytest.raises(AxisPublishedImmutableError, match="test_axis"):
        await service.update("test_axis", _definition("test_axis", default_weight=0.9, is_published=False))

    assert AXIS_DEFINITIONS["test_axis"].default_weight == 0.1


async def test_update_allows_draft_axis(road_graph_session):
    # 下書き（is_published=False）は自由に更新できる（既存のtest_update_*群と同じ挙動の
    # 再確認、T271の不変制約が下書きには効かないことを明示する）。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis", is_published=False))

    await service.update("test_axis", _definition("test_axis", default_weight=0.9, is_published=False))

    assert AXIS_DEFINITIONS["test_axis"].default_weight == 0.9


async def test_delete_rejects_published_axis(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis", is_published=True))
    await service.create(_definition("other_axis", material="wind_penalty"))

    with pytest.raises(AxisPublishedImmutableError, match="test_axis"):
        await service.delete("test_axis")

    assert "test_axis" in AXIS_DEFINITIONS


async def test_update_raises_key_error_for_unknown_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    with pytest.raises(KeyError):
        await service.update("unknown", _definition("unknown"))


async def test_delete_removes_definition_and_refreshes_process_cache(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis"))
    # 最後の1軸削除ガードに引っかからないための2軸目（材料は衝突しないよう分ける、改善計画T268）。
    await service.create(_definition("other_axis", material="stop_count_per_km"))

    await service.delete("test_axis")

    assert "test_axis" not in AXIS_DEFINITIONS
    assert await repository.get("test_axis") is None


async def test_delete_raises_key_error_for_unknown_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    with pytest.raises(KeyError):
        await service.delete("unknown")


async def test_delete_rejects_axis_id_in_code_coupled_set_even_when_draft(road_graph_session, monkeypatch):
    # 改善計画T350: `_CODE_COUPLED_AXIS_IDS`に含まれるaxis_idは、is_published=False
    # （下書き）でも削除できない。改善計画T458で最後の実在該当軸（gradient）が
    # 宣言的フィールドへの汎用化により対象から外れ現在は空集合のため（下記
    # test_delete_allows_axis_id_after_t352_generalization参照）、安全弁の機構自体を
    # 実在しない架空のaxis_idでmonkeypatchして検証する（改善計画T358の「全件
    # parametrize」の後継、実在軸に依存しない回帰テスト）。
    monkeypatch.setattr(axis_registry_service, "_CODE_COUPLED_AXIS_IDS", frozenset({"fake_coupled_axis"}))
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("fake_coupled_axis", is_published=False))
    await service.create(_definition("other_axis", material="wind_penalty"))

    with pytest.raises(ValueError, match="fake_coupled_axis"):
        await service.delete("fake_coupled_axis")

    assert "fake_coupled_axis" in AXIS_DEFINITIONS


async def test_delete_rejects_axis_id_in_code_coupled_set_after_unpublish(road_graph_session, monkeypatch):
    # 改善計画T350: unpublish→deleteの2段階（T302で正式フローとして許容された経路）でも
    # コード結合axis_idは削除できない。
    monkeypatch.setattr(axis_registry_service, "_CODE_COUPLED_AXIS_IDS", frozenset({"fake_coupled_axis"}))
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("fake_coupled_axis", is_published=True))
    await service.create(_definition("other_axis", material="wind_penalty"))
    await service.unpublish("fake_coupled_axis")

    with pytest.raises(ValueError, match="fake_coupled_axis"):
        await service.delete("fake_coupled_axis")

    assert "fake_coupled_axis" in AXIS_DEFINITIONS


@pytest.mark.parametrize("axis_id", ["night", "wind", "car_stress", "gradient"])
async def test_delete_allows_axis_id_after_t352_generalization(road_graph_session, axis_id):
    # 改善計画T352: night（time_scope="night_only"）・wind（supports_route_coloring=True）は
    # 以前`_CODE_COUPLED_AXIS_IDS`に含まれ削除禁止だったが、road_graph_engine.pyの
    # T173ロジック・frontend routeStyleModes.tsのハードコードをそれぞれ宣言的フィールドへ
    # 汎用化したことで、axis_idの直接ハードコードが解消された。改善計画T459: car_stressも
    # 同様に、`car_stress_display_level()`（末端消費者ゼロの生値フィールド専用だった）を
    # 撤去したことでハードコードが解消された。改善計画T458: gradientも同様に、
    # `DYNAMIC_WAY_VALUE_MATERIALS`ハードコード辞書を`AXIS_DEFINITIONS`由来の動的導出へ
    # 置き換えたことでハードコードが解消された。削除できる（コード結合が無いことの回帰テスト）。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition(axis_id, is_published=False))
    await service.create(_definition("other_axis", material="wind_penalty"))

    await service.delete(axis_id)

    assert axis_id not in AXIS_DEFINITIONS


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


# --- unpublish（改善計画T302） ---


async def test_unpublish_flips_published_axis_to_draft(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis", default_weight=0.3, is_published=True))

    await service.unpublish("test_axis")

    assert AXIS_DEFINITIONS["test_axis"].is_published is False
    # is_published以外のフィールドは変わらないこと。
    assert AXIS_DEFINITIONS["test_axis"].default_weight == 0.3
    persisted, _ = await repository.get("test_axis")
    assert persisted.is_published is False


async def test_unpublish_allows_update_afterwards(road_graph_session):
    # 下書きへ戻った後は通常のupdate()経路で自由に再編集・再公開できる
    # （複製ではなく同一axis_idのまま行き来する）。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis", default_weight=0.3, is_published=True))
    await service.unpublish("test_axis")

    await service.update("test_axis", _definition("test_axis", default_weight=0.9, is_published=True))

    assert AXIS_DEFINITIONS["test_axis"].default_weight == 0.9
    assert AXIS_DEFINITIONS["test_axis"].is_published is True


async def test_unpublish_is_idempotent_for_already_draft_axis(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis", is_published=False))

    await service.unpublish("test_axis")  # 例外にならないこと

    assert AXIS_DEFINITIONS["test_axis"].is_published is False


async def test_unpublish_raises_key_error_for_unknown_axis_id(road_graph_session):
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)

    with pytest.raises(KeyError):
        await service.unpublish("unknown")


async def test_unpublish_then_delete_succeeds_where_direct_delete_was_rejected(road_graph_session):
    # T271のガード単体では公開済み軸を削除できないが、unpublish→deleteの2段階なら
    # 削除できる（改善計画T302で正式フローとして決定）。
    repository = AxisDefinitionRepository(road_graph_session)
    service = AxisRegistryAdminService(repository)
    await service.create(_definition("test_axis", is_published=True))
    await service.create(_definition("other_axis", material="wind_penalty"))

    with pytest.raises(AxisPublishedImmutableError):
        await service.delete("test_axis")

    await service.unpublish("test_axis")
    await service.delete("test_axis")

    assert "test_axis" not in AXIS_DEFINITIONS
