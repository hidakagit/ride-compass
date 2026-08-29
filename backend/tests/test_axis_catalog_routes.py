import pytest
from fastapi.testclient import TestClient

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.main import app

# 改善計画T350: 本番相当の14軸（実軸id前提のロジック用）はtests/conftest.pyのセッション
# スコープautouseフィクスチャが全テスト共通で用意する（tests/realistic_axis_fixtures.py参照）。

client = TestClient(app)


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
    # 改善計画T292: car_stress軸を支える内部軸（is_published=False）は一般公開しない
    # ため比較対象から除く（endpoint自体が既にis_published絞り込み済み、T271）。
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
    car_stress = entries_by_id["car_stress"]

    assert gradient["icon_id"] == "incline"
    assert gradient["chip_label"] == "勾配"
    # 改善計画T318: show_map_iconは既定Trueのため、明示的にfalseへ変更していない
    # 既存軸は全て地図上に表示される。
    assert gradient["show_map_icon"] is True
    assert car_stress["icon_id"] == "warning-triangle"
    assert car_stress["chip_label"] == "圧迫感"
    assert car_stress["panel_hint"] is not None
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

    # 改善計画T404: stop_densityはderive_ramp_inputsが自動導出したtile_inputsに
    # display_thresholds_override（軽量な色分けしきい値の上書き、tests/
    # realistic_axis_fixtures.py参照）を組み合わせる。
    stop_density_display = entries_by_id["stop_density"]["display"]
    assert stop_density_display["kind"] == "ramp"
    assert stop_density_display["thresholds"] == [1.0, 2.0, 4.0]

    # surface_qは手書きoverrideが無いためderive_ramp_inputsによる自動導出。
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
    assert set(entries_by_id["stop_density"]["primary_attribute_ids"]) == {"stop_poi", "intersection"}
    assert set(entries_by_id["night"]["primary_attribute_ids"]) == {"lit", "tunnel"}
    assert set(entries_by_id["accident"]["primary_attribute_ids"]) == {"accident_point"}
    # car_stress: AxisDefinition.materialsは内部軸id(car_stress_highway_base等)を返すため
    # 再帰的に解決する必要がある（domain/axis_definitions.py T292階層構造、
    # api/routers/axis_catalog.py: _primary_attribute_ids_for参照）。改善計画T353で
    # car_stress_bicycle_infra_adjustment内部軸を廃止したため、cycleway（自転車インフラ系
    # 材料由来）はcar_stressのprimary_attribute_idsから外れbicycle_infra_quality専用になった。
    assert set(entries_by_id["car_stress"]["primary_attribute_ids"]) == {
        "highway",
        "maxspeed",
        "lanes",
        "designation",
        "motor_vehicle_access",
    }


def test_get_axis_catalog_marks_accident_tile_input_as_needing_runtime_scale():
    # 改善計画T404: accidentは実行時スケール変換（収録年数での正規化）が必要な材料
    # （accident_count_per_km_year）を使うが、derive_ramp_inputsは自動導出の対象に
    # 含めるようになった。TileInputSpec.needs_runtime_scale=Trueで印を付け、実際の
    # スケール定数はmaterial_runtime_scales（レスポンス直下）で別途返す。
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
