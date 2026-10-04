"""`api/routers/tuning_admin.py`——較正値の一覧と上書きの管理API。

ここで見るもの: 一覧の並び（効き方ごと）・いま効いている値と上書き済みかの印・上書きを保存して読み直した結果・
宣言に無いidと保存側が断った値の状態コード。

ここで見ないもの:
- すべての口に認証が要ること → `test_admin_route_authorization.py`（`/api/admin/`配下の全ルートを走査する）
- 認証情報の照合そのもの（誤った・未設定の認証情報） → `admin_auth`のテスト
- 上書きの保存と、範囲の外・数値でない値の判定 → `services/tuning_service.py`・`infrastructure/tuning_overrides.py`のテスト
- 較正値の宣言の中身 → `domain/tuning.py`のテスト
- 宣言の項目（表示名・単位・範囲・効き方の名前）を応答へそのまま写すこと——書き写しで、判断が無い

**宣言は本物の宣言から作った架空の較正値へ差し替える**（`dataclasses.replace`で本物の型のまま、
効き方と並びだけをテストが決める）。いま効いている値は`TUNING_VALUES`へ差し込む。上書きの読み書き
（サービス）は差し替え、本物の署名へ当てる（`bound`）。読み出しは応答を差し替えるだけで、呼ばれ方は見ない。
"""

import dataclasses

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import tuning_admin
from app.domain.tuning import TUNING_VALUES
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
        self.error: Exception | None = None

    async def overridden_parameter_ids(self, session):
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
    for param_id, value in {"a": 11.0, "b": 12.0, "c": 13.0}.items():
        monkeypatch.setitem(TUNING_VALUES, param_id, value)
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


def test_list_shows_the_current_value_and_whether_it_is_overridden(client, declarations, store):
    store.overridden = {"a"}

    views = {p["id"]: p for p in client.get("/api/admin/tuning").json()}

    assert [(views[i]["value"], views[i]["overridden"]) for i in ("a", "b")] == [(11.0, True), (12.0, False)]


# ---- 上書き ----


def test_update_saves_the_value_and_returns_the_view_read_after_saving(client, declarations, store):
    response = client.put("/api/admin/tuning/a", json={"value": 20.0})

    assert store.saved == [(SESSION, "a", 20.0)]
    # 上書き済みかは保存のあとに読み直す
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
