"""FastAPIアプリのOpenAPIスキーマをJSONへ書き出す（docs/improvement-plan.md T4）。

フロントエンドの型生成（openapi-typescript、frontend/package.jsonのgenerate:api）の
入力になる。出力先をfrontend/src/types/generated/へ置いてコミットするのは、
(1) フロントの型生成・ビルドがbackendの起動なしで完結する、
(2) CIのドリフト検知（backendから再生成→git diffで差分が無いことを確認）が成立する、
の2点のため。domain/route.py等のレスポンスモデルを変更したら、このスクリプトと
frontendのnpm run generate:apiを実行して生成物を同じコミットに含めること
（手動同期ペアを作らない方針。docs/design-review-2026-08-15.md 設計原則1・3）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\export_openapi.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.recipe import (  # noqa: E402
    DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE,
    DEFAULT_ROAD_SUITABILITY_RECIPE,
    ROAD_SUITABILITY_BASE_BY_HIGHWAY,
    MotorVehicleDensityRecipe,
    RoadSuitabilityRecipe,
)
from app.domain.registry import all_axes, all_primary_attributes, reset_registry_for_testing  # noqa: E402
from app.domain.registry_defaults import register_defaults  # noqa: E402
from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS  # noqa: E402
from app.domain.traffic import (  # noqa: E402
    DEFAULT_CAR_STRESS_RECIPE,
    CarStressRecipe,
    car_stress_level,
    car_stress_tile_ingredients,
)
from app.domain.wind_grid import (  # noqa: E402
    WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG,
    WIND_GRID_DETAIL_MAX_POINTS,
    WIND_GRID_DETAIL_SPACING_DEG,
    WIND_GRID_SPACING_DEG,
)
from app.infrastructure.vector_tile import (  # noqa: E402
    ACCIDENT_LAYER_NAME,
    ROAD_SURFACE_LAYER_NAME,
    STOP_POI_LAYER_NAME,
)
from app.main import app  # noqa: E402
from app.services.accident_service import ACCIDENT_TILE_VERSION  # noqa: E402
from app.services.region_service import POI_TILE_VERSION, ROAD_SURFACE_TILE_VERSION  # noqa: E402

GENERATED_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "generated"
OUTPUT_PATH = GENERATED_DIR / "openapi.json"
SURFACE_TAGS_PATH = GENERATED_DIR / "surface-tags.json"
REGION_TILE_CONFIG_PATH = GENERATED_DIR / "region-tile-config.json"
TRAFFIC_STRESS_RECIPE_PATH = GENERATED_DIR / "traffic-stress-recipe.json"
TRAFFIC_STRESS_TEST_CASES_PATH = GENERATED_DIR / "traffic-stress-test-cases.json"
ROAD_SUITABILITY_RECIPE_PATH = GENERATED_DIR / "road-suitability-recipe.json"
MOTOR_VEHICLE_DENSITY_RECIPE_PATH = GENERATED_DIR / "motor-vehicle-density-recipe.json"
AXIS_CATALOG_PATH = GENERATED_DIR / "axis-catalog.json"
WIND_GRID_CONFIG_PATH = GENERATED_DIR / "wind-grid-config.json"

# 車ストレスのPython実装（domain/traffic.py: car_stress_level）とフロント実装
# （trafficStressExpression.ts）の相互検証用フィクスチャ（改善計画: 交通ストレスレシピ
# 外出し基盤・車との近さ材料の共有元化）。backend/tests/test_traffic.pyの代表ケースを
# 踏襲しつつ、材料タグ（cycleway_class/maxspeed_kmh/lanes_count/motor_vehicle_no/
# designation）の観点で全分岐を1回ずつ踏むよう構成する。
# (highway, tags, is_designated, recipe_override, road_suitability_recipe_override,
# motor_vehicle_density_recipe_override)の6-tupleで持ち、Noneならそれぞれ既定レシピを使う。
_CAR_STRESS_TEST_CASES: list[
    tuple[str | None, dict[str, str], bool, dict[str, object] | None, dict[str, object] | None, dict[str, object] | None]
] = [
    ("cycleway", {}, False, None, None, None),
    ("residential", {}, False, None, None, None),
    ("tertiary", {}, False, None, None, None),
    ("secondary", {}, False, None, None, None),
    ("primary", {}, False, None, None, None),
    ("trunk", {}, False, None, None, None),
    ("motorway", {}, False, None, None, None),  # 判定基準に未登録→None
    (None, {}, False, None, None, None),  # highway自体が無い→None
    ("primary", {"motor_vehicle": "no"}, False, None, None, None),  # 固定1（他の補正より優先）
    ("primary", {"cycleway": "track"}, False, None, None, None),
    ("primary", {"cycleway": "lane"}, False, None, None, None),
    ("primary", {"cycleway": "shared_lane"}, False, None, None, None),
    ("primary", {"maxspeed": "30"}, False, None, None, None),
    ("tertiary", {"maxspeed": "60"}, False, None, None, None),
    ("tertiary", {"lanes": "4"}, False, None, None, None),
    ("primary", {"lanes": "1"}, False, None, None, None),
    # lanes_lowは分離自転車道（cycleway=track）区間では該当しない（domain/traffic.py:
    # car_stress_breakdown参照）。track単体の-2のみが効く。
    ("primary", {"lanes": "1", "cycleway": "track"}, False, None, None, None),
    # コードレビューで発覚したlanes/maxspeed="0"の無効値ケース（値>0のみ有効、
    # road_graph_repository.pyのSQL側と挙動を合わせた回帰確認）。
    ("primary", {"lanes": "0"}, False, None, None, None),
    ("primary", {"maxspeed": "0"}, False, None, None, None),
    ("cycleway", {"cycleway": "track", "maxspeed": "20"}, False, None, None, None),  # 下限1でクランプ
    ("primary", {"maxspeed": "80", "lanes": "6"}, False, None, None, None),  # raw=6、上限5でクランプ
    ("residential", {}, True, None, None, None),  # 指定路線+1
    ("primary", {}, True, None, None, None),  # 指定路線+1でraw=5、上限5ちょうど（改善計画: 交通ストレス5段階化）
    ("primary", {"motor_vehicle": "no"}, True, None, None, None),  # 指定路線+motor_vehicle=noは1固定
    # 道路適正レシピの上書き（研究モード相当）でも一致することを確認する（改善計画: 車との
    # 近さ材料の共有元化。旧base_by_highway上書きケースをこちらへ移設）。
    ("secondary", {}, False, None, {**DEFAULT_ROAD_SUITABILITY_RECIPE.model_dump(), "base_by_highway": {**ROAD_SUITABILITY_BASE_BY_HIGHWAY, "secondary": 2}}, None),
    # 自動車密度レシピの上書きでも一致することを確認する。
    (
        "tertiary",
        {"maxspeed": "40"},
        False,
        None,
        None,
        {**DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE.model_dump(), "maxspeed_high_threshold": 40},
    ),
    # 3レシピ（軸固有・道路適正・自動車密度）を同時に上書きしても正しく合成されることを
    # 確認する（フロント側ミラー実装の合成検証、改善計画: 車との近さ材料の共有元化）。
    (
        "secondary",
        {"lanes": "1"},
        True,
        {**DEFAULT_CAR_STRESS_RECIPE.model_dump(), "lanes_low_adjustment": -3},
        {**DEFAULT_ROAD_SUITABILITY_RECIPE.model_dump(), "base_by_highway": {**ROAD_SUITABILITY_BASE_BY_HIGHWAY, "secondary": 2}},
        {**DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE.model_dump(), "designation_adjustment": 2},
    ),
]


def _car_stress_test_cases() -> list[dict[str, object]]:
    cases = []
    for (
        highway,
        tags,
        is_designated,
        recipe_override,
        road_suitability_recipe_override,
        motor_vehicle_density_recipe_override,
    ) in _CAR_STRESS_TEST_CASES:
        recipe = CarStressRecipe(**recipe_override) if recipe_override else None
        road_suitability_recipe = (
            RoadSuitabilityRecipe(**road_suitability_recipe_override) if road_suitability_recipe_override else None
        )
        motor_vehicle_density_recipe = (
            MotorVehicleDensityRecipe(**motor_vehicle_density_recipe_override)
            if motor_vehicle_density_recipe_override
            else None
        )
        cases.append(
            {
                "properties": car_stress_tile_ingredients(highway, tags, is_designated),
                "recipe": recipe_override,
                "road_suitability_recipe": road_suitability_recipe_override,
                "motor_vehicle_density_recipe": motor_vehicle_density_recipe_override,
                "expected_level": car_stress_level(
                    highway, tags, is_designated, recipe, road_suitability_recipe, motor_vehicle_density_recipe
                ),
            }
        )
    return cases


def _write_json(path: Path, data: dict | list) -> None:
    # ensure_ascii=False: 日本語のdescription（レート制限メッセージ等）を可読なまま残す。
    # indent固定・末尾改行あり: 再生成のdiffが内容の変化だけを反映するようにする。
    # newline="\n"固定: Windowsで実行してもCRLFにならないようにする（CI（Linux）の
    # ドリフト検知と生成環境によらずバイト単位で一致させるため）。
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path}")


def main() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, app.openapi())
    # 路面語彙の正準タグ集合（domain/road.py）。フロントの表示グループ定義
    # （roadFilterAxes.ts）が正準分類とずれていないことをroadFilterAxes.test.tsが
    # このJSONと突き合わせて検証する（改善計画T7。地図の色とルート評価の食い違い防止）。
    _write_json(
        SURFACE_TAGS_PATH,
        {"good": sorted(GOOD_OSM_SURFACE_TAGS), "bad": sorted(BAD_OSM_SURFACE_TAGS)},
    )
    # 地域ベクタタイルのレイヤー名・世代（改善計画T19、T50でaccidentキー・T54でpoiキーへ拡張。
    # T97でpoi.intersection_layer_nameを削除、交差点密度レイヤーの配信自体を撤去）。
    # フロントの手書き定数（MapView.tsx: ROAD_TILE_SOURCE_LAYER/ACCIDENT_TILE_SOURCE_LAYER/
    # STOP_POI_SOURCE_LAYER、regionApi.ts: 各tileUrl()の?v=）がこのJSONとregionApi.test.tsで
    # 突き合わされる（CIのapi-contractジョブがドリフト検知）。
    _write_json(
        REGION_TILE_CONFIG_PATH,
        {
            "road_surface": {"layer_name": ROAD_SURFACE_LAYER_NAME, "tile_version": ROAD_SURFACE_TILE_VERSION},
            "accident": {"layer_name": ACCIDENT_LAYER_NAME, "tile_version": ACCIDENT_TILE_VERSION},
            "poi": {
                "stop_poi_layer_name": STOP_POI_LAYER_NAME,
                "tile_version": POI_TILE_VERSION,
            },
        },
    )
    # 車ストレスの既定レシピ（domain/traffic.py: CarStressRecipe）。フロントの
    # trafficStressExpression.ts（地図表示用のMapLibre expression）が既定値をこのJSONから
    # 読み、Python側とのドリフトをCI（trafficStressExpression.test.ts）で検知する
    # （手動同期ペアを作らない設計原則1）。
    _write_json(TRAFFIC_STRESS_RECIPE_PATH, DEFAULT_CAR_STRESS_RECIPE.model_dump())
    # car_stress_level()を実際に実行して得た(材料タグ, レシピ, 期待値)の組。
    # trafficStressExpression.test.tsがこのJSONを読み、同じ入力でJS実装が同じ結果を返すかを
    # 検証する（旧test_road_graph_repository.pyのSQL⇔Python整合性テストに代わる、
    # Python⇔JS間の実ドリフト検知。ハードコードした期待値ではなくPythonの実行結果を都度
    # 書き出すため、car_stress_breakdownのロジックが変わればこのJSONも追従し、
    # JS側のミラー実装が古いままなら再生成後にテストが落ちる）。
    _write_json(TRAFFIC_STRESS_TEST_CASES_PATH, _car_stress_test_cases())
    # 「車との近さ」(N2)を構成する共有レシピ2つの既定値（domain/recipe.py:
    # RoadSuitabilityRecipe/MotorVehicleDensityRecipe、改善計画: 車との近さ材料の
    # 共有元化）。車ストレスのMapLibre expressionが読む。
    _write_json(ROAD_SUITABILITY_RECIPE_PATH, DEFAULT_ROAD_SUITABILITY_RECIPE.model_dump())
    _write_json(MOTOR_VEHICLE_DENSITY_RECIPE_PATH, DEFAULT_MOTOR_VEHICLE_DENSITY_RECIPE.model_dump())
    # 二次軸カタログ（改善計画T145b「事実はタイルに、解釈はクライアントに」）。
    # レジストリ（domain/registry_defaults.py）の全軸と表示宣言（AxisDisplaySpec）を
    # 書き出し、フロントの汎用レイヤーファクトリ（axisLayers.ts）がkind="ramp"の軸から
    # レイヤー・凡例を自動生成する。新しい軸はレジストリへの登録（＋タイルへの事実の
    # 焼き込み）だけで地図レイヤーが現れる。
    # 一次属性カタログ（改善計画T163、地図レイヤー階層の次数反転）も同じレジストリから
    # 書き出す。各軸のinputsは既にattr_idのリストとして含まれているため、
    # フロントはこのprimary_attributesのlabel（正式名）とinputsの組み合わせだけで
    # 2次→1次・1次→2次の双方向導出ができる（片側import、設計原則2）。
    reset_registry_for_testing()
    register_defaults()
    _write_json(
        AXIS_CATALOG_PATH,
        {
            "axes": [
                {
                    "axis_id": axis.axis_id,
                    "inputs": axis.inputs,
                    "output_range": list(axis.output_range),
                    "display": axis.display.model_dump() if axis.display is not None else None,
                }
                for axis in all_axes()
            ],
            "primary_attributes": [
                {
                    "attr_id": attr.attr_id,
                    "label": attr.label,
                    "shared": attr.shared,
                }
                for attr in all_primary_attributes()
            ],
        },
    )
    # 風・降水延長予報の格子間隔（改善計画T198、統合レビュー2026-08-22指摘F-B）。
    # domain/wind_grid.pyの定数群をfrontend/src/components/Map/windLayer.tsが
    # 「値を合わせること」というコメントのみで手動複製していたため、他の生成物と同じ
    # 片側import方式へ揃える（APIレスポンス自体には間隔情報が含まれないため、フロント側は
    # このJSONから読む以外に値を知る手段がない設計にする）。
    _write_json(
        WIND_GRID_CONFIG_PATH,
        {
            "spacing_deg": WIND_GRID_SPACING_DEG,
            "detail_spacing_deg": WIND_GRID_DETAIL_SPACING_DEG,
            "detail_allowed_spacings_deg": list(WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG),
            "detail_max_points": WIND_GRID_DETAIL_MAX_POINTS,
        },
    )


if __name__ == "__main__":
    main()
