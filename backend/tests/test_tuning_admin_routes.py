"""較正値の管理API（`api/routers/tuning_admin.py`）のテスト。

DBは触らない——セッションのDIをその場のフェイクへ差し替え、**画面が並べる項目が宣言から
導かれること**と、書かせてよい対象の線引きを見る。
"""

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_tuning_session
from app.domain import tuning
from app.domain.tuning import TUNING_PARAMETERS, TUNING_PARAMETERS_BY_ID
from app.main import app
from tests.admin_auth import AUTH_HEADERS

client = TestClient(app)

_PARAM = "turn.right_seconds"


class _FakeSession:
    """`tuning_overrides`の読み書きを、その場の辞書で代用する。"""

    def __init__(self) -> None:
        self.rows: dict[str, float] = {}

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture
def fake_overrides(monkeypatch, admin_credentials):
    """DBの代わりに辞書を使い、プロセス内の較正値も元へ戻す。"""
    session = _FakeSession()
    saved = dict(tuning.TUNING_VALUES)

    async def _read(_session):
        return dict(session.rows)

    async def _set(_session, param_id, value):
        from app.infrastructure.tuning_overrides import merge_overrides

        merge_overrides({param_id: value})
        if value == TUNING_PARAMETERS_BY_ID[param_id].default:
            session.rows.pop(param_id, None)
        else:
            session.rows[param_id] = value

    async def _clear(_session, param_id):
        session.rows.pop(param_id, None)

    async def _refresh(_session):
        from app.infrastructure.tuning_overrides import merge_overrides

        merged = merge_overrides(dict(session.rows))
        tuning.TUNING_VALUES.clear()
        tuning.TUNING_VALUES.update(merged)

    # 差し替えるのは**サービス層が使うinfrastructure**（取引の区切りはサービスが持つ、
    # design-principles.md構造仕様7）。ルーター側へ当てると、サービスを通る経路
    # （commit/rollbackの位置）がテストから外れる。
    import app.services.tuning_service as service

    monkeypatch.setattr(service, "read_overrides", _read)
    monkeypatch.setattr(service, "set_override", _set)
    monkeypatch.setattr(service, "clear_override", _clear)
    monkeypatch.setattr(service, "refresh_tuning_values", _refresh)
    app.dependency_overrides[get_tuning_session] = lambda: session
    yield session
    app.dependency_overrides.pop(get_tuning_session, None)
    tuning.TUNING_VALUES.clear()
    tuning.TUNING_VALUES.update(saved)


def test_requires_admin_auth(admin_credentials):
    # 走行モデルの振る舞いを直接変えられるため、軸スタジオと同じ認可境界の内側に置く。
    assert client.get("/api/admin/tuning").status_code == 401


def test_lists_exactly_the_declared_calibration_values(fake_overrides):
    # 画面へ出るのは較正値の宣言に載っているものだけ。較正値ではない固定値（物理定数・
    # 資源の上限）は使う側のモジュールにあり、このAPIからは見えない。
    response = client.get("/api/admin/tuning", headers=AUTH_HEADERS)

    assert response.status_code == 200
    listed = {row["id"] for row in response.json()}
    assert listed == {p.id for p in TUNING_PARAMETERS}


def test_each_row_carries_what_it_takes_for_the_change_to_apply(fake_overrides):
    # 「変えたのに効かない」を画面から見えるようにするための宣言。
    rows = {row["id"]: row for row in client.get("/api/admin/tuning", headers=AUTH_HEADERS).json()}

    for param_id, row in rows.items():
        assert row["effect"] == TUNING_PARAMETERS_BY_ID[param_id].effect.value


def test_updating_a_value_reaches_the_running_value(fake_overrides):
    changed = TUNING_PARAMETERS_BY_ID[_PARAM].default + 5.0

    response = client.put(f"/api/admin/tuning/{_PARAM}", json={"value": changed}, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["value"] == changed
    assert response.json()["overridden"] is True
    assert tuning.tuning_value(_PARAM) == changed


def test_clearing_puts_the_declared_default_back(fake_overrides):
    client.put(f"/api/admin/tuning/{_PARAM}", json={"value": 30.0}, headers=AUTH_HEADERS)

    response = client.put(f"/api/admin/tuning/{_PARAM}", json={"value": None}, headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["value"] == TUNING_PARAMETERS_BY_ID[_PARAM].default
    assert response.json()["overridden"] is False


def test_a_value_outside_the_declared_range_is_rejected(fake_overrides):
    too_big = TUNING_PARAMETERS_BY_ID[_PARAM].maximum + 1.0

    response = client.put(f"/api/admin/tuning/{_PARAM}", json={"value": too_big}, headers=AUTH_HEADERS)

    assert response.status_code == 422
    assert tuning.tuning_value(_PARAM) == TUNING_PARAMETERS_BY_ID[_PARAM].default


def test_an_undeclared_id_is_not_writable(fake_overrides):
    response = client.put("/api/admin/tuning/turn.no_such_value", json={"value": 1.0}, headers=AUTH_HEADERS)

    assert response.status_code == 404
