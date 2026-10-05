"""`api/routers/axis_catalog.py`——公開軸の一覧（`GET /api/axis-catalog`、認可不要）。

ここで見るもの: 公開軸だけを配ること、軸ごとの欄へ domain の導出を受け渡すこと、domain に低い層の
テストが無い導出（気象のチップ・生値の単位・材料の内訳・専用配信の条件・画面へ配る較正値）の結果、
実行時の換算係数を地図の塗る式がタイルのプロパティ名で引けること。

ここで見ないもの:
- 地図表示の導出と段のラベル → `test_axis_display.py`、一次属性 → `test_axis_hierarchy.py`、
  塗る値の種類と単位 → `test_dynamic_way_values.py`
- 換算係数を収録年から導くこと → `test_material_catalog.py`
- タイルの世代 → `test_derived_data_revision_service.py`・`test_derived_data_meta.py`
- 軸の項目を応答へそのまま写すこと（表示名・重み・チップの欄等）——書き写しで、判断が無い
- 画面へ配る較正値の顔ぶれ（`tuning.py: client_tuning_values`）——同じ関数がビルド時生成物の`client_tuning`も書き、
  CI がその差分を落とす。画面が読む id は`frontend/src/lib/axisCatalog.ts: CLIENT_TUNING_IDS`が生成物の id に型で縛るので、
  配る集合から抜けると型検査で落ちる（余分に配っても画面は壊れない）
"""

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_region_service
from app.domain import tuning
from app.domain.axis_definitions import (
    AxisDefinition,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
)
from app.domain.material_catalog import MATERIAL_CATALOG, SURFACE_ESTIMATE
from app.infrastructure.derived_data_meta import DataRevisions
from app.main import app
from app.services.region_service import RegionService
from tests.axis_system_fixture import axis_definition, replaced_axis_definitions

#: カタログが配る軸。1本ごとに、カタログの別の出し分けを通す性質を持たせる。
CATALOG_AXES: dict[str, AxisDefinition] = {
    # 単一材料の絶対値を評価する軸（地図は符号付きの生値を塗り、生値の単位が定まる）。
    "axis_way_value_signed": AxisDefinition(
        axis_id="axis_way_value_signed",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="gradient_percent")],
            preprocess="abs",
            breakpoints=[(0.0, 0.0), (5.0, 50.0), (10.0, 100.0)],
        ),
        default_weight=0.2,
        label="軸グ",
        is_published=True,
    ),
    # 得点を塗る軸。
    "axis_way_value_scored": AxisDefinition(
        axis_id="axis_way_value_scored",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="wind_drag_ratio")],
            breakpoints=[(-1.0, 0.0), (0.0, 20.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="軸ウ",
        is_published=True,
    ),
    # 分類のshape。地図表示を導出できる。
    "axis_categorical": AxisDefinition(
        axis_id="axis_categorical",
        shape=CategoricalShape(material=SURFACE_ESTIMATE, mapping={"paved": 0.0, "gravel": 80.0}),
        default_weight=0.2,
        label="軸カ",
        is_published=True,
    ),
    # 重みの違う材料を足す軸（和の単位が定まらない）。
    "axis_optional_terms": AxisDefinition(
        axis_id="axis_optional_terms",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="poi_signal_per_km", weight=1.0, required=False),
                MaterialTerm(material="poi_level_crossing_per_km", weight=1.5, required=False),
                MaterialTerm(material="poi_stop_per_km", weight=0.3, required=False),
                MaterialTerm(material="poi_crossing_per_km", weight=0.0, required=False),
            ],
            breakpoints=[(0.0, 0.0), (1.0, 50.0), (4.0, 100.0)],
        ),
        default_weight=0.2,
        label="軸オ",
        is_published=True,
    ),
    # 実行時スケールを要する材料（収録年数で割る前の生値がタイルに焼かれている）を使う軸。
    "axis_runtime_scaled": AxisDefinition(
        axis_id="axis_runtime_scaled",
        shape=BreakpointLinearShape(
            terms=[MaterialTerm(material="accident_count_per_km_year")],
            breakpoints=[(0.0, 0.0), (1.0, 100.0)],
        ),
        default_weight=0.1,
        label="軸ラ",
        is_published=True,
    ),
    # 真偽の材料を符号の違う重みで合成する軸（材料まで分解した内訳を持つ）。
    "axis_boolean_terms": AxisDefinition(
        axis_id="axis_boolean_terms",
        shape=BreakpointLinearShape(
            terms=[
                MaterialTerm(material="lit", weight=-50.0),
                MaterialTerm(material="has_tunnel", weight=50.0),
            ],
            breakpoints=[(-50.0, 0.0), (50.0, 100.0)],
        ),
        default_weight=0.0,
        label="軸ナ",
        is_published=True,
    ),
}


