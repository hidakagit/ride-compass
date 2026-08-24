from fastapi.testclient import TestClient

from app.domain.material_catalog import MATERIAL_CATALOG
from app.main import app

client = TestClient(app)


def test_get_material_catalog_requires_no_auth_and_returns_all_materials():
    # 改善計画T277: 読み取り専用・認可不要。改善計画T290でMATERIAL_CATALOGへ
    # 11材料（categorical 6件込み）を追加した後も、公開APIが全材料を漏れなく返すことを
    # 確認する（GET /api/material-catalog自体を検証する専用テストが従来無かった穴埋め）。
    response = client.get("/api/material-catalog")

    assert response.status_code == 200
    body = response.json()
    material_ids = {entry["material_id"] for entry in body["materials"]}
    assert material_ids == set(MATERIAL_CATALOG.keys())


def test_get_material_catalog_reflects_material_catalog_content():
    response = client.get("/api/material-catalog")

    entries_by_id = {entry["material_id"]: entry for entry in response.json()["materials"]}
    gradient_percent = entries_by_id["gradient_percent"]

    assert gradient_percent["label"] == MATERIAL_CATALOG["gradient_percent"].label
    assert gradient_percent["dtype"] == "numeric"


def test_get_material_catalog_includes_categorical_dtype():
    # 改善計画T290: dtype="categorical"の材料（highway等）が公開APIレスポンスへ
    # 正しく含まれることを確認する（MaterialCatalogEntry.dtypeがMaterialDType型を
    # そのままimportしているため、Literal拡張が自動反映される設計）。
    response = client.get("/api/material-catalog")

    entries_by_id = {entry["material_id"]: entry for entry in response.json()["materials"]}

    assert entries_by_id["highway"]["dtype"] == "categorical"
    assert entries_by_id["surface"]["dtype"] == "categorical"
    assert entries_by_id["bicycle_infra"]["dtype"] == "categorical"
    assert entries_by_id["cycleway_class"]["dtype"] == "categorical"
    assert entries_by_id["designation"]["dtype"] == "categorical"
    assert entries_by_id["smoothness"]["dtype"] == "categorical"


def test_get_material_catalog_includes_t290_numeric_and_boolean_materials():
    response = client.get("/api/material-catalog")

    entries_by_id = {entry["material_id"]: entry for entry in response.json()["materials"]}

    assert entries_by_id["bridge"]["dtype"] == "boolean"
    assert entries_by_id["motor_vehicle_no"]["dtype"] == "boolean"
    assert entries_by_id["oneway"]["dtype"] == "boolean"
    assert entries_by_id["maxspeed_kmh"]["dtype"] == "numeric"
    assert entries_by_id["lanes_count"]["dtype"] == "numeric"


def test_get_material_catalog_response_excludes_internal_tile_fields():
    # 改善計画T277: tile_property/tile_property_inverted/tile_property_needs_runtime_scaleは
    # backend内部（axis_display.py）専用で、公開レスポンスには含めない。
    response = client.get("/api/material-catalog")

    for entry in response.json()["materials"]:
        assert "tile_property" not in entry
        assert "tile_property_inverted" not in entry
        assert "tile_property_needs_runtime_scale" not in entry
