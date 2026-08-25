import pytest
from fastapi.testclient import TestClient

from app.domain.axis_definitions import AXIS_DEFINITIONS, AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.main import app

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

    # stop_densityは手書きoverride（axis_display.py: STOP_DENSITY_DISPLAY）を優先する。
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
    # api/routers/axis_catalog.py: _primary_attribute_ids_for参照）。
    assert set(entries_by_id["car_stress"]["primary_attribute_ids"]) == {
        "highway",
        "cycleway",
        "maxspeed",
        "lanes",
        "designation",
        "motor_vehicle_access",
    }
