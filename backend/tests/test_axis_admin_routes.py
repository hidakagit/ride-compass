"""`api/routers/axis_admin.py`——軸スタジオの管理API（書き込み時の検証・例外の変換）。

ここで見ないもの:
- 軸そのものの不変条件（折れ点・段の境界・段ラベル）と公開の不変性・材料の排他、軸の外（材料カタログ・
  ほかの軸）に照らす値の不変条件（`check_axis_definition`）の中身 → `test_axis_definitions.py`
- 書き込みの本体（DBへの反映と`AXIS_DEFINITIONS`の差し替え） → `test_axis_registry_service.py`
- 地図表示の導出・段が落ちるかの判定 → `test_axis_display.py`
- 下書きの点数の計算と段の境界の並びの検証の入力違い → `test_axis_definitions.py`
- 分布の計算 → `test_axis_preview_service.py`
- 認可（どの口もBasic認証の依存を持つこと・その依存が拒むこと） → `test_admin_route_authorization.py`
- DBの失敗の503 → `test_admin_db_unavailable.py`

ここで見るのは、口ごとの受け渡し（無い軸・断られた書き込みを状態コードへ変えること・
応答に地図表示を添えること）と、ルーターが自分で持つ検証（URLと本文の軸の一致・配信の実装の有無）。

**ルーターが名前空間に持つ外向きの参照は差し替える**——軸の集合・配信実装の有無・分布の計算（DB）。
どれも読むだけなので、応答を差し替えるだけで呼ばれ方は見ない。
地図表示の導出（domain）と材料カタログは本物を通し、材料は性質ごとに本物のカタログから選ぶ。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import axis_admin
from app.domain.axis_definitions import REQUEST_DYNAMIC_MATERIAL_IDS
from app.domain.axis_display import axis_display_for
from app.domain.material_catalog import MATERIAL_CATALOG
from app.domain.value_distribution import ValueDistribution
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


def display_of(definition):
    """応答に添える地図の表示（JSON の形）。"""
    return axis_display_for(definition).model_dump(mode="json")


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
        return [call for call in self.calls if call[0] != "list_all"]

    async def list_all(self):
        self._record("list_all")
        return dict(self.axes)

    async def create(self, definition):
        self._record("create", definition)
        self.axes[definition.axis_id] = definition
        return dict(self.axes)

    async def update(self, axis_id, definition):
        self._record("update", axis_id, definition)
        if axis_id not in self.axes:
            raise KeyError(axis_id)
        self.axes[axis_id] = definition
        return dict(self.axes)

    async def delete(self, axis_id):
        self._record("delete", axis_id)
        self.axes.pop(axis_id)

    async def unpublish(self, axis_id):
        self._record("unpublish", axis_id)
        self.axes[axis_id] = self.axes[axis_id].model_copy(update={"is_published": False})
        return dict(self.axes)


@pytest.fixture
def registry():
    return FakeAxisRegistry()


@pytest.fixture
def seams(monkeypatch):
    def served_dedicated_way_value_material(materials):
        return NUM_A if list(materials) == [NUM_A] else None

    async def axis_raw_value_distribution(repository, shape):
        return ValueDistribution(
            sample_ways=3, total_km=1.5, quantiles={"p50": 2.0}, bins=[(0.0, 4.0, 1.0)]
        )

    fakes = {
        "served_dedicated_way_value_material": served_dedicated_way_value_material,
        "axis_raw_value_distribution": axis_raw_value_distribution,
    }
    for name, fake in fakes.items():
        monkeypatch.setattr(axis_admin, name, bound(getattr(axis_admin, name), fake))
    monkeypatch.setattr(axis_admin, "AXIS_DEFINITIONS", {REFERENCED_AXIS: stored(REFERENCED_AXIS)})


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


class TestRead:
    def test_list_returns_every_axis_with_its_map_display(self, client, registry):
        registry.axes = {"a": stored("a"), "b": stored("b", label="軸B")}

        body = client.get(BASE).json()

        assert [(item["axis_id"], item["display"]) for item in body] == [
            ("a", display_of(registry.axes["a"])),
            ("b", display_of(registry.axes["b"])),
        ]

    def test_get_returns_the_axis_with_its_map_display(self, client, registry):
        registry.axes["a"] = stored()

        body = client.get(BASE + "/a").json()

        assert body["axis_id"] == "a"
        assert body["display"] == display_of(stored())

    def test_an_axis_whose_material_left_the_catalog_can_still_be_read(self, client, registry):
        """読み出しは保存済みの内容を返すだけで、書き込み時の検証をやり直さない。"""
        registry.axes["a"] = stored(shape=linear_shape("retired"))

        assert client.get(BASE + "/a").status_code == 200


class TestWrite:
    def test_create_stores_a_plain_axis_definition_and_returns_it_with_its_display(self, client, registry):
        """ペイロードの型のまま渡すと、公開後の見た目だけの更新を判定する等価比較が型の違いで
        常に不一致になる。"""
        response = client.post(BASE, json=payload())

        assert response.status_code == 201
        assert response.json()["display"] == display_of(stored())
        ((name, definition),) = registry.writes
        assert (name, type(definition)) == ("create", axis_admin.AxisDefinition)

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
        ("method", "path", "body"),
        [
            ("GET", BASE + "/a", None),
            ("PUT", BASE + "/a", payload()),
            ("DELETE", BASE + "/a", None),
            ("POST", BASE + "/a/unpublish", None),
        ],
    )
    def test_an_operation_on_an_unknown_axis_is_a_404(self, client, method, path, body):
        assert client.request(method, path, json=body).status_code == 404

    @pytest.mark.parametrize(
        ("method", "path", "body", "operation"),
        [
            ("POST", BASE, payload(), "create"),
            ("PUT", BASE + "/a", payload(), "update"),
            ("DELETE", BASE + "/a", None, "delete"),
        ],
    )
    def test_an_operation_refused_by_the_registry_is_a_409(self, client, registry, method, path, body, operation):
        registry.axes["a"] = stored()
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

        assert (body["is_published"], body["display"]) == (False, display_of(stored()))


class TestPayloadValidation:
    """本文の検証。拒否は422で、レジストリへは届かない。値の不変条件は`check_axis_definition`へ渡し、
    ルーターが持つのは配信の実装に照らす検証だけ。"""

    @pytest.mark.parametrize(
        ("fields", "reason"),
        [
            ({"shape": linear_shape("ghost")}, "存在しない材料・軸を指しています（ghost）"),
            (
                {"dedicated_way_value_layer": True, "shape": linear_shape(NUM_A, NUM_B)},
                "専用配信の軸は",
            ),
            (
                {
                    "dedicated_way_value_layer": True,
                    "priority_overrides": [{"material": BOOL_A, "equals": "true", "value": 0}],
                },
                "専用配信の軸は",
            ),
        ],
        ids=["値の不変条件に通らない", "配信実装の無い専用レイヤー", "0次条件の材料も数える専用レイヤー"],
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


class TestPreviews:
    def test_distribution_answers_what_was_computed_for_the_draft_shape(self, client):
        body = client.post(BASE + "/preview-distribution", json={"shape": linear_shape(NUM_A)}).json()

        assert body == {
            "sample_ways": 3,
            "total_km": 1.5,
            "quantiles": {"p50": 2.0},
            "bins": [[0.0, 4.0, 1.0]],
        }

    def test_display_thresholds_answer_which_bands_the_map_drops_and_keeps(self, client):
        """5より上は点数が100で平らなので、6と8の境界は地図では区別できない。"""
        shape = {
            "kind": "breakpoint_linear",
            "terms": [{"material": RAMP_NUM}],
            "breakpoints": [[0, 0], [5, 100], [10, 100]],
        }

        body = client.post(
            BASE + "/preview-display-thresholds",
            json={"axis_id": "a", "shape": shape, "thresholds": [1.0, 6.0, 8.0]},
        ).json()

        assert body == {"dropped_on_map": [8.0], "bands_on_map": [0, 1, 2]}

    def test_display_thresholds_must_rise_strictly(self, client):
        response = client.post(
            BASE + "/preview-display-thresholds",
            json={"axis_id": "a", "shape": linear_shape(NUM_A), "thresholds": [1.0, 1.0]},
        )

        assert response.status_code == 422

    def test_scores_of_a_draft_with_two_terms(self, client):
        """1つ目の項の材料の値ごとの点数は、ほかの項の材料が無い道を評価したときの点数である。"""
        shape = {
            "kind": "breakpoint_linear",
            "terms": [{"material": NUM_A, "weight": 2.0}, {"material": NUM_B, "required": False}],
            "preprocess": "abs",
            "breakpoints": [[0, 0], [10, 100]],
        }

        body = client.post(
            BASE + "/preview-scores",
            json={"shape": shape, "xs": [2.5, 20.0], "material_values": [-3.0, 1.0, 7.0]},
        ).json()

        assert body == {
            "scores": [25.0, 100.0],
            "material_points": [{"x": 6.0, "score": 60.0}, {"x": 2.0, "score": 20.0}, {"x": 14.0, "score": 100.0}],
        }
