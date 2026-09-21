import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_region_service
from app.domain import tuning
from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.domain.tuning import TUNING_PARAMETERS, TuningEffect
from app.main import app
from app.services.region_service import RegionService

# 改善計画T350: 本番相当の14軸（実軸id前提のロジック用）はtests/conftest.pyのセッション
# スコープautouseフィクスチャが全テスト共通で用意する（tests/realistic_axis_fixtures.py参照）。

client = TestClient(app)


@pytest.fixture(autouse=True)
def region_service_without_repository():
    """このファイルの検証対象は軸カタログの内容で、DBの値は見ない。

    `/api/axis-catalog`は`material_runtime_scales`（事故の収録年数）を出すためだけに
    `RegionService`を経由する。実DBが繋がる環境ではリクエストごとに接続を開き、
    `TestClient`のイベントループをまたいだasyncpg接続がGCされる際にキャンセル用の
    コルーチンが未awaitのまま残る（`RuntimeWarning: coroutine 'Connection._cancel' was
    never awaited`）。repositoryを注入しない形へ固定して、DBの有無でこのファイルの
    経路が変わらないようにする。
    """
    app.dependency_overrides[get_region_service] = lambda: RegionService()
    yield
    app.dependency_overrides.pop(get_region_service, None)


@pytest.fixture
def draft_axis():
    # 改善計画T271: 下書き軸（is_published=False）が公開APIから漏れないことの検証用。
    # AXIS_DEFINITIONSはプロセス全体で共有されるため、他テストへ汚染が漏れないよう
    # 必ず復元する（test_axis_registry_service.pyのrestore_axis_definitionsと同じ方針）。
    AXIS_DEFINITIONS["draft_axis"] = AxisDefinition(
        axis_id="draft_axis",
        shape=BreakpointLinearShape(terms=[MaterialTerm(material="dummy")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
        default_weight=0.1,
        label="下書き軸",
        is_published=False,
    )
    yield
    del AXIS_DEFINITIONS["draft_axis"]


def test_get_axis_catalog_requires_no_auth_and_returns_builtin_axes():
    # 改善計画T269: 読み取り専用・認可不要（axis_adminとは異なりトークン無しでアクセスできる）。
    response = client.get("/api/axis-catalog")

    assert response.status_code == 200
    body = response.json()
    axis_ids = {entry["axis_id"] for entry in body["axes"]}
    # 内部軸（is_published=False）は一般公開しない。
    published_axis_ids = {axis_id for axis_id, d in AXIS_DEFINITIONS.items() if d.is_published}
    assert axis_ids == published_axis_ids


def test_get_axis_catalog_reflects_axis_definitions_content():
    response = client.get("/api/axis-catalog")

    body = response.json()
    entries_by_id = {entry["axis_id"]: entry for entry in body["axes"]}
    gradient = entries_by_id["gradient"]

    assert gradient["label"] == AXIS_DEFINITIONS["gradient"].label
    assert gradient["description"] == AXIS_DEFINITIONS["gradient"].description
    assert gradient["category"] == AXIS_DEFINITIONS["gradient"].category
    assert gradient["default_weight"] == AXIS_DEFINITIONS["gradient"].default_weight


def test_get_axis_catalog_reflects_display_fields():
    # 改善計画T310/T318: 地図チップ表示要素（icon_id/chip_label/panel_hint/
    # show_map_icon）が軸自身のデータ（AXIS_DEFINITIONS）からそのまま反映されること。
    response = client.get("/api/axis-catalog")

    body = response.json()
    entries_by_id = {entry["axis_id"]: entry for entry in body["axes"]}
    gradient = entries_by_id["gradient"]

    assert gradient["icon_id"] == "incline"
    assert gradient["chip_label"] == "勾配"
    # 改善計画T318: show_map_iconは既定Trueのため、明示的にfalseへ変更していない
    # 既存軸は全て地図上に表示される。
    assert gradient["show_map_icon"] is True
    # wind等、T310で値を持たない軸は素直にnull（未設定=フロント側の汎用フォールバック）。
    assert entries_by_id["wind"]["icon_id"] is None


def test_get_axis_catalog_excludes_draft_axes(draft_axis):
    # 改善計画T271完了条件: 下書き軸が一般向けAPIに漏れないこと。
    response = client.get("/api/axis-catalog")

    axis_ids = {entry["axis_id"] for entry in response.json()["axes"]}
    assert "draft_axis" not in axis_ids


def test_get_axis_catalog_includes_display_for_hand_written_and_auto_derived_axes():
    # 改善計画T308: displayフィールドが軸ごとに含まれ、is_published切替が即座に
    # （axis-catalog.jsonの再生成・フロント再デプロイなしに）反映されることの土台。
    response = client.get("/api/axis-catalog")

    body = response.json()
    entries_by_id = {entry["axis_id"]: entry for entry in body["axes"]}

    stop_density_display = entries_by_id["stop_density"]["display"]
    assert stop_density_display["kind"] == "ramp"
    # 末尾が落ちるのは折れ線が飽和した先の境界だから。
    assert stop_density_display["thresholds"] == [2.0, 4.0, 7.0]

    # surface_qは上書きが無いので導出した値をそのまま使う。
    surface_q_display = entries_by_id["surface_q"]["display"]
    assert surface_q_display["kind"] == "ramp"
    assert surface_q_display["tile_inputs"][0]["property"] == "surface_good"

    # gradientはどちらの経路でも導出できないためkind="none"。
    assert entries_by_id["gradient"]["display"]["kind"] == "none"


def test_get_axis_catalog_display_reflects_gui_created_published_axis():
    # 改善計画T308の完了条件そのもの: 軸スタジオが公開した軸（複数材料の重み付き結合、
    # 手書きoverrideテーブルに含まれない）が、コード変更・再デプロイなしにramp表示を持つ。
    AXIS_DEFINITIONS["gui_published_axis"] = AxisDefinition(
        axis_id="gui_published_axis",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="lanes_count", weight=1.0)],
            breakpoints=[(0.0, 0.0), (10.0, 100.0)],
        ),
        default_weight=0.1,
        label="GUI公開軸テスト",
        is_published=True,
    )
    try:
        response = client.get("/api/axis-catalog")
        entries_by_id = {entry["axis_id"]: entry for entry in response.json()["axes"]}
        display = entries_by_id["gui_published_axis"]["display"]
        assert display["kind"] == "ramp"
        assert len(display["tile_inputs"]) == 1
        assert display["tile_inputs"][0]["property"] == "lanes_count"
        assert display["tile_inputs"][0]["weight"] == 1.0
        assert display["thresholds"] == [10.0]
        # 改善計画T308: lanes_count材料はprimary_attribute_id="lanes"へ解決される
        # （material_catalog.py参照）。
        assert entries_by_id["gui_published_axis"]["primary_attribute_ids"] == ["lanes"]
    finally:
        del AXIS_DEFINITIONS["gui_published_axis"]


