"""`api/routers/axis_admin.py`——軸スタジオの管理API（書き込み時の検証・例外の変換）。

ここで見ないもの:
- 軸そのものの不変条件（折れ点・段の境界・段ラベル）と公開の不変性・材料の排他、軸の外（材料カタログ・
  ほかの軸）に照らす値の不変条件（`check_axis_definition`）の中身 → `test_axis_definitions.py`
- 書き込みの本体（DBへの反映と`AXIS_DEFINITIONS`の差し替え） → `test_axis_registry_service.py`
- 地図表示の導出・段が落ちるかの判定 → `test_axis_display.py`
- 分布の計算 → `test_axis_preview_service.py`
- 認可（どの口もBasic認証の依存を持つこと・その依存が拒むこと） → `test_admin_route_authorization.py`

**ルーターが名前空間に持つ外向きの参照は差し替える**——軸の集合・配信実装の有無・分布の計算（DB）。
地図表示の導出（domain）と材料カタログは本物を通し、材料は性質ごとに本物のカタログから選ぶ。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.api.routers import axis_admin
from app.domain.axis_definitions import REQUEST_DYNAMIC_MATERIAL_IDS
from app.domain.material_catalog import MATERIAL_CATALOG
from app.services.axis_preview_service import ValueDistribution
from tests.admin_auth import AUTH_HEADERS
from tests.bound_fake import bound


def _static_materials(dtype: str) -> list[str]:
    return [m for m, spec in MATERIAL_CATALOG.items() if spec.dtype == dtype and m not in REQUEST_DYNAMIC_MATERIAL_IDS]


BASE = "/api/admin/axis-definitions"
NUM_A, NUM_B = _static_materials("numeric")[:2]
BOOL_A = _static_materials("boolean")[0]
#: 地図に塗れる（タイルに向きによらない値を持つ）数値の材料。
RAMP_NUM = next(
    m
    for m in _static_materials("numeric")
    if MATERIAL_CATALOG[m].tile_property and not MATERIAL_CATALOG[m].tile_property_direction_dependent
)
REFERENCED_AXIS = "ref"
REPOSITORY = object()


def linear_shape(*materials):
    return {
        "kind": "breakpoint_linear",
        "terms": [{"material": m} for m in materials],
        "breakpoints": [[0, 0], [10, 100]],
    }


def payload(axis_id="a", **fields):
    body = {"axis_id": axis_id, "label": "軸A", "default_weight": 1.0, "shape": linear_shape(NUM_A)}
    body.update(fields)
    return body


def stored(axis_id="a", **fields):
    return axis_admin.AxisDefinition.model_validate(payload(axis_id, **fields))


class FakeAxisRegistry:
    """`AxisRegistryAdminService`の代役。受けた呼び出しを記録し、`errors`に置いた例外を送出する。"""

    def __init__(self):
        self.axes: dict[str, axis_admin.AxisDefinition] = {}
        self.calls: list[tuple] = []
        self.errors: dict[str, Exception] = {}

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if name in self.errors:
            raise self.errors[name]

    @property
    def writes(self) -> list[tuple]:
        """受けた呼び出しのうち書き込み（応答に重みの割合を添えるための一覧の読み取りを除く）。"""
        return [call for call in self.calls if call[0] not in ("list_all", "get")]

    async def list_all(self):
        self._record("list_all")
        return dict(self.axes)

    async def get(self, axis_id):
        self._record("get", axis_id)
        return self.axes.get(axis_id)

    async def create(self, definition):
        self._record("create", definition)
        self.axes[definition.axis_id] = definition

    async def update(self, axis_id, definition):
        self._record("update", axis_id, definition)
        self.axes[axis_id] = definition

    async def delete(self, axis_id):
        self._record("delete", axis_id)
        self.axes.pop(axis_id)

    async def unpublish(self, axis_id):
        self._record("unpublish", axis_id)
        self.axes[axis_id] = self.axes[axis_id].model_copy(update={"is_published": False})


@pytest.fixture
def registry():
    return FakeAxisRegistry()


@pytest.fixture
def seams(monkeypatch):
    """差し替えた外向きの参照が受けた引数を記録する。"""
    received: dict[str, list] = {"served": [], "distribution": []}

    def served_dedicated_way_value_material(materials):
        materials = list(materials)
        received["served"].append(materials)
        return NUM_A if materials == [NUM_A] else None

    async def axis_raw_value_distribution(repository, shape):
        received["distribution"].append((repository, shape))
        return ValueDistribution(
            sample_ways=3, total_km=1.5, quantiles={"p50": 2.0}, bins=[(0.0, 4.0, 1.0)], zero_share=0.25
        )

    fakes = {
        "served_dedicated_way_value_material": served_dedicated_way_value_material,
        "axis_raw_value_distribution": axis_raw_value_distribution,
    }
    for name, fake in fakes.items():
        monkeypatch.setattr(axis_admin, name, bound(getattr(axis_admin, name), fake))
    monkeypatch.setattr(axis_admin, "AXIS_DEFINITIONS", {REFERENCED_AXIS: stored(REFERENCED_AXIS)})
    return received


@pytest.fixture
def app(registry, seams):
    app = FastAPI()
    app.include_router(axis_admin.router)
    app.dependency_overrides[axis_admin.get_axis_registry_admin_service] = lambda: registry
    app.dependency_overrides[axis_admin.get_road_graph_repository] = lambda: REPOSITORY
    return app


@pytest.fixture
def client(app, admin_credentials):
    return TestClient(app, headers=AUTH_HEADERS)


# 口ごとの(本文, DBが落ちたときの状態コード)。母集団は`router.routes`から取るので、口を足して
# ここへ足し忘れるとKeyErrorで落ちる。
ROUTE_CASES = {
    ("GET", BASE): (None, 503),
    ("POST", BASE): (payload(), 503),
    ("GET", BASE + "/{axis_id}"): (None, 503),
    ("PUT", BASE + "/{axis_id}"): (payload(), 503),
    ("DELETE", BASE + "/{axis_id}"): (None, 503),
    ("POST", BASE + "/{axis_id}/unpublish"): (None, 503),
    ("POST", BASE + "/preview-distribution"): ({"shape": linear_shape(NUM_A)}, 503),
    ("POST", BASE + "/preview-display-thresholds"): (
        {"axis_id": "a", "shape": linear_shape(NUM_A), "thresholds": [1.0]},
        200,
    ),
    ("POST", BASE + "/preview-scores"): ({"shape": linear_shape(NUM_A), "xs": [0.5]}, 200),
}
ROUTES = [(method, route.path) for route in axis_admin.router.routes for method in sorted(route.methods)]


def send(client, method, path):
    body, _ = ROUTE_CASES[(method, path)]
    return client.request(method, path.replace("{axis_id}", "a"), json=body)


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_a_database_failure_becomes_a_503_on_every_route_that_reads_it(client, registry, monkeypatch, method, path):
    failure = DBAPIError("SELECT 1", {}, Exception("接続できない"))
    registry.axes["a"] = stored()
    registry.errors = {name: failure for name in ("list_all", "get", "create", "update", "delete", "unpublish")}

    async def failing_distribution(repository, shape):
        raise failure

    monkeypatch.setattr(
        axis_admin, "axis_raw_value_distribution", bound(axis_admin.axis_raw_value_distribution, failing_distribution)
    )

    response = send(client, method, path)

    assert response.status_code == ROUTE_CASES[(method, path)][1]
    if response.status_code == 503:
        assert "軸定義DBへのアクセスに失敗しました" in response.json()["detail"]


class TestRead:
    def test_list_returns_every_axis_with_its_map_display(self, client, registry):
        registry.axes = {"a": stored("a"), "b": stored("b", label="軸B")}

        body = client.get(BASE).json()

        assert [(item["axis_id"], item["display"]["label"]) for item in body] == [("a", "軸A"), ("b", "軸B")]

    def test_get_returns_the_axis_with_its_map_display(self, client, registry):
        registry.axes["a"] = stored()

        body = client.get(BASE + "/a").json()

        assert body["axis_id"] == "a"
        assert body["display"]["label"] == "軸A"

    def test_get_of_an_unknown_axis_is_404(self, client):
        assert client.get(BASE + "/missing").status_code == 404

    def test_an_axis_whose_material_left_the_catalog_can_still_be_read(self, client, registry):
        """読み出しは保存済みの内容を返すだけで、書き込み時の検証をやり直さない。"""
        registry.axes["a"] = stored(shape=linear_shape("retired"))

        assert client.get(BASE + "/a").status_code == 200


class TestWrite:
    def test_create_stores_a_plain_axis_definition_and_returns_it_with_its_display(self, client, registry):
        """ペイロードの型のまま渡すと、公開後の見た目だけの更新を判定する等価比較が型の違いで
        常に不一致になる。"""
        response = client.post(BASE, json=payload(chip_label="略"))

        assert response.status_code == 201
        assert response.json()["display"]["label"] == "軸A"
        ((name, definition),) = registry.writes
        assert name == "create"
        assert type(definition) is axis_admin.AxisDefinition
        assert definition.chip_label == "略"

    def test_create_rejected_by_the_registry_is_a_409(self, client, registry):
        registry.errors["create"] = ValueError("材料が重複している")

        response = client.post(BASE, json=payload())

        assert (response.status_code, response.json()["detail"]) == (409, "材料が重複している")

    def test_update_stores_a_plain_axis_definition_under_the_axis_id(self, client, registry):
        registry.axes["a"] = stored()

        response = client.put(BASE + "/a", json=payload(default_weight=2.0))

        assert response.status_code == 200
        ((name, axis_id, definition),) = registry.writes
        assert (name, axis_id, type(definition), definition.default_weight) == (
            "update",
            "a",
            axis_admin.AxisDefinition,
            2.0,
        )

    def test_update_whose_body_names_another_axis_is_a_400(self, client, registry):
        response = client.put(BASE + "/a", json=payload("b"))

        assert response.status_code == 400
        assert registry.calls == []

    @pytest.mark.parametrize(
        ("method", "path", "body", "operation"),
        [
            ("PUT", BASE + "/a", payload(), "update"),
            ("DELETE", BASE + "/a", None, "delete"),
            ("POST", BASE + "/a/unpublish", None, "unpublish"),
        ],
    )
    def test_an_operation_on_an_unknown_axis_is_a_404(self, client, registry, method, path, body, operation):
        registry.errors[operation] = KeyError("a")

        assert client.request(method, path, json=body).status_code == 404

    @pytest.mark.parametrize(
        ("method", "path", "body", "operation"),
        [("PUT", BASE + "/a", payload(), "update"), ("DELETE", BASE + "/a", None, "delete")],
    )
    def test_an_operation_refused_by_the_registry_is_a_409(self, client, registry, method, path, body, operation):
        registry.errors[operation] = ValueError("公開済みの軸は変更できない")

        response = client.request(method, path, json=body)

        assert (response.status_code, response.json()["detail"]) == (409, "公開済みの軸は変更できない")

    def test_delete_is_a_204(self, client, registry):
        registry.axes["a"] = stored()

        assert client.delete(BASE + "/a").status_code == 204
        assert "a" not in registry.axes

    def test_unpublish_returns_the_axis_as_stored_afterwards(self, client, registry):
        registry.axes["a"] = stored(is_published=True)

        body = client.post(BASE + "/a/unpublish").json()

        assert (body["is_published"], body["display"]["label"]) == (False, "軸A")


class TestPayloadValidation:
    """本文の検証。拒否は422で、レジストリへは届かない。値の不変条件は`check_axis_definition`へ渡し、
    ルーターが持つのは配信の実装に照らす検証だけ。"""

    @pytest.mark.parametrize(
        ("fields", "reason"),
        [
            ({"shape": linear_shape("ghost")}, "無い材料・軸を指しています: ['ghost']"),
            (
                {"dedicated_way_value_layer": True, "shape": linear_shape(NUM_A, NUM_B)},
                "専用配信の軸は",
            ),
        ],
        ids=["値の不変条件に通らない", "配信実装の無い専用レイヤー"],
    )
    def test_rejected(self, client, registry, fields, reason):
        response = client.post(BASE, json=payload(**fields))

        assert response.status_code == 422
        assert reason in response.json()["detail"][0]["msg"]
        assert registry.calls == []

    @pytest.mark.parametrize(
        "fields",
        [{"shape": linear_shape(REFERENCED_AXIS)}, {"dedicated_way_value_layer": True}],
        ids=["今ある軸の参照", "配信実装のある材料1つの専用レイヤー"],
    )
    def test_accepted(self, client, fields):
        assert client.post(BASE, json=payload(**fields)).status_code == 201

    def test_the_delivery_check_sees_the_override_materials_too(self, client, seams):
        client.post(
            BASE,
            json=payload(
                dedicated_way_value_layer=True,
                priority_overrides=[{"material": BOOL_A, "equals": "true", "value": 0}],
            ),
        )

        assert seams["served"] == [[NUM_A, BOOL_A]]


class TestPreviews:
    def test_distribution_is_computed_from_the_repository_for_the_draft_shape(self, client, seams):
        body = client.post(BASE + "/preview-distribution", json={"shape": linear_shape(NUM_A)}).json()

        assert body == {
            "sample_ways": 3,
            "total_km": 1.5,
            "quantiles": {"p50": 2.0},
            "bins": [[0.0, 4.0, 1.0]],
            "zero_share": 0.25,
        }
        ((repository, shape),) = seams["distribution"]
        assert repository is REPOSITORY
        assert [t.material for t in shape.terms] == [NUM_A]

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ([], {"dropped_on_map": [8.0], "bands_on_map": [0, 1, 2]}),
            (
                [{"material": BOOL_A, "equals": "true", "value": 0.0}],
                {"dropped_on_map": [], "bands_on_map": [0, 1, 2, 3]},
            ),
        ],
        ids=["同じ点数へ写る境界は地図に出ない", "0次条件のある軸は地図に塗らないので全段が残る"],
    )
    def test_display_thresholds_answer_which_bands_the_map_drops_and_keeps(self, client, overrides, expected):
        """5より上は点数が100で平らなので、6と8の境界は地図では区別できない。"""
        shape = {
            "kind": "breakpoint_linear",
            "terms": [{"material": RAMP_NUM}],
            "breakpoints": [[0, 0], [5, 100], [10, 100]],
        }

        body = client.post(
            BASE + "/preview-display-thresholds",
            json={"axis_id": "a", "shape": shape, "priority_overrides": overrides, "thresholds": [1.0, 6.0, 8.0]},
        ).json()

        assert body == expected

    @pytest.mark.parametrize("thresholds", [[2.0, 1.0], [1.0, 1.0]], ids=["降順", "同値"])
    def test_display_thresholds_must_rise_strictly(self, client, thresholds):
        response = client.post(
            BASE + "/preview-display-thresholds",
            json={"axis_id": "a", "shape": linear_shape(NUM_A), "thresholds": thresholds},
        )

        assert response.status_code == 422
