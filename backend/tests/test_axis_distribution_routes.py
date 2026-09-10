"""分布プレビューの2エンドポイントのルーター層テスト。

計算本体は`tests/test_axis_preview_service.py`が持つ。ここでは**ルーターの振る舞い**
——認可・DB未接続時の扱い・未知の材料・サービス層の例外の変換——だけを見る。
どちらもT686/T697で新設されたがルーター層のテストが無く、認可の付け忘れやDB未接続時の
500がテストをすり抜けていた。
"""

from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_road_graph_repository
from app.main import app
from app.services.axis_preview_service import ValueDistribution
from tests.admin_auth import AUTH_HEADERS

client = TestClient(app)

_PREVIEW_PATH = "/api/admin/axis-definitions/preview-distribution"
_SHAPE = {
    "kind": "breakpoint_linear",
    "terms": [{"material": "curvature_deg_per_km", "weight": 1.0, "required": True}],
    "breakpoints": [[0.0, 0.0], [200.0, 100.0]],
    "preprocess": "identity",
}

_DISTRIBUTION = ValueDistribution(
    sample_ways=3,
    total_km=1.2,
    quantiles={"p50": 10.0},
    bins=[(0.0, 1.0, 1.0)],
    zero_share=0.0,
)


def _expected_json() -> dict:
    """JSONではtupleが配列になるため、期待値もその形へそろえる。"""
    payload = asdict(_DISTRIBUTION)
    payload["bins"] = [list(b) for b in payload["bins"]]
    return payload


@pytest.fixture
def _override_repository():
    """`get_road_graph_repository`を差し替えるためのヘルパ。値はテストごとに設定する。"""

    def _set(value):
        app.dependency_overrides[get_road_graph_repository] = lambda: value

    yield _set
    app.dependency_overrides.clear()


def test_preview_distribution_requires_admin_auth():
    response = client.post(_PREVIEW_PATH, json={"shape": _SHAPE})

    assert response.status_code == 401


def test_preview_distribution_returns_503_without_db(admin_credentials, _override_repository):
    # DB未接続構成では算出できない。500ではなく503で「今は出せない」と返す
    # （frontendはこの区別でエラー表示を出し分ける）。
    _override_repository(None)

    response = client.post(_PREVIEW_PATH, json={"shape": _SHAPE}, headers=AUTH_HEADERS)

    assert response.status_code == 503


def test_preview_distribution_returns_the_service_result(admin_credentials, monkeypatch, _override_repository):
    _override_repository(object())

    async def _fake(repository, shape):
        return _DISTRIBUTION

    monkeypatch.setattr("app.api.routers.axis_admin.axis_raw_value_distribution", _fake)

    response = client.post(_PREVIEW_PATH, json={"shape": _SHAPE}, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == _expected_json()


def _material_path(material_id: str) -> str:
    return f"/api/admin/material-catalog/{material_id}/distribution"


def test_material_distribution_requires_admin_auth():
    response = client.get(_material_path("curvature_deg_per_km"))

    assert response.status_code == 401


def test_material_distribution_returns_404_for_unknown_material(admin_credentials):
    response = client.get(_material_path("no_such_material"), headers=AUTH_HEADERS)

    assert response.status_code == 404


def test_material_distribution_reports_unavailable_without_db(admin_credentials, _override_repository):
    # 材料側は503ではなくavailable=falseで返す（軸スタジオは「実データが出せない」旨を
    # 行内に薄く出すだけで、編集そのものは続けられる）。
    _override_repository(None)

    response = client.get(_material_path("curvature_deg_per_km"), headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["available"] is False


def test_material_distribution_reports_unavailable_for_non_numeric_material(admin_credentials, monkeypatch, _override_repository):
    _override_repository(object())

    async def _fake(repository, material_id):
        return None

    monkeypatch.setattr("app.api.routers.material_catalog.material_value_distribution", _fake)

    response = client.get(_material_path("surface"), headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["available"] is False


def test_material_distribution_returns_the_service_result(admin_credentials, monkeypatch, _override_repository):
    _override_repository(object())

    async def _fake(repository, material_id):
        return _DISTRIBUTION

    monkeypatch.setattr("app.api.routers.material_catalog.material_value_distribution", _fake)

    response = client.get(_material_path("curvature_deg_per_km"), headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json() == {"available": True, **_expected_json()}