@pytest.fixture
def catalog_axes():
    with replaced_axis_definitions(CATALOG_AXES):
        yield


class _CatalogRepository:
    """`/api/axis-catalog`が`RegionService`越しに読むDBの口（データの世代・事故の収録年）の代役。"""

    def __init__(self, accident_years: list[int] | None = None):
        self._accident_years = accident_years or []

    async def get_data_revisions(self):
        return DataRevisions(derived=None, imported=0)

    async def get_accident_years(self):
        return self._accident_years


@pytest.fixture
def client():
    """`/api/axis-catalog`を叩く口。このファイルの検証対象は軸カタログの内容で、DBの値は見ない。

    `/api/axis-catalog`は`tile_runtime_scales`（事故の収録年数）とタイル世代を出すためだけに
    `RegionService`を経由する。実DBが繋がる環境ではリクエストごとに接続を開き、
    `TestClient`のイベントループをまたいだasyncpg接続がGCされる際にキャンセル用の
    コルーチンが未awaitのまま残る（`RuntimeWarning: coroutine 'Connection._cancel' was
    never awaited`）。DBの口を代役へ固定して、DBの有無でこのファイルの経路が変わらないようにする。
    """
    app.dependency_overrides[get_region_service] = lambda: RegionService(repository=_CatalogRepository())
    yield TestClient(app)
    app.dependency_overrides.pop(get_region_service, None)


def _entries(client) -> dict[str, dict]:
    return {entry["axis_id"]: entry for entry in client.get("/api/axis-catalog").json()["axes"]}


def test_only_the_published_axes_are_served_without_auth(client):
    """下書きの軸が一般の画面へ漏れると、まだ固まっていない軸を利用者が選び、変えも消せもしなくなる。"""
    draft = axis_definition("draft_axis", is_published=False)
    with replaced_axis_definitions({**CATALOG_AXES, draft.axis_id: draft}):
        assert set(_entries(client)) == set(CATALOG_AXES)


def test_each_axis_carries_what_the_domain_derives_for_it(client, catalog_axes):
    """導出の入力違いは domain のテストが持つ。ここは軸ごとの欄へ結果が届くことだけを見る。"""
    entries = _entries(client)

    categorical = entries["axis_categorical"]
    assert categorical["display"]["tile_inputs"][0]["property"] == MATERIAL_CATALOG[SURFACE_ESTIMATE].tile_property
    assert categorical["primary_attribute_ids"] == ["surface"]
    signed = entries["axis_way_value_signed"]
    assert (signed["map_value"], signed["map_value_unit"]) == (
        {"kind": "signed_material", "material": "gradient_percent"},
        "%",
    )


def test_get_axis_catalog_names_the_weather_chip_that_shows_a_dynamic_material(client, catalog_axes):
    # 風の材料は一次属性を持たないが、同じ格子の風を描く気象のチップが元データを見せる。
    entries = _entries(client)

    assert entries["axis_way_value_scored"]["weather_layer_groups"] == ["windVector"]
    assert entries["axis_categorical"]["weather_layer_groups"] == []


def _runtime_scaled_tile_properties(body) -> set[str]:
    return {
        tile_input["property"]
        for entry in body["axes"]
        for tile_input in entry["display"]["tile_inputs"]
        if tile_input["needs_runtime_scale"]
    }


