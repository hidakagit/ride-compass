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
from typing import get_args

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.registry import (  # noqa: E402
    all_primary_attributes,
    reset_registry_for_testing,
)
from app.domain.registry_defaults import register_defaults  # noqa: E402
from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS  # noqa: E402
from app.domain.wind_grid import (  # noqa: E402
    WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG,
    WIND_GRID_DETAIL_MAX_POINTS,
    WIND_GRID_DETAIL_SPACING_DEG,
    WIND_GRID_SPACING_DEG,
)
from app.api.routers.routes import DEFAULT_DISTANCE_TOLERANCE_KM, MAX_ROUTE_DISTANCE_KM  # noqa: E402
from app.infrastructure.vector_tile import (  # noqa: E402
    ACCIDENT_LAYER_NAME,
    ROAD_SURFACE_LAYER_NAME,
    STOP_POI_LAYER_NAME,
)
from app.main import app  # noqa: E402
from app.domain.wind import ASSUMED_SPEED_KMH, MAX_ASSUMED_SPEED_KMH, MIN_ASSUMED_SPEED_KMH  # noqa: E402
from app.domain.hard_filters import DEFAULT_HARD_FILTERS, HARD_FILTER_NAMES  # noqa: E402
from app.domain.landcover import (  # noqa: E402
    LANDCOVER_CLASSES,
    LANDCOVER_TILE_MAX_ZOOM,
    LANDCOVER_TILE_MIN_ZOOM,
)
from app.services.landcover_tile_service import LANDCOVER_TILE_VERSION  # noqa: E402
from app.domain.jma_tile_specs import JMA_TILE_SPECS, effective_max_zoom  # noqa: E402
from app.domain.material_catalog import MATERIAL_CATALOG  # noqa: E402
from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM  # noqa: E402
from app.domain.traffic import STOP_POI_KINDS, SupplyPoiKind  # noqa: E402
from app.services.route_generator import SPLICED_ROUTE_ID, DEFAULT_MAX_ROUTES, MAX_ROUTES  # noqa: E402
from app.domain.tuning import client_tuning_values  # noqa: E402
from app.services.tile_version_service import TILE_SHAPES  # noqa: E402

