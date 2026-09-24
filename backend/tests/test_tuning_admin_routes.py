"""`api/routers/tuning_admin.py`——較正値の一覧と上書きの管理API。

ここで見ないもの:
- すべての口に認証が要ること → `test_admin_route_authorization.py`（`/api/admin/`配下の全ルートを走査する）
- 認証情報の照合そのもの（誤った・未設定の認証情報） → `admin_auth`のテスト
- 上書きの保存と、範囲の外・数値でない値の判定 → `services/tuning_service.py`・`infrastructure/tuning_overrides.py`のテスト
- 較正値の宣言の中身 → `domain/tuning.py`のテスト

**宣言は本物の宣言から作った架空の較正値へ差し替える**（`dataclasses.replace`で本物の型のまま、
効き方と並びだけをテストが決める）。上書きの読み書き（サービス）と、いま効いている値は差し替え、
本物の署名へ当てる（`bound`）。
"""

import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import tuning_admin
from tests.admin_auth import AUTH_HEADERS
from tests.bound_fake import bound

SESSION = object()


def _declared(param_id: str, effect) -> object:
    return dataclasses.replace(
        tuning_admin.TUNING_PARAMETERS[0],
        id=param_id,
        label=f"表示名-{param_id}",
        unit="km/h",
        description=f"説明-{param_id}",
        default=10.0,
        minimum=1.0,
        maximum=100.0,
        effect=effect,
    )


class Store:
    """上書きの読み書き（サービスの代役）。保存したidは次の読み出しから上書き済みになる。"""

    def __init__(self):
        self.overridden: set[str] = set()
        self.saved: list[tuple[object, str, float | None]] = []
        self.reads: list[object] = []
        self.error: Exception | None = None

    async def overridden_parameter_ids(self, session):
        self.reads.append(session)
        return set(self.overridden)

    async def save_override(self, session, param_id, value):
        if self.error is not None:
            raise self.error
        self.saved.append((session, param_id, value))
        self.overridden.add(param_id)


@pytest.fixture
def declarations(monkeypatch):
    """宣言順は a（画面の再読み込み）・b（即時）・c（画面の再読み込み）。"""
    params = (
        _declared("a", tuning_admin.TuningEffect.CLIENT_RELOAD),
        _declared("b", tuning_admin.TuningEffect.IMMEDIATE),
        _declared("c", tuning_admin.TuningEffect.CLIENT_RELOAD),
    )
    monkeypatch.setattr(tuning_admin, "TUNING_PARAMETERS", params)
    monkeypatch.setattr(tuning_admin, "TUNING_PARAMETERS_BY_ID", {p.id: p for p in params})
    values = {"a": 11.0, "b": 12.0, "c": 13.0}
    monkeypatch.setattr(
        tuning_admin, "tuning_value", bound(tuning_admin.tuning_value, lambda param_id: values[param_id])
    )
    return params


@pytest.fixture
def store(monkeypatch):
    fake = Store()
    monkeypatch.setattr(
        tuning_admin,
        "overridden_parameter_ids",
        bound(tuning_admin.overridden_parameter_ids, fake.overridden_parameter_ids),
    )
    monkeypatch.setattr(tuning_admin, "save_override", bound(tuning_admin.save_override, fake.save_override))
    return fake


@pytest.fixture
def app(store):
    application = FastAPI()
    application.include_router(tuning_admin.router)
    application.dependency_overrides[tuning_admin.get_tuning_session] = lambda: SESSION
    return application


@pytest.fixture
def client(app, admin_credentials):
    return TestClient(app, headers=AUTH_HEADERS)


# ---- 一覧 ----


def test_list_returns_every_declared_value_grouped_by_how_it_takes_effect(client, declarations):
    response = client.get("/api/admin/tuning")

    # 効き方の宣言順（即時→…→画面の再読み込み）にまとめ、同じ効き方の中は宣言順のまま
    assert [p["id"] for p in response.json()] == ["b", "a", "c"]


def test_list_shows_the_declaration_the_current_value_and_whether_it_is_overridden(client, declarations, store):
    store.overridden = {"a"}

    views = {p["id"]: p for p in client.get("/api/admin/tuning").json()}

    assert views["a"] == {
        "id": "a",
        "label": "表示名-a",
        "unit": "km/h",
        "description": "説明-a",
        "default": 10.0,
        "minimum": 1.0,
        "maximum": 100.0,
        "effect": tuning_admin.TuningEffect.CLIENT_RELOAD.value,
        "effect_title": tuning_admin.TuningEffect.CLIENT_RELOAD.title,
        "value": 11.0,
        "overridden": True,
    }
    assert views["b"]["overridden"] is False
    assert store.reads == [SESSION]


# ---- 上書き ----


@pytest.mark.parametrize("value", [20.0, None])
def test_update_saves_the_value_and_returns_the_view_read_after_saving(client, declarations, store, value):
    # 値を省略（None）すると既定へ戻す——その判断は保存側が持ち、ここはそのまま渡す
    response = client.put("/api/admin/tuning/a", json={} if value is None else {"value": value})

    assert response.status_code == 200
    assert store.saved == [(SESSION, "a", value)]
    # 上書き済みかは保存のあとに、同じセッションで読み直す
    assert store.reads == [SESSION]
    assert response.json()["overridden"] is True


def test_update_of_an_undeclared_id_is_not_found_and_saves_nothing(client, declarations, store):
    response = client.put("/api/admin/tuning/zzz", json={"value": 20.0})

    assert response.status_code == 404
    assert "zzz" in response.json()["detail"]
    assert store.saved == []


def test_update_the_store_refuses_is_unprocessable_with_its_reason(client, declarations, store):
    store.error = tuning_admin.TuningOverrideError("範囲の外: a=1000")

    response = client.put("/api/admin/tuning/a", json={"value": 1000.0})

    assert response.status_code == 422
    assert response.json()["detail"] == "範囲の外: a=1000"