def test_every_runtime_scaled_tile_input_finds_its_scale_by_its_tile_property(client, catalog_axes):
    """換算係数は材料の宣言から導かれ、地図が塗る値の式はタイルのプロパティ名でそれを引く。"""
    app.dependency_overrides[get_region_service] = lambda: RegionService(
        repository=_CatalogRepository(accident_years=[2019, 2020, 2021, 2022, 2023, 2024])
    )

    body = client.get("/api/axis-catalog").json()

    scaled = _runtime_scaled_tile_properties(body)
    assert scaled
    assert {p: body["tile_runtime_scales"].get(p) for p in scaled} == {p: pytest.approx(1 / 6) for p in scaled}


def test_get_axis_catalog_carries_the_calibration_values_the_client_needs(client, monkeypatch):
    """フロントが使う較正値は、このカタログが**いま効いている値**で運ぶ。

    ビルド時生成物（route-generate-config.json）だけで配ると、管理画面から変えても
    次のデプロイまで画面に届かない。
    """
    param_id = sorted(client.get("/api/axis-catalog").json()["client_tuning"])[0]
    monkeypatch.setitem(tuning.TUNING_VALUES, param_id, 9.5)

    assert client.get("/api/axis-catalog").json()["client_tuning"][param_id] == 9.5


# 地図が専用配信の要求へ載せるクエリパラメータは、軸が参照する材料の配信サービスが受け取る条件から決まる。
# 風は時刻を省略できても載せる（利用者が選んだ時刻の風を塗る）。専用配信を持たない軸には何も載せない。
@pytest.mark.parametrize(("dedicated", "conditions"), [(True, {"at", "bearing_deg", "speed_kmh"}), (False, set())])
def test_get_axis_catalog_names_the_query_params_the_map_sends_for_a_dedicated_axis(client, dedicated, conditions):
    axis = axis_definition(
        "axis_any_name", material="wind_drag_ratio", is_published=True, dedicated_way_value_layer=dedicated
    )
    with replaced_axis_definitions({axis.axis_id: axis}):
        response = client.get("/api/axis-catalog")

    (entry,) = response.json()["axes"]
    assert set(entry["dynamic_way_value_conditions"]) == conditions


# 「向きで決まらない」の凡例の行は、配信がその道を返しうる軸だけが持つ（返さない軸に出すと、どの道も入らない行になる）。
@pytest.mark.parametrize(
    ("material", "dedicated", "undetermined"),
    [("gradient_percent", True, True), ("wind_drag_ratio", True, False), ("gradient_percent", False, False)],
)
def test_get_axis_catalog_tells_which_dedicated_axis_can_leave_a_road_undetermined_by_the_bearing(
    client, material, dedicated, undetermined
):
    axis = axis_definition("axis_any_name", material=material, is_published=True, dedicated_way_value_layer=dedicated)
    with replaced_axis_definitions({axis.axis_id: axis}):
        response = client.get("/api/axis-catalog")

    (entry,) = response.json()["axes"]
    assert entry["dynamic_way_value_undetermined_by_bearing"] is undetermined


def test_get_axis_catalog_includes_raw_value_unit(client, catalog_axes):
    # 得点の隣へ生値を出すための単位（domain/axis_raw_value.py: raw_value_unit）。
    # 勾配は単一材料をそのまま使うので%、内部軸を合成する軸は単位が定まらずnull。
    entries = _entries(client)
    assert entries["axis_way_value_signed"]["raw_value_unit"] == "%"
    # 材料ごとに重みを変えて足す軸は、和がどの単位でも読めない——nullになる。
    assert entries["axis_optional_terms"]["raw_value_unit"] is None


def test_get_axis_catalog_includes_material_breakdown(client, catalog_axes):
    # 単位が定まらない軸は、材料まで分解した内訳を持つ（得点だけでは軸単体で判断できない）。並びは正規化重みの降順で、フロントは並べ替えを持たない。
    entries = _entries(client)
    # 単位が定まる軸は分解しない（軸単位の生値で足りる）。
    assert entries["axis_way_value_signed"]["material_breakdown"] == []
    night = entries["axis_boolean_terms"]["material_breakdown"]
    assert [(entry["material_id"], entry["share"]) for entry in night] == [("lit", 0.5), ("has_tunnel", 0.5)]
    # 真偽値材料に対訳は要らない（走行中に見る画面へ不要なデータを載せない）。
    assert night[0]["value_labels"] == {}
