from fastapi.testclient import TestClient

from app.api.dependencies import get_region_service
from app.domain.material_catalog import MATERIAL_CATALOG
from app.main import app

client = TestClient(app)


def test_get_material_catalog_requires_no_auth_and_returns_all_non_display_only_materials():
    # 改善計画T277: 読み取り専用・認可不要。改善計画T290でMATERIAL_CATALOGへ
    # 11材料（categorical 6件込み）を追加した後も、公開APIが全材料を漏れなく返すことを
    # 確認する（GET /api/material-catalog自体を検証する専用テストが従来無かった穴埋め）。
    # 改善計画T338: display_only=Trueの材料（designation）は公開レスポンスから除外される
    # ため、比較対象からも除く（test_designation_is_excluded_as_display_only参照）。
    response = client.get("/api/material-catalog")

    assert response.status_code == 200
    body = response.json()
    material_ids = {entry["material_id"] for entry in body["materials"]}
    expected_ids = {m.material_id for m in MATERIAL_CATALOG.values() if not m.display_only}
    assert material_ids == expected_ids


def test_designation_is_excluded_as_display_only():
    # 改善計画T338回帰テスト: designationは"both"が実データで35.01%と構造的に頻発する
    # AND条件（decisions/material-normalization-for-axis-composition.md参照）のため、
    # 軸スタジオの材料選択肢からは除外する（地図表示専用）。MATERIAL_CATALOGへの登録
    # 自体は維持する（is_known_materialはTrueのまま、地図表示のtile_property経由の
    # 参照にも影響しない）。
    response = client.get("/api/material-catalog")

    material_ids = {entry["material_id"] for entry in response.json()["materials"]}
    assert "designation" not in material_ids
    assert "designation" in MATERIAL_CATALOG
    assert MATERIAL_CATALOG["designation"].display_only is True


def test_is_emergency_transport_and_is_critical_logistics_are_selectable():
    # 改善計画T338フォローアップ（2026-08-26）: designationの正規化フラグ版は
    # designationと異なり軸スタジオの選択肢に現れる（display_only=False）。
    response = client.get("/api/material-catalog")

    entries_by_id = {entry["material_id"]: entry for entry in response.json()["materials"]}
    assert entries_by_id["is_emergency_transport"]["dtype"] == "boolean"
    assert entries_by_id["is_critical_logistics"]["dtype"] == "boolean"


def test_get_material_catalog_reflects_material_catalog_content():
    response = client.get("/api/material-catalog")

    entries_by_id = {entry["material_id"]: entry for entry in response.json()["materials"]}
    gradient_percent = entries_by_id["gradient_percent"]

    # 改善計画T345さらなるフォローアップ2: labelは「論理名 - 物理名」形式(full_label)。
    assert gradient_percent["label"] == MATERIAL_CATALOG["gradient_percent"].full_label()
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
    assert entries_by_id["smoothness"]["dtype"] == "categorical"


def test_get_material_catalog_includes_t290_numeric_and_boolean_materials():
    response = client.get("/api/material-catalog")

    entries_by_id = {entry["material_id"]: entry for entry in response.json()["materials"]}

    assert entries_by_id["bridge"]["dtype"] == "boolean"
    assert entries_by_id["motor_vehicle_no"]["dtype"] == "boolean"
    assert entries_by_id["oneway"]["dtype"] == "boolean"
    assert entries_by_id["maxspeed_kmh"]["dtype"] == "numeric"
    assert entries_by_id["lanes_count"]["dtype"] == "numeric"


def test_get_material_catalog_includes_description():
    # 改善計画T345: 軸スタジオの材料選択で情報アイコンから表示する説明文。全材料が
    # 空でない説明文を持つこと、レスポンスのdescriptionがMATERIAL_CATALOGの値と
    # 一致することを確認する。
    response = client.get("/api/material-catalog")

    entries = response.json()["materials"]
    assert len(entries) > 0
    for entry in entries:
        assert entry["description"] == MATERIAL_CATALOG[entry["material_id"]].description
        assert entry["description"].strip() != ""


def test_get_material_catalog_response_excludes_internal_tile_fields():
    # 改善計画T277: tile_property/tile_property_inverted/tile_property_needs_runtime_scaleは
    # backend内部（axis_display.py）専用で、公開レスポンスには含めない。
    response = client.get("/api/material-catalog")

    for entry in response.json()["materials"]:
        assert "tile_property" not in entry
        assert "tile_property_inverted" not in entry
        assert "tile_property_needs_runtime_scale" not in entry
        assert "display_only" not in entry


# --- 材料の実データ値一覧（改善計画T340） ---


class FakeRegionServiceForMaterialValues:
    def __init__(self, values: list[str] | None = None):
        self._values = values if values is not None else []
        self.last_material_id: str | None = None

    async def get_material_values(self, material_id: str) -> list[str]:
        self.last_material_id = material_id
        return self._values


def test_get_material_values_returns_sorted_distinct_values_from_service():
    fake = FakeRegionServiceForMaterialValues(values=["cycleway", "primary", "residential"])
    app.dependency_overrides[get_region_service] = lambda: fake

    try:
        response = client.get("/api/material-catalog/highway/values")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    # 改善計画T345フォローアップ: 値ごとに日本語ラベルも返す
    # （MaterialSpec.value_labels、地図の絞り込みUIのグルーピングとは独立の1値1ラベル）。
    # さらなるフォローアップ2: 「論理名 - 物理名」形式。
    assert response.json() == {
        "values": [
            {"value": "cycleway", "label": "自転車専用道 - cycleway"},
            {"value": "primary", "label": "主要幹線道路 - primary"},
            {"value": "residential", "label": "住宅街の道路 - residential"},
        ]
    }
    assert fake.last_material_id == "highway"


def test_get_material_values_unknown_material_id_is_404():
    response = client.get("/api/material-catalog/not_a_real_material/values")

    assert response.status_code == 404


def test_get_material_values_known_material_without_dynamic_support_returns_empty_list():
    # 改善計画T340: bicycle_infraのように事前に閉じた値集合を持つ既知の材料は404にせず、
    # 空リストを返す（フロント側は空リスト→自由テキスト入力へフォールバックする）。
    fake = FakeRegionServiceForMaterialValues(values=[])
    app.dependency_overrides[get_region_service] = lambda: fake

    try:
        response = client.get("/api/material-catalog/bicycle_infra/values")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"values": []}
    assert fake.last_material_id == "bicycle_infra"


def test_get_material_values_without_db_repository_returns_empty_list():
    # DB未接続構成（RegionService()、repository=None）を素通しで叩く既定のテスト環境
    # （このファイルのclientはdependency_overrides未設定）。
    response = client.get("/api/material-catalog/smoothness/values")

    assert response.status_code == 200
    assert response.json() == {"values": []}