def test_get_axis_catalog_primary_attribute_ids_match_legacy_static_inputs():
    # 改善計画T308: primary_attribute_idsは、以前ビルド時静的生成物
    # （registry_defaults.py: AxisSpec.inputs、export_openapi.py経由でaxis-catalog.jsonへ
    # 書き出されていた値）が持っていたのと同じ一次属性id集合を実行時に再現できることの
    # 回帰確認（既存7軸ぶん、順序は問わない）。
    response = client.get("/api/axis-catalog")
    entries_by_id = {entry["axis_id"]: entry for entry in response.json()["axes"]}

    assert set(entries_by_id["gradient"]["primary_attribute_ids"]) == {"elevation"}
    assert set(entries_by_id["surface_q"]["primary_attribute_ids"]) == {"surface"}
    # 交差点密度はT655で停止密度の材料から外れた（docs/records/tasks/T655.md「交差点密度の扱い」）。
    assert set(entries_by_id["stop_density"]["primary_attribute_ids"]) == {"stop_poi"}
    assert set(entries_by_id["night"]["primary_attribute_ids"]) == {"lit", "tunnel"}
    assert set(entries_by_id["accident"]["primary_attribute_ids"]) == {"accident_point"}


def test_get_axis_catalog_marks_accident_tile_input_as_needing_runtime_scale():
    # 実行時スケールが要る材料は印だけ付け、係数はmaterial_runtime_scalesで別途返す。
    response = client.get("/api/axis-catalog")
    body = response.json()
    entries_by_id = {entry["axis_id"]: entry for entry in body["axes"]}

    accident_tile_inputs = entries_by_id["accident"]["display"]["tile_inputs"]
    assert len(accident_tile_inputs) == 1
    assert accident_tile_inputs[0]["property"] == "accident_per_km"
    assert accident_tile_inputs[0]["needs_runtime_scale"] is True

    # material_runtime_scalesは常にレスポンスへ含まれる（テスト環境はroad_graph_use_
    # repository=Falseのためrepository未注入、RegionService.get_accident_years_coveredが
    # 0を返し、0除算を避けてキー自体を含めない安全側の挙動になる——本番相当のDB接続時の
    # 挙動はtest_region_service.pyのget_accident_years_covered系テスト参照）。
    assert "material_runtime_scales" in body
    assert isinstance(body["material_runtime_scales"], dict)


