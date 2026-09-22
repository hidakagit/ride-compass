"""FastAPIアプリのOpenAPIスキーマをJSONへ書き出す。

フロントエンドの型生成（openapi-typescript、frontend/package.jsonのgenerate:api）の
入力になる。出力先をfrontend/src/types/generated/へ置いてコミットするのは、
(1) フロントの型生成・ビルドがbackendの起動なしで完結する、
(2) CIのドリフト検知（backendから再生成→git diffで差分が無いことを確認）が成立する、
の2点のため。レスポンスモデルを変更したら、このスクリプトとfrontendの
npm run generate:apiを実行して生成物を同じコミットに含めること。

**この生成物は契約だけを運ぶ**（名前・型・required・enum）。散文は`_strip_prose`が
落とす——載せると、docstringを直しただけで生成物が動き、追従のコミットを要求される。
散文は実行中のアプリの`/docs`・`/openapi.json`が配るため失われない。

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
from app.domain.map_display import (  # noqa: E402
    MAP_LAYER_CATEGORIES,
    MAP_LAYER_IDS,
    MAP_LAYER_KINDS,
    MAP_LAYER_DATA_NATURES,
    MAP_LAYER_DATA_SOURCES,
    MAP_OVERLAY_GROUPS,
)
from app.domain.weather_display import (  # noqa: E402
    PRECIPITATION_COLOR_STOPS,
    RISK_LEVEL_COLORS,
    THUNDER_ACTIVITY_LEVELS,
    TORNADO_POTENTIAL_LEVELS,
    WIND_SPEED_COLOR_STOPS,
)
from app.domain.display_palette import (  # noqa: E402
    COMPARISON_SLOT_COLORS,
    EVALUATION_RAMP_ANCHORS,
    SEMANTIC_COLORS,
    resolved_display_axes,
)
from app.domain.gsi_tiles import (  # noqa: E402
    RELIEF_ATTRIBUTION,
    RELIEF_MAX_ZOOM,
    RELIEF_TILE_URL,
    TERRAIN_MAX_ZOOM,
    TERRAIN_TILE_URL,
)
from app.domain.terrain_rgb import TERRAIN_RGB_BASE_M, TERRAIN_RGB_UNIT_M  # noqa: E402
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
PRIMARY_ATTRIBUTES_PATH = GENERATED_DIR / "primaryAttributes.ts"
WIND_GRID_CONFIG_PATH = GENERATED_DIR / "wind-grid-config.json"
ROUTE_GENERATE_CONFIG_PATH = GENERATED_DIR / "route-generate-config.json"
JMA_TILE_CONFIG_PATH = GENERATED_DIR / "jma-tile-config.json"
POI_KINDS_PATH = GENERATED_DIR / "poi-kinds.json"
MATERIAL_CATALOG_PATH = GENERATED_DIR / "material-catalog.json"
LANDCOVER_CLASSES_PATH = GENERATED_DIR / "landcover-classes.json"
PALETTE_PATH = GENERATED_DIR / "palette.json"
WEATHER_SCALES_PATH = GENERATED_DIR / "weather-scales.json"
MAP_DISPLAY_PATH = GENERATED_DIR / "mapDisplay.ts"

def _strip_prose(node: object, *, keep: bool = False) -> object:
    """docstring由来の`description`・`summary`を落とす。

    応答オブジェクトの`description`だけは残す——OpenAPIが必須にしており、落とすと
    生成物が仕様を満たさなくなる（FastAPIが入れる"Successful Response"等の定型で、
    docstringとは無関係）。
    """
    if isinstance(node, dict):
        out: dict[str, object] = {}
        for key, value in node.items():
            if key in ("description", "summary") and not keep:
                continue
            if key == "responses" and isinstance(value, dict):
                out[key] = {code: _strip_prose(r, keep=True) for code, r in value.items()}
            elif key == "properties" and isinstance(value, dict):
                # ここのキーはキーワードではなく**フィールド名**。`description`という名前の
                # フィールドを持つモデルがあり、落とすと契約からフィールドが消える。
                out[key] = {name: _strip_prose(sub) for name, sub in value.items()}
            else:
                out[key] = _strip_prose(value)
        return out
    if isinstance(node, list):
        return [_strip_prose(item) for item in node]
    return node


def _write_json(path: Path, data: dict | list) -> None:
    # ensure_ascii=False: 日本語のdescription（レート制限メッセージ等）を可読なまま残す。
    # indent固定・末尾改行あり: 再生成のdiffが内容の変化だけを反映するようにする。
    # newline="\n"固定: Windowsで実行してもCRLFにならないようにする（CI（Linux）の
    # ドリフト検知と生成環境によらずバイト単位で一致させるため）。
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path}")


def _write_ts(path: Path, name: str, data: dict | list) -> None:
    """生成物をTypeScriptの`as const`で書く。

    **JSONで出すと型が`string`へ広がり、存在しない値を渡しても型検査が通る**
    （実際に広げた実績あり）。値の集合そのものが契約になるものは、この形で出す。
    """
    body = json.dumps(data, ensure_ascii=False, indent=2)
    header = "// 生成物。`backend/scripts/export_openapi.py`が書き出す。手で編集しない。"
    text = header + "\n" + f"export const {name} = {body} as const;" + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {path}")


def main() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, _strip_prose(app.openapi()))  # type: ignore[arg-type]
    # 路面語彙の正準タグ集合（domain/road.py）。フロントの表示グループ定義
    # （roadFilterAxes.ts）が正準分類とずれていないことをroadFilterAxes.test.tsが
    # このJSONと突き合わせて検証する（地図の色とルート評価の食い違いを防ぐ）。
    _write_json(
        SURFACE_TAGS_PATH,
        {"good": sorted(GOOD_OSM_SURFACE_TAGS), "bad": sorted(BAD_OSM_SURFACE_TAGS)},
    )
    # 地域ベクタタイルのレイヤー名・世代。フロントの手書き定数（MapView.tsxのソース
    # レイヤー名、regionApi.ts: 各tileUrl()の?v=）がこのJSONとregionApi.test.tsで
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
            # 国土地理院タイル（色別標高図・標高）。配信元が実データを持つ範囲・画面が
            # 要求するURL・出典表記・標高の読み戻し係数は、すべてbackendが正本を持つ
            # （domain/gsi_tiles.py・domain/terrain_rgb.py）。**画面はこれを写さない**。
            "gsi": {
                "relief": {
                    "tile_url": RELIEF_TILE_URL,
                    "max_zoom": RELIEF_MAX_ZOOM,
                    "attribution": RELIEF_ATTRIBUTION,
                },
                "terrain": {
                    "tile_url": TERRAIN_TILE_URL,
                    "max_zoom": TERRAIN_MAX_ZOOM,
                    # 標高(m) = base + (R*65536 + G*256 + B) * unit。画面は係数を持たず、
                    # この2つから組み立てる。
                    "rgb_unit_m": TERRAIN_RGB_UNIT_M,
                    "rgb_base_m": TERRAIN_RGB_BASE_M,
                },
            },
            # 土地被覆ラスタタイル。ズーム範囲は元データの分解能と読み取り量から
            # backendが決める（domain/landcover.py）。
            "landcover": {
                "tile_version": LANDCOVER_TILE_VERSION,
                "min_zoom": LANDCOVER_TILE_MIN_ZOOM,
                "max_zoom": LANDCOVER_TILE_MAX_ZOOM,
            },
        },
    )
    # 役割ごとの色（domain/display_palette.py）。**画面は色の値を持たず、この名前で引く**。
    # 色を変えるときに触るのはbackendの1ファイルだけになる。
    _write_json(
        PALETTE_PATH,
        {
            "semantic": SEMANTIC_COLORS,
            "comparison_slots": list(COMPARISON_SLOT_COLORS),
            "evaluation_ramp_anchors": [
                {"position": position, "color": color} for position, color in EVALUATION_RAMP_ANCHORS
            ],
        },
    )
    # 地図に出すものの最上位の束ね方（domain/map_display.py）。並びがチップの並び順。
    # **JSONではなくTypeScriptで出す。** JSONのimportは型が`string`へ広がり、
    # 存在しない値を渡しても型検査が通ってしまう（実際に広げた実績あり）。`as const`で
    # 出すと、画面側の型は源泉の値そのものに狭まる。
    _write_ts(
        MAP_DISPLAY_PATH,
        "mapDisplay",
        {
            "overlayGroups": [g._asdict() for g in MAP_OVERLAY_GROUPS],
            "layerCategories": [c._asdict() for c in MAP_LAYER_CATEGORIES],
            "layerDataSources": list(MAP_LAYER_DATA_SOURCES),
            "layerDataNatures": list(MAP_LAYER_DATA_NATURES),
            "layerIds": list(MAP_LAYER_IDS),
            "layerKinds": list(MAP_LAYER_KINDS),
        },
    )
    # 気象の値を色へ写す段（domain/weather_display.py）。危険度・雷・竜巻は配信元が
    # 決めた配色に合わせるもので、画面の好みではない。
    _write_json(
        WEATHER_SCALES_PATH,
        {
            "precipitation": [s._asdict() for s in PRECIPITATION_COLOR_STOPS],
            "wind_speed": [s._asdict() for s in WIND_SPEED_COLOR_STOPS],
            "risk_levels": [level._asdict() for level in RISK_LEVEL_COLORS],
            "thunder_activity": [level._asdict() for level in THUNDER_ACTIVITY_LEVELS],
            "tornado_potential": [level._asdict() for level in TORNADO_POTENTIAL_LEVELS],
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
    # **キーの一覧はここから引く**——backendがkindを足したのにfrontendのbaseFilterが
    # 古いままだと、その地物はフィルタに弾かれて地図から完全に消える（凡例にも出ないため
    # 「データが無い」としか見えない）。
    _write_json(
        POI_KINDS_PATH,
        {
            "stop": sorted(STOP_POI_KINDS),
            "supply": sorted(get_args(SupplyPoiKind)),
        },
    )
    # 軸スタジオが選べる公開材料の一覧。frontendは`GET /api/material-catalog`が失敗した
    # ときの静的フォールバックとして使う。
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
    _write_ts(
        PRIMARY_ATTRIBUTES_PATH,
        "primaryAttributes",
        # 一次属性カタログ（地図レイヤー階層の次数反転）。レジストリ
        # （`domain/registry.py`）だけから決まり、DBを読まない。各軸の
        # `primary_attribute_ids`は実行時の`GET /api/axis-catalog`が配るため、フロントは
        # この一覧のlabel（正式名）と突き合わせて1次↔2次の双方向導出ができる。
        # 宣言をそのまま配る。色だけは宣言に無いので`resolved_display_axes`が決める。
        [
            {**attr.model_dump(exclude={"display_axes"}), "display_axes": resolved_display_axes(attr)}
            for attr in all_primary_attributes()
        ],
    )
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
    # 風・降水延長予報の格子間隔（domain/wind_grid.py）。APIレスポンスは間隔を含まない
    # ため、frontend（windLayer.ts）はこのJSONから読む以外に値を知る手段がない。
    _write_json(
        WIND_GRID_CONFIG_PATH,
        {
            "spacing_deg": WIND_GRID_SPACING_DEG,
            "detail_spacing_deg": WIND_GRID_DETAIL_SPACING_DEG,
            "detail_allowed_spacings_deg": list(WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG),
            "detail_max_points": WIND_GRID_DETAIL_MAX_POINTS,
        },
    )
    # ルート生成の上限・既定値。frontendが独立にハードコードすると、backendだけ変えた
    # ときに入力の上限と受理される値がずれる。
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
            # キーを1つ足した瞬間にすべてのルート生成が422になる。
            "hard_filters": {
                "keys": sorted(HARD_FILTER_NAMES),
                "defaults": sorted(DEFAULT_HARD_FILTERS),
            },
        },
    )


if __name__ == "__main__":
    main()