GENERATED_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "generated"
OUTPUT_PATH = GENERATED_DIR / "openapi.json"
SURFACE_TAGS_PATH = GENERATED_DIR / "surface-tags.json"
REGION_TILE_CONFIG_PATH = GENERATED_DIR / "region-tile-config.json"
PRIMARY_ATTRIBUTES_PATH = GENERATED_DIR / "primary-attributes.json"
WIND_GRID_CONFIG_PATH = GENERATED_DIR / "wind-grid-config.json"
ROUTE_GENERATE_CONFIG_PATH = GENERATED_DIR / "route-generate-config.json"
JMA_TILE_CONFIG_PATH = GENERATED_DIR / "jma-tile-config.json"
POI_KINDS_PATH = GENERATED_DIR / "poi-kinds.json"
MATERIAL_CATALOG_PATH = GENERATED_DIR / "material-catalog.json"
LANDCOVER_CLASSES_PATH = GENERATED_DIR / "landcover-classes.json"

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
            # **DBの中身から決まる世代はここへ書かない。** バッチが中身を作り直しても
            # デプロイは起きず、ビルド時の値は次のデプロイまで古いままになる。そちらは
            # `GET /api/axis-catalog`の`tile_versions`が実行時に配る
            # （`services/tile_version_service.py`）。
            # 下の`landcover.tile_version`だけは例外で、**コードとクラス定義だけから
            # 決まる**（DBを読まない）ためビルド時に確定する。実際に開いているラスタの
            # 構成はサーバー側のディスクキャッシュの鍵が持ち、URLには入らない
            # （環境ごとに違う値をビルド機の設定で固定してしまうため）。
            # 実行時に世代が配られる系統の名前。**frontendはこの一覧を手で持たず、
            # ここから照合する**——片側だけ系統を足すと、足りない側は「世代が揃った」と
            # 判定したまま配られない世代を待ち続ける（`regionApi.ts: TILE_KINDS`）。
            "tile_version_kinds": sorted(TILE_SHAPES),
            "road_surface": {"layer_name": ROAD_SURFACE_LAYER_NAME},
            "accident": {"layer_name": ACCIDENT_LAYER_NAME},
            "poi": {"stop_poi_layer_name": STOP_POI_LAYER_NAME},
            # 路面タイルを要求するズーム範囲。frontendのMapLibreソース設定
            # （minzoom/maxzoom）とタイル要求のガードがこの値を使う。手書きで複製すると、
            # backendだけ広げてもfrontendが要求せずレイヤーが黙って消える。
            "road_tile_min_zoom": ROAD_TILE_MIN_ZOOM,
            "road_tile_max_zoom": ROAD_TILE_MAX_ZOOM,
            # 土地被覆ラスタタイル。ズーム範囲は元データの分解能と読み取り量から
            # backendが決める（domain/landcover.py）。
            "landcover": {
                "tile_version": LANDCOVER_TILE_VERSION,
                "min_zoom": LANDCOVER_TILE_MIN_ZOOM,
                "max_zoom": LANDCOVER_TILE_MAX_ZOOM,
            },
        },
    )
    # 土地被覆のクラス（画素値・割合列・表示名・色）。地図タイルの塗りと同じレジストリから
    # 書き出し、frontendの凡例・区間インスペクタの表示名がこれを読む。
    _write_json(
        LANDCOVER_CLASSES_PATH,
        [
            {
                "value": cls.value,
                "percent_field": cls.percent_field,
                "label": cls.label,
                "color": cls.color,
                "painted": cls.painted,
            }
            for cls in LANDCOVER_CLASSES
        ],
    )
    # 停止要因POI・補給休憩POIのkind正準集合。frontendは色・ラベルを自分で持つが、
    # **キーの一覧はここから引く**——backendが6種目を足したときfrontendのbaseFilterが
    # 5値のままだと、その地物はフィルタに弾かれて地図から完全に消える（凡例にも出ないため
    # 「データが無い」としか見えない）。
    _write_json(
        POI_KINDS_PATH,
        {
            "stop": sorted(STOP_POI_KINDS),
            "supply": sorted(get_args(SupplyPoiKind)),
        },
    )
    # 軸スタジオが選べる公開材料の一覧。frontendは`GET /api/material-catalog`が失敗した
    # ときの静的フォールバックとして使う。手書きで複製していたころは、APIが落ちている
    # ときだけ古い選択肢が出るという気づきにくいドリフトが実際に発生していた。
    # value_labels（smoothness等の値→日本語ラベル）も含める——同じ対訳表をfrontendが
    # 独自に持つと、地図のポップアップと軸スタジオで同じ値の呼び方が食い違う。
    _write_json(
        MATERIAL_CATALOG_PATH,
        [
            {
                "material_id": spec.material_id,
                "label": spec.label,
                "description": spec.description,
                "dtype": spec.dtype,
                "unit": spec.unit,
                "value_labels": dict(spec.value_labels) if spec.value_labels else None,
            }
            for spec in MATERIAL_CATALOG.values()
        ],
    )
    # **軸そのものはここへ書き出さない。** 軸定義の正本は本番DBで、実行時の
    # `GET /api/axis-catalog`が配る。ビルド時に写しを持つと、API障害時に古い軸で
    # 地図が描かれ、伝播の失敗が見えなくなる。
    reset_registry_for_testing()
    register_defaults()
    _write_json(
        PRIMARY_ATTRIBUTES_PATH,
        # 一次属性カタログ（地図レイヤー階層の次数反転）。レジストリ
        # （`domain/registry.py`）だけから決まり、DBを読まない。各軸の
        # `primary_attribute_ids`は実行時の`GET /api/axis-catalog`が配るため、フロントは
        # この一覧のlabel（正式名）と突き合わせて1次↔2次の双方向導出ができる。
        [
            {"attr_id": attr.attr_id, "label": attr.label, "shared": attr.shared}
            for attr in all_primary_attributes()
        ],
    )
    # 風・降水延長予報の格子間隔（改善計画T198、統合レビュー2026-08-22指摘F-B）。
    # domain/wind_grid.pyの定数群をfrontend/src/components/Map/windLayer.tsが
    # 「値を合わせること」というコメントのみで手動複製していたため、他の生成物と同じ
    # 片側import方式へ揃える（APIレスポンス自体には間隔情報が含まれないため、フロント側は
    # このJSONから読む以外に値を知る手段がない設計にする）。
    # 気象庁タイルの要素ごとのズーム範囲（domain/jma_tile_specs.py）。frontendの
    # MapView.tsx: DYNAMIC_WEATHER_RENDERERSがmaxzoomを手書きせずここから受け取る。
    _write_json(
        JMA_TILE_CONFIG_PATH,
        {
            element_id: {
                "min_zoom": spec.min_zoom,
                "max_zoom": effective_max_zoom(spec),
                "zoom_use": spec.zoom_use,
                "max_native_zoom": spec.max_native_zoom,
                "verified": spec.verified,
            }
            for element_id, spec in JMA_TILE_SPECS.items()
        },
    )
    _write_json(
        WIND_GRID_CONFIG_PATH,
        {
            "spacing_deg": WIND_GRID_SPACING_DEG,
            "detail_spacing_deg": WIND_GRID_DETAIL_SPACING_DEG,
            "detail_allowed_spacings_deg": list(WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG),
            "detail_max_points": WIND_GRID_DETAIL_MAX_POINTS,
        },
    )
    # ルート生成距離の上限（改善計画T471、api/routers/routes.py: MAX_ROUTE_DISTANCE_KMの
    # コメント参照）。以前はfrontend側の複数ファイルが「100」を独立にハードコードしていた。
    # 改善計画T531: 周回候補の件数（max_routes）の上限・既定値も同じ経路でフロントへ渡す。
    _write_json(
        ROUTE_GENERATE_CONFIG_PATH,
        {
            "max_distance_km": MAX_ROUTE_DISTANCE_KM,
            "max_routes": MAX_ROUTES,
            "default_max_routes": DEFAULT_MAX_ROUTES,
            "default_assumed_speed_kmh": ASSUMED_SPEED_KMH,
            "default_distance_tolerance_km": DEFAULT_DISTANCE_TOLERANCE_KM,
            "spliced_route_id": SPLICED_ROUTE_ID,
            "min_assumed_speed_kmh": MIN_ASSUMED_SPEED_KMH,
            "max_assumed_speed_kmh": MAX_ASSUMED_SPEED_KMH,
            # フロントが使う較正値の**既定**（`domain/tuning.py`の宣言そのまま）。
            # 実際に効いている値はGET /api/axis-catalogが返し、これはそれを取れるまでの値。
            "client_tuning": client_tuning_values(),
            # 0次ハードフィルタのキー一覧と既定値。backendは`_check_filter_keys`で
            # **キー集合の完全一致**を要求するため、frontendが手書きで持っていると
            # 4つ目を足した瞬間にすべてのルート生成が422になる。
            "hard_filters": {
                "keys": sorted(HARD_FILTER_NAMES),
                "defaults": sorted(DEFAULT_HARD_FILTERS),
            },
        },
    )


if __name__ == "__main__":
    main()