def test_get_axis_catalog_carries_the_calibration_values_the_client_needs(monkeypatch):
    """フロントが使う較正値は、このカタログが**いま効いている値**で運ぶ。

    ビルド時生成物（route-generate-config.json）だけで配ると、管理画面から変えても
    次のデプロイまで画面に届かない。運ぶ対象は宣言（効き方がCLIENT_RELOAD）から導く。
    """
    expected = {
        p.id for p in TUNING_PARAMETERS if p.effect is TuningEffect.CLIENT_RELOAD
    }
    assert expected, "画面へ配る較正値が宣言に1件も無い"
    param_id = sorted(expected)[0]
    monkeypatch.setitem(tuning.TUNING_VALUES, param_id, 9.5)

    body = client.get("/api/axis-catalog").json()

    assert set(body["client_tuning"]) == expected
    assert body["client_tuning"][param_id] == 9.5


def test_get_axis_catalog_includes_map_value_kind_and_unit():
    # 地図の色分けがルート前後で同じスケールを使うための宣言（domain/dynamic_way_values.py:
    # map_value_kind/map_value_unit）。勾配だけが符号付き材料（%）、他は難易度（無次元）。
    response = client.get("/api/axis-catalog")
    entries_by_id = {entry["axis_id"]: entry for entry in response.json()["axes"]}
    assert entries_by_id["gradient"]["map_value_kind"] == "signed_material"
    assert entries_by_id["gradient"]["map_value_unit"] == "%"
    assert entries_by_id["wind"]["map_value_kind"] == "difficulty"
    assert entries_by_id["wind"]["map_value_unit"] == ""


def test_get_axis_catalog_includes_raw_value_unit():
    # 得点の隣へ生値を出すための単位（domain/axis_raw_value.py: raw_value_unit）。
    # 勾配は単一材料をそのまま使うので%、内部軸を合成する軸は単位が定まらずnull。
    response = client.get("/api/axis-catalog")
    entries_by_id = {entry["axis_id"]: entry for entry in response.json()["axes"]}
    assert entries_by_id["gradient"]["raw_value_unit"] == "%"
    # 停止密度は材料ごとに重みを変えて足す（交差点は0.3倍）ため、和は「回/km」では
    # 読めない——生値の単位はnullになる。
    assert entries_by_id["stop_density"]["raw_value_unit"] is None


def test_get_axis_catalog_includes_material_breakdown():
    # 単位が定まらない軸は、材料まで分解した内訳を持つ（得点だけでは軸単体で判断できない、
    # docs/records/tasks/T689.md）。並びは正規化重みの降順で、フロントは並べ替えを持たない。
    response = client.get("/api/axis-catalog")

    entries_by_id = {entry["axis_id"]: entry for entry in response.json()["axes"]}
    # 単位が定まる軸は分解しない（軸単位の生値で足りる）。
    assert entries_by_id["gradient"]["material_breakdown"] == []
    night = entries_by_id["night"]["material_breakdown"]
    assert [entry["material_id"] for entry in night] == ["lit", "has_tunnel"]
    assert [entry["dtype"] for entry in night] == ["boolean", "boolean"]
    assert [entry["share"] for entry in night] == [0.5, 0.5]
    # 材料の表示名・単位はbackendが返す（フロントは対応表を持たない）。
    lit = next(entry for entry in night if entry["material_id"] == "lit")
    assert lit["label"]
    # 真偽値材料に対訳は要らない（走行中に見る画面へ不要なデータを載せない）。
    assert lit["value_labels"] == {}


def test_タイル世代はDBの派生データ世代を前置きして配る():
    """フロントはこの世代でブラウザのキャッシュを分ける。

    世代を読む経路はルート生成の材料取得のため、**カタログ側が自分で読み直しを促さないと**
    「まだ誰も読んでいない」印（`x-`）のまま配ってしまう（起動直後に取られるのがこの
    エンドポイントであるため、実際にそうなった）。
    """
    from app.services import derived_data_revision_service

    class RepositoryWithRevision:
        async def get_derived_data_revision(self):
            return 42

    derived_data_revision_service.reset_for_tests()
    app.dependency_overrides[get_region_service] = lambda: RegionService(
        repository=RepositoryWithRevision()
    )
    try:
        versions = client.get("/api/axis-catalog").json()["tile_versions"]
    finally:
        app.dependency_overrides[get_region_service] = lambda: RegionService()
        derived_data_revision_service.reset_for_tests()

    assert versions, "タイル世代が配られていない"
    for name, version in versions.items():
        assert version.startswith("42-"), f"{name}がDBの世代を前置きしていない: {version}"
