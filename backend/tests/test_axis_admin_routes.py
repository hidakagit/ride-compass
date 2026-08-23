import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_axis_registry_admin_service
from app.config import settings
from app.domain.axis_definitions import AxisDefinition, BreakpointLinearShape, MaterialTerm
from app.main import app

client = TestClient(app)

_PAYLOAD = {
    "axis_id": "test_axis",
    "shape": {
        "kind": "breakpoint_linear",
        "terms": [{"material": "dummy", "weight": 1.0, "required": True}],
        "preprocess": "identity",
        "breakpoints": [[0.0, 0.0], [10.0, 100.0]],
    },
    "default_weight": 0.1,
}

_DEFINITION = AxisDefinition(
    axis_id="test_axis",
    shape=BreakpointLinearShape(terms=[MaterialTerm(material="dummy")], breakpoints=[(0.0, 0.0), (10.0, 100.0)]),
    default_weight=0.1,
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
        self._definitions[axis_id] = definition

    async def delete(self, axis_id: str) -> None:
        if axis_id not in self._definitions:
            raise KeyError(axis_id)
        if len(self._definitions) == 1:
            raise ValueError("最後の1軸は削除できません")
        del self._definitions[axis_id]


@pytest.fixture(autouse=True)
def admin_token(monkeypatch):
    monkeypatch.setattr(settings, "axis_admin_token", "secret-token")


@pytest.fixture
def override_service():
    fake = FakeAxisRegistryAdminService()
    app.dependency_overrides[get_axis_registry_admin_service] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.clear()


AUTH_HEADERS = {"X-Admin-Token": "secret-token"}


# --- 認可（require_axis_admin_token） ---


def test_list_rejects_missing_token(override_service):
    response = client.get("/api/admin/axis-definitions")

    assert response.status_code == 403


def test_list_rejects_wrong_token(override_service):
    response = client.get("/api/admin/axis-definitions", headers={"X-Admin-Token": "wrong"})

    assert response.status_code == 403


def test_list_rejects_any_token_when_admin_token_unset(override_service, monkeypatch):
    monkeypatch.setattr(settings, "axis_admin_token", "")

    response = client.get("/api/admin/axis-definitions", headers=AUTH_HEADERS)

    assert response.status_code == 403


def test_list_succeeds_with_correct_token(override_service):
    response = client.get("/api/admin/axis-definitions", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == []


# --- CRUD ---


def test_create_returns_201_and_persists(override_service):
    response = client.post("/api/admin/axis-definitions", json=_PAYLOAD, headers=AUTH_HEADERS)

    assert response.status_code == 201
    assert response.json()["axis_id"] == "test_axis"
    assert "test_axis" in override_service._definitions


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


def test_delete_returns_404_for_unknown_axis_id(override_service):
    response = client.delete("/api/admin/axis-definitions/unknown", headers=AUTH_HEADERS)

    assert response.status_code == 404


def test_delete_returns_204_and_removes(override_service):
    override_service._definitions["test_axis"] = _DEFINITION
    override_service._definitions["other_axis"] = _DEFINITION

    response = client.delete("/api/admin/axis-definitions/test_axis", headers=AUTH_HEADERS)

    assert response.status_code == 204
    assert "test_axis" not in override_service._definitions


def test_delete_returns_409_for_last_remaining_axis(override_service):
    override_service._definitions["test_axis"] = _DEFINITION

    response = client.delete("/api/admin/axis-definitions/test_axis", headers=AUTH_HEADERS)

    assert response.status_code == 409
