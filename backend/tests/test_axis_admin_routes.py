import base64

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_axis_registry_admin_service
from app.config import settings
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    MaterialTerm,
    check_publish_immutability,
)
from app.main import app

client = TestClient(app)

_PAYLOAD = {
    "axis_id": "test_axis",
    "shape": {
        "kind": "breakpoint_linear",
        "terms": [{"material": "gradient_percent", "weight": 1.0, "required": True}],
        "preprocess": "identity",
        "breakpoints": [[0.0, 0.0], [10.0, 100.0]],
    },
    "default_weight": 0.1,
    "label": "テスト軸",
    "description": "テスト用ダミー軸",
    "category": "推定",
}

_DEFINITION = AxisDefinition(
    axis_id="test_axis",
    shape=BreakpointLinearShape(
        terms=[MaterialTerm(material="gradient_percent")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]
    ),
    default_weight=0.1,
    label="テスト軸",
    description="テスト用ダミー軸",
    category="推定",
)


class FakeAxisRegistryAdminService:
    def __init__(self, definitions: dict[str, AxisDefinition] | None = None):
        self._definitions = definitions if definitions is not None else {}

    async def list_all(self) -> dict[str, AxisDefinition]:
        return self._definitions

    async def get(self, axis_id: str) -> AxisDefinition | None:
        return self._definitions.get(axis_id)

    async def create(self, definition: AxisDefinition) -> None:
        if definition.axis_id in self._definitions:
            raise ValueError(f"axis_id={definition.axis_id} は既に存在します")
        self._definitions[definition.axis_id] = definition

    async def update(self, axis_id: str, definition: AxisDefinition) -> None:
        if axis_id not in self._definitions:
            raise KeyError(axis_id)
        check_publish_immutability(self._definitions[axis_id], "updated")
        self._definitions[axis_id] = definition

    async def delete(self, axis_id: str) -> None:
        if axis_id not in self._definitions:
            raise KeyError(axis_id)
        if len(self._definitions) == 1:
            raise ValueError("最後の1軸は削除できません")
        check_publish_immutability(self._definitions[axis_id], "deleted")
        del self._definitions[axis_id]


