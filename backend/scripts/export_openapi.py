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

from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS  # noqa: E402
from app.domain.traffic import (  # noqa: E402
    DEFAULT_TRAFFIC_STRESS_RECIPE,
    TrafficStressRecipe,
    traffic_stress_level,
    traffic_stress_tile_ingredients,
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

# 交通ストレスのPython実装（domain/traffic.py: traffic_stress_level）とフロント実装
# （trafficStressExpression.ts）の相互検証用フィクスチャ（改善計画: 交通ストレスレシピ
# 外出し基盤）。backend/tests/test_traffic.pyの代表ケースを踏襲しつつ、材料タグ
# （cycleway_class/maxspeed_kmh/lanes_count/motor_vehicle_no/designation）の観点で
# 全分岐を1回ずつ踏むよう構成する。(highway, tags, is_designated, recipe_override)の
# タプルで持ち、recipe_overrideはNoneなら既定レシピを使う。
_TRAFFIC_STRESS_TEST_CASES: list[tuple[str | None, dict[str, str], bool, dict[str, object] | None]] = [
    ("cycleway", {}, False, None),
    ("residential", {}, False, None),
    ("tertiary", {}, False, None),
    ("secondary", {}, False, None),
    ("primary", {}, False, None),
    ("trunk", {}, False, None),
    ("motorway", {}, False, None),  # 判定基準に未登録→None
    (None, {}, False, None),  # highway自体が無い→None
    ("primary", {"motor_vehicle": "no"}, False, None),  # 固定1（他の補正より優先）
    ("primary", {"cycleway": "track"}, False, None),
    ("primary", {"cycleway": "lane"}, False, None),
    ("primary", {"cycleway": "shared_lane"}, False, None),
    ("primary", {"maxspeed": "30"}, False, None),
    ("tertiary", {"maxspeed": "60"}, False, None),
    ("tertiary", {"lanes": "4"}, False, None),
    ("primary", {"lanes": "1"}, False, None),
    # コードレビューで発覚したlanes/maxspeed="0"の無効値ケース（値>0のみ有効、
    # road_graph_repository.pyのSQL側と挙動を合わせた回帰確認）。
    ("primary", {"lanes": "0"}, False, None),
    ("primary", {"maxspeed": "0"}, False, None),
    ("cycleway", {"cycleway": "track", "maxspeed": "20"}, False, None),  # 下限1でクランプ
    ("primary", {"maxspeed": "80", "lanes": "6"}, False, None),  # raw=6、上限5でクランプ
    ("residential", {}, True, None),  # 指定路線+1
    ("primary", {}, True, None),  # 指定路線+1でraw=5、上限5ちょうど（改善計画: 交通ストレス5段階化）
    ("primary", {"motor_vehicle": "no"}, True, None),  # 指定路線+motor_vehicle=noは1固定
    # レシピ上書き（研究モード相当）でも一致することを確認する。
    (
        "secondary",
        {},
        False,
        {**DEFAULT_TRAFFIC_STRESS_RECIPE.model_dump(), "base_by_highway": {"secondary": 2}},
    ),
]


def _traffic_stress_test_cases() -> list[dict[str, object]]:
    cases = []
    for highway, tags, is_designated, recipe_override in _TRAFFIC_STRESS_TEST_CASES:
        recipe = TrafficStressRecipe(**recipe_override) if recipe_override else None
        cases.append(
            {
                "properties": traffic_stress_tile_ingredients(highway, tags, is_designated),
                "recipe": recipe_override,
                "expected_level": traffic_stress_level(highway, tags, is_designated, recipe),
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
    # 交通ストレスの既定レシピ（domain/traffic.py: TrafficStressRecipe）。フロントの
    # trafficStressExpression.ts（地図表示用のMapLibre expression）が既定値をこのJSONから
    # 読み、Python側とのドリフトをCI（trafficStressExpression.test.ts）で検知する
    # （手動同期ペアを作らない設計原則1）。
    _write_json(TRAFFIC_STRESS_RECIPE_PATH, DEFAULT_TRAFFIC_STRESS_RECIPE.model_dump())
    # traffic_stress_level()を実際に実行して得た(材料タグ, レシピ, 期待値)の組。
    # trafficStressExpression.test.tsがこのJSONを読み、同じ入力でJS実装が同じ結果を返すかを
    # 検証する（旧test_road_graph_repository.pyのSQL⇔Python整合性テストに代わる、
    # Python⇔JS間の実ドリフト検知。ハードコードした期待値ではなくPythonの実行結果を都度
    # 書き出すため、traffic_stress_breakdownのロジックが変わればこのJSONも追従し、
    # JS側のミラー実装が古いままなら再生成後にテストが落ちる）。
    _write_json(TRAFFIC_STRESS_TEST_CASES_PATH, _traffic_stress_test_cases())


if __name__ == "__main__":
    main()
