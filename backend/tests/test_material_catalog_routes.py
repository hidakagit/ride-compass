import base64
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.api.dependencies import get_material_coverage_service, get_region_service
from app.config import settings
from app.domain.material_catalog import MATERIAL_CATALOG
from app.infrastructure.material_coverage import MATERIAL_COVERAGE_SPECS, MaterialCoverageCounts
from app.main import app
from app.services.material_coverage_service import build_material_coverage_report
from app.services.region_service import RegionService

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
    assert entries_by_id["tracktype"]["dtype"] == "categorical"
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


def test_get_material_catalog_includes_reference_points():
    # 軸スタジオの折れ点編集を助ける「値の目安」一覧。値を持つ材料（wind_drag_ratio）は
    # 非空、値を持たない材料（lit等）は空配列で返る。
    response = client.get("/api/material-catalog")

    entries_by_id = {entry["material_id"]: entry for entry in response.json()["materials"]}

    wind = entries_by_id["wind_drag_ratio"]
    assert len(wind["reference_points"]) > 0
    assert wind["reference_points"][0].keys() == {"label", "value"}
    assert [p.value for p in MATERIAL_CATALOG["wind_drag_ratio"].reference_points] == [
        entry["value"] for entry in wind["reference_points"]
    ]

    assert entries_by_id["lit"]["reference_points"] == []


def test_get_material_catalog_response_excludes_internal_tile_fields():
    # 改善計画T277: tile_property/tile_property_needs_runtime_scaleは
    # backend内部（axis_display.py）専用で、公開レスポンスには含めない。
    response = client.get("/api/material-catalog")

    for entry in response.json()["materials"]:
        assert "tile_property" not in entry
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
    # 改善計画T340: tracktypeのように事前に閉じた値集合を持つ既知の材料は404にせず、
    # 空リストを返す（フロント側は空リスト→自由テキスト入力へフォールバックする）。
    fake = FakeRegionServiceForMaterialValues(values=[])
    app.dependency_overrides[get_region_service] = lambda: fake

    try:
        response = client.get("/api/material-catalog/tracktype/values")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"values": []}
    assert fake.last_material_id == "tracktype"


def test_get_material_values_without_db_repository_returns_empty_list():
    # DB未接続構成（RegionService()、repository=None）を明示的に強制する。
    # 以前は「このファイルのclientはdependency_overrides未設定→get_region_serviceの
    # 既定分岐（settings.road_graph_use_repository）に委ねる」という設計だったが、
    # この既定分岐はDB接続の可否ではなく環境変数road_graph_use_repositoryの値で決まる
    # ため、DB接続済みのdev機（road_graph_use_repository=true）ではrepository付きの
    # RegionServiceが注入され実データが返り、本テストが環境依存で失敗していた
    # （2026-08-28指摘）。他のテスト（本ファイル上部）と同じdependency_overridesパターンで
    # 明示的にrepository無しのRegionServiceを注入し、環境非依存にする。
    app.dependency_overrides[get_region_service] = lambda: RegionService()

    try:
        response = client.get("/api/material-catalog/smoothness/values")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"values": []}


# --- 材料ごとの欠損割合（GET /api/admin/material-catalog/coverage、Basic認証必須） ---


COVERAGE_URL = "/api/admin/material-catalog/coverage"


def _basic_auth_header(username: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()


AUTH_HEADERS = {"Authorization": _basic_auth_header("admin-user", "secret-password")}


@pytest.fixture
def admin_credentials(monkeypatch):
    monkeypatch.setattr(settings, "admin_basic_auth_username", "admin-user")
    monkeypatch.setattr(settings, "admin_basic_auth_password", "secret-password")


class FakeMaterialCoverageService:
    def __init__(self, counts: MaterialCoverageCounts | None = None, error: Exception | None = None):
        self._counts = counts
        self._error = error

    async def get_material_coverage(self):
        if self._error is not None:
            raise self._error
        assert self._counts is not None
        return build_material_coverage_report(self._counts, datetime(2026, 9, 4, tzinfo=timezone.utc))


def _counts(**missing_overrides: int) -> MaterialCoverageCounts:
    missing = {material_id: 0 for material_id in MATERIAL_COVERAGE_SPECS}
    missing.update(missing_overrides)
    return MaterialCoverageCounts(way_total=200, edge_total=40, missing_by_material=missing)


def test_get_material_coverage_requires_basic_auth(admin_credentials):
    response = client.get(COVERAGE_URL)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="RideCompass admin"'


def test_get_material_coverage_rejects_wrong_credentials(admin_credentials):
    response = client.get(COVERAGE_URL, headers={"Authorization": _basic_auth_header("admin-user", "wrong")})

    assert response.status_code == 401


def test_get_material_coverage_returns_all_catalog_materials(admin_credentials):
    app.dependency_overrides[get_material_coverage_service] = lambda: FakeMaterialCoverageService(
        counts=_counts(surface=170, gradient_percent=30)
    )
    try:
        response = client.get(COVERAGE_URL, headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["way_total"] == 200
    assert body["edge_total"] == 40
    assert body["computed_at"].startswith("2026-09-04")
    assert [entry["material_id"] for entry in body["materials"]] == list(MATERIAL_CATALOG)

    by_id = {entry["material_id"]: entry for entry in body["materials"]}
    assert by_id["surface"] == {
        "material_id": "surface",
        "label": MATERIAL_CATALOG["surface"].full_label(),
        "dtype": "categorical",
        "population": "way",
        "total": 200,
        "missing": 170,
        "missing_ratio": pytest.approx(0.85),
        "source": MATERIAL_COVERAGE_SPECS["surface"].source,
        "missing_semantics": "unknown",
        "excluded_reason": None,
    }
    assert by_id["gradient_percent"]["population"] == "edge"
    assert by_id["gradient_percent"]["missing_ratio"] == pytest.approx(0.75)
    assert by_id["lit"]["missing_semantics"] == "definite"
    assert by_id["wind_penalty"]["population"] is None
    assert by_id["wind_penalty"]["excluded_reason"]


def test_get_material_coverage_translates_db_errors_to_503(admin_credentials):
    db_error = DBAPIError("SELECT 1", {}, Exception("connection refused"))
    app.dependency_overrides[get_material_coverage_service] = lambda: FakeMaterialCoverageService(error=db_error)
    try:
        response = client.get(COVERAGE_URL, headers=AUTH_HEADERS)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "欠損割合" in response.json()["detail"]