def _basic_auth_header(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


@pytest.fixture(autouse=True)
def admin_credentials(monkeypatch):
    monkeypatch.setattr(settings, "admin_basic_auth_username", "admin-user")
    monkeypatch.setattr(settings, "admin_basic_auth_password", "secret-password")


@pytest.fixture
def override_service():
    fake = FakeAxisRegistryAdminService()
    app.dependency_overrides[get_axis_registry_admin_service] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.clear()


AUTH_HEADERS = {"Authorization": _basic_auth_header("admin-user", "secret-password")}


# --- 認可（require_admin_basic_auth） ---


def test_list_rejects_missing_credentials(override_service):
    response = client.get("/api/admin/axis-definitions")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="RideCompass admin"'


def test_list_rejects_wrong_credentials(override_service):
    response = client.get(
        "/api/admin/axis-definitions", headers={"Authorization": _basic_auth_header("admin-user", "wrong")}
    )

    assert response.status_code == 401


def test_list_rejects_any_credentials_when_unset(override_service, monkeypatch):
    monkeypatch.setattr(settings, "admin_basic_auth_username", "")
    monkeypatch.setattr(settings, "admin_basic_auth_password", "")

    response = client.get("/api/admin/axis-definitions", headers=AUTH_HEADERS)

    assert response.status_code == 401


def test_list_succeeds_with_correct_credentials(override_service):
    response = client.get("/api/admin/axis-definitions", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == []


# --- CRUD ---


def test_create_returns_422_for_unknown_material(override_service):
    # 改善計画T277: shapeが参照する材料はdomain/material_catalog.py: MATERIAL_CATALOGの
    # 既知材料でなければ拒否する。
    payload = {
        **_PAYLOAD,
        "shape": {
            "kind": "breakpoint_linear",
            "terms": [{"material": "not_a_real_material", "weight": 1.0, "required": True}],
            "preprocess": "identity",
            "breakpoints": [[0.0, 0.0], [10.0, 100.0]],
        },
    }

    response = client.post("/api/admin/axis-definitions", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 422
    assert "not_a_real_material" in response.text


def test_create_returns_422_when_categorical_shape_uses_numeric_material(override_service):
    # レビュー指摘の修正確認: CategoricalShape/FlagSumShapeはboolean材料前提だが、
    # 以前は材料の存在チェックのみでdtypeを見ておらず、numeric材料（例:
    # stop_count_per_km）を指定しても素通りしていた（evaluate_categoricalが常に
    # None/NaNを返す=軸が恒久的に欠損扱いになる無言のバグ）。
    payload = {
        **_PAYLOAD,
        "shape": {
            "kind": "categorical",
            "material": "stop_count_per_km",
            "mapping": {"true": 0.0, "false": 80.0},
        },
    }

    response = client.post("/api/admin/axis-definitions", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 422
    assert "stop_count_per_km" in response.text


def test_create_returns_422_when_breakpoint_linear_shape_uses_categorical_material(override_service):
    # 改善計画T290: MATERIAL_CATALOGへ追加したdtype="categorical"材料（highway等）は
    # 登録のみで評価軸には未対応（CategoricalShapeが現状booleanのみ対応のため）。
    # numeric専用のBreakpointLinearShapeに指定した場合も、既存のdtype検証
    # （expected_dtype != material_dtype）で正しく拒否されることを確認する
    # （"numeric"でも"boolean"でもないcategoricalは、両方のexpected_dtype判定と
    # 必ず不一致になる設計）。
    payload = {
        **_PAYLOAD,
        "shape": {
            "kind": "breakpoint_linear",
            "terms": [{"material": "highway", "weight": 1.0, "required": True}],
            "preprocess": "identity",
            "breakpoints": [[0.0, 0.0], [10.0, 100.0]],
        },
    }

    response = client.post("/api/admin/axis-definitions", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 422
    assert "highway" in response.text


def test_create_accepts_categorical_shape_with_categorical_material(override_service):
    # 改善計画T292: CategoricalShape.mappingがstrキーにも対応した（highway/bicycle_infra等の
    # dtype="categorical"材料、多値対応）ため、以前は拒否していたこの組み合わせが正当に
    # 受理されるようになった（T290時点ではCategoricalShapeがbooleanキー専用だったため
    # 422で拒否する回帰テストだったが、T292でその制約自体を撤廃したため意味が反転した）。
    payload = {
        **_PAYLOAD,
        "shape": {
            "kind": "categorical",
            "material": "bicycle_infra",
            "mapping": {"separated": 0.0, "lane": 20.0, "roadway": 70.0},
        },
    }

    response = client.post("/api/admin/axis-definitions", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 201


def test_create_returns_422_when_categorical_shape_mapping_keys_mismatch_material_dtype(override_service):
    # コードレビュー指摘の修正確認: dtype「クラス」（boolean/categoricalのどちらか）の
    # 一致だけを見ていた従来のチェックだと、highway（dtype="categorical"、文字列値）を
    # 参照しつつmappingはboolキー（{"true": ..., "false": ...}）という組み合わせが
    # 素通りしていた。これは評価時evaluate_categoricalが常にNoneを返す（=軸が恒久的に
    # 欠損扱いになる）のと同型の無言バグのため、mappingキーの実際の型もmaterialの
    # dtypeと一致することを検証するようにした。
    payload = {
        **_PAYLOAD,
        "shape": {
            "kind": "categorical",
            "material": "highway",
            "mapping": {"true": 0.0, "false": 80.0},
        },
    }

    response = client.post("/api/admin/axis-definitions", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 422
    assert "highway" in response.text


def test_create_returns_422_when_flag_sum_shape_uses_numeric_material(override_service):
    payload = {
        **_PAYLOAD,
        "shape": {
            "kind": "flag_sum",
            "flags": [["accident_count_per_km_year", 50.0]],
            "cap": 100.0,
        },
    }

    response = client.post("/api/admin/axis-definitions", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 422
    assert "accident_count_per_km_year" in response.text


def test_create_returns_201_and_persists(override_service):
    response = client.post("/api/admin/axis-definitions", json=_PAYLOAD, headers=AUTH_HEADERS)

    assert response.status_code == 201
    assert response.json()["axis_id"] == "test_axis"
    assert "test_axis" in override_service._definitions


def test_create_persists_and_returns_priority_overrides(override_service):
    # コードレビュー指摘の修正確認: priority_overrides（0次条件）が管理API経由で
    # 設定・参照できること（以前はAxisDefinitionFieldsに露出しておらず、
    # 送信しても静かに無視されていた）。
    payload = {
        **_PAYLOAD,
        "priority_overrides": [{"material": "motor_vehicle_no", "equals": "true", "value": 0.0}],
    }

    response = client.post("/api/admin/axis-definitions", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == 201
    assert response.json()["priority_overrides"] == [
        {"material": "motor_vehicle_no", "equals": "true", "value": 0.0}
    ]
    assert override_service._definitions["test_axis"].priority_overrides[0].material == "motor_vehicle_no"


def test_create_returns_409_on_duplicate(override_service):
    override_service._definitions["test_axis"] = _DEFINITION

    response = client.post("/api/admin/axis-definitions", json=_PAYLOAD, headers=AUTH_HEADERS)

    assert response.status_code == 409


def test_get_returns_404_for_unknown_axis_id(override_service):
    response = client.get("/api/admin/axis-definitions/unknown", headers=AUTH_HEADERS)

    assert response.status_code == 404


def test_get_returns_definition(override_service):
    override_service._definitions["test_axis"] = _DEFINITION

    response = client.get("/api/admin/axis-definitions/test_axis", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["axis_id"] == "test_axis"


def test_list_and_get_succeed_for_axis_referencing_a_now_unknown_material(override_service):
    # レビュー指摘の修正確認: AxisDefinitionResponseは書き込み専用バリデータ
    # （_check_materials_are_known）を継承しないため、材料カタログから将来削除・
    # リネームされた材料をまだ参照する既存軸（AxisDefinitionはPayload経由を通らず
    # 直接構築されているためこのテストではその状況を模する）の読み取りが500に
    # ならないことを確認する。
    stale = AxisDefinition(
        axis_id="stale_axis",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="removed_material")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]
        ),
        default_weight=0.1,
        label="廃止予定材料を参照する軸",
        category="推定",
    )
    override_service._definitions["stale_axis"] = stale

    list_response = client.get("/api/admin/axis-definitions", headers=AUTH_HEADERS)
    get_response = client.get("/api/admin/axis-definitions/stale_axis", headers=AUTH_HEADERS)

    assert list_response.status_code == 200
    assert get_response.status_code == 200
    assert get_response.json()["axis_id"] == "stale_axis"


def test_update_returns_400_when_axis_id_mismatches_url(override_service):
    override_service._definitions["test_axis"] = _DEFINITION

    response = client.put("/api/admin/axis-definitions/other_id", json=_PAYLOAD, headers=AUTH_HEADERS)

    assert response.status_code == 400


def test_update_returns_404_for_unknown_axis_id(override_service):
    response = client.put("/api/admin/axis-definitions/test_axis", json=_PAYLOAD, headers=AUTH_HEADERS)

    assert response.status_code == 404


def test_update_returns_200_and_persists(override_service):
    override_service._definitions["test_axis"] = _DEFINITION
    updated_payload = {**_PAYLOAD, "default_weight": 0.9}

    response = client.put("/api/admin/axis-definitions/test_axis", json=updated_payload, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert override_service._definitions["test_axis"].default_weight == 0.9


def test_update_returns_409_for_published_axis(override_service):
    # 改善計画T271: 公開済み軸の更新は409で拒否される（以前はupdate_axis_definitionに
    # ValueError用のexcept節が無く想定外の500になっていた抜け穴も合わせて塞いだ）。
    override_service._definitions["test_axis"] = _DEFINITION.model_copy(update={"is_published": True})
    updated_payload = {**_PAYLOAD, "default_weight": 0.9}

    response = client.put("/api/admin/axis-definitions/test_axis", json=updated_payload, headers=AUTH_HEADERS)

    assert response.status_code == 409
    assert override_service._definitions["test_axis"].default_weight == 0.1


def test_delete_returns_404_for_unknown_axis_id(override_service):
    response = client.delete("/api/admin/axis-definitions/unknown", headers=AUTH_HEADERS)

    assert response.status_code == 404


def test_delete_returns_204_and_removes(override_service):
    override_service._definitions["test_axis"] = _DEFINITION
    override_service._definitions["other_axis"] = _DEFINITION

    response = client.delete("/api/admin/axis-definitions/test_axis", headers=AUTH_HEADERS)

    assert response.status_code == 204
    assert "test_axis" not in override_service._definitions


def test_delete_returns_409_for_published_axis(override_service):
    override_service._definitions["test_axis"] = _DEFINITION.model_copy(update={"is_published": True})
    override_service._definitions["other_axis"] = _DEFINITION.model_copy(update={"axis_id": "other_axis"})

    response = client.delete("/api/admin/axis-definitions/test_axis", headers=AUTH_HEADERS)

    assert response.status_code == 409
    assert "test_axis" in override_service._definitions


def test_delete_returns_409_for_last_remaining_axis(override_service):
    override_service._definitions["test_axis"] = _DEFINITION

    response = client.delete("/api/admin/axis-definitions/test_axis", headers=AUTH_HEADERS)

    assert response.status_code == 409
