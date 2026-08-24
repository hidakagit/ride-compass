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
    assert axis_ids == set(AXIS_DEFINITIONS.keys())


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
