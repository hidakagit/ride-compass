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
from typing import get_args
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.registry import (  # noqa: E402
    all_primary_attributes,
    reset_registry_for_testing,
)
from app.domain.registry_defaults import register_defaults  # noqa: E402
from app.domain.wind_grid import (  # noqa: E402
    WIND_GRID_DETAIL_MAX_POINTS,
    WIND_GRID_DETAIL_MIN_SPACING_DEG,
    WIND_GRID_SPACING_DEG,
)
from app.api.routers.routes import DEFAULT_DISTANCE_TOLERANCE_KM, MAX_ROUTE_DISTANCE_KM  # noqa: E402
from app.api.routers.axis_admin import AxisDefinitionPayload  # noqa: E402
from app.api.routers.debug_admin import LogLevelName  # noqa: E402
from app.infrastructure.source_models import SOURCE_RUN_STATUS_LABELS  # noqa: E402
from app.domain.axis_definitions import MAP_CHIP_LABEL_MAX_LENGTH  # noqa: E402
from app.infrastructure.vector_tile import (  # noqa: E402
    ACCIDENT_LAYER_NAME,
    ROAD_SURFACE_LAYER_NAME,
    STOP_POI_LAYER_NAME,
)
from app.main import app  # noqa: E402
from app.domain.wind import ASSUMED_SPEED_KMH, MAX_ASSUMED_SPEED_KMH, MIN_ASSUMED_SPEED_KMH  # noqa: E402
from app.domain.hard_filters import DEFAULT_HARD_FILTERS, HARD_FILTER_LABELS, HARD_FILTER_NAMES  # noqa: E402
from app.domain.geo import COMPASS_LABELS  # noqa: E402
from app.domain.weather_elements import (  # noqa: E402
    WEATHER_ELEMENTS,
    WEATHER_LAYER_GROUPS,
    WeatherElement,
    weather_element_attribution,
    weather_element_deliveries,
    weather_element_tile,
)
from app.domain.map_display import (  # noqa: E402
    ALWAYS_SHOWN_ATTRIBUTIONS,
    DEFAULT_DIFFICULTY_BOUNDARIES,
    AXIS_LAYER_SPECS,
    MAP_LAYER_CATEGORIES,
    MAP_LAYERS,
    MAP_LAYER_KINDS,
    MapLayerSpec,
    ROUTE_ARROW_HALO_SCALE,
    ROUTE_ARROW_SIZE_BY_ZOOM,
    ROUTE_ARROW_SPACING_PX,
    ROUTE_CASING_WIDTHS_PX,
    ROUTE_LINE_OPACITIES,
    ROUTE_LINE_WIDTHS_PX,
    ROUTE_SPLICE_DASH,
    AREA_OPACITY,
    HILLSHADE_ILLUMINATION_DEG,
    HILLSHADE_METHOD,
    LIGHTNING_ICON_SCALE,
    TERRAIN_EXAGGERATION,
    WEATHER_MARK_HALO_WIDTH_PX,
    WIND_FULL_SCALE_MS,
    WIND_ICON_SCALE_RANGE,
    ACCIDENT_POINT_OPACITY,
    POINT_FATAL_RADIUS_PX,
    POINT_NON_FATAL_RADIUS_PX,
    POINT_OPACITY,
    POINT_RADIUS_PX,
    POINT_STROKE_WIDTH_PX,
    ROAD_INSPECTED_WIDTH_PX,
    ROAD_KNOWN_OPACITY,
    ROAD_LINE_WIDTH_PX,
    ROAD_TRACK_OFFSET_STEP_PX,
    NO_DATA_DASH,
    ROAD_UNDERLAY_OPACITY,
    ROAD_UNKNOWN_OPACITY,
    MAP_LAYER_DATA_NATURES,
    MAP_LAYER_DATA_SOURCES,
    MAP_OVERLAY_GROUPS,
)
from app.domain.warning_display import WARNING_BADGE_DISPLAY  # noqa: E402
from app.domain.weather_display import (  # noqa: E402
    WEATHER_CATEGORIES,
    WEATHER_CATEGORY_FALLBACK,
    LINEAR_RAINBAND_COLOR,
    PRECIPITATION_COLOR_STOPS,
    RISK_LEVEL_COLORS,
    THUNDER_ACTIVITY_LEVELS,
    TORNADO_POTENTIAL_LEVELS,
    WIND_CALM_BELOW_MS,
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
from app.domain.jma_tile_specs import effective_max_zoom  # noqa: E402
from app.domain.material_catalog import (  # noqa: E402
    MATERIAL_CATALOG,
    MISSING_SEMANTICS_DISPLAY,
    POPULATION_LABELS,
    display_axis_missing_semantics,
)
from app.domain.region import ROAD_TILE_MAX_ZOOM, ROAD_TILE_MIN_ZOOM  # noqa: E402
from app.services.road_graph_engine import MAX_TIME_BINS, TIME_BIN_HOURS  # noqa: E402
from app.services.route_generator import (  # noqa: E402
    DEFAULT_MAX_ROUTES,
    MAX_ROUTES,
    ROUTES_WITH_WAYPOINTS,
    SPLICED_ROUTE_ID,
)
from app.config import Settings  # noqa: E402
from app.domain.loop_routing import WAYPOINTS_ROUTE_ID  # noqa: E402
from app.domain.region import MAX_MERCATOR_LATITUDE  # noqa: E402
from app.domain.route_preference import MAX_AXIS_WEIGHT  # noqa: E402
from app.domain.tuning import client_tuning_values  # noqa: E402
from app.domain.weather import PRECIPITATION_MIN_MM  # noqa: E402
from app.infrastructure.msm_client import DEFAULT_UPDATE_INTERVAL_SECONDS as MSM_UPDATE_INTERVAL_SECONDS  # noqa: E402
from app.services.jma_amedas_service import AMEDAS_REFRESH_INTERVAL_MINUTES  # noqa: E402
from app.infrastructure.job_registry import JOB_TTL_SECONDS  # noqa: E402
from app.services.tile_version_service import TILE_SHAPES  # noqa: E402

GENERATED_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "generated"
OUTPUT_PATH = GENERATED_DIR / "openapi.json"
REGION_TILE_CONFIG_PATH = GENERATED_DIR / "region-tile-config.json"
PRIMARY_ATTRIBUTES_PATH = GENERATED_DIR / "primaryAttributes.ts"
WIND_GRID_CONFIG_PATH = GENERATED_DIR / "wind-grid-config.json"
ROUTE_GENERATE_CONFIG_PATH = GENERATED_DIR / "route-generate-config.json"
REFRESH_INTERVALS_PATH = GENERATED_DIR / "refresh-intervals.json"
AXIS_PAYLOAD_CONFIG_PATH = GENERATED_DIR / "axis-payload-config.json"
MATERIAL_CATALOG_PATH = GENERATED_DIR / "material-catalog.json"
LANDCOVER_CLASSES_PATH = GENERATED_DIR / "landcover-classes.json"
PALETTE_PATH = GENERATED_DIR / "palette.json"
WEATHER_SCALES_PATH = GENERATED_DIR / "weather-scales.json"
MAP_DISPLAY_PATH = GENERATED_DIR / "mapDisplay.ts"
VOCABULARY_PATH = GENERATED_DIR / "vocabulary.ts"


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


def _map_layer_entry(spec: MapLayerSpec) -> dict:
    return {
        "dataSource": spec.data_source,
        "category": spec.category,
        "kind": spec.kind,
        "dataNature": spec.data_nature,
        "defaultOn": spec.default_on,
    }


def _weather_element_entry(element: WeatherElement) -> dict:
    tile = weather_element_tile(element)
    return {
        "group": element.group,
        "source": element.source,
        "kind": element.kind,
        "label": element.label,
        "frameRule": {"kind": element.frame_rule.kind, "windowMinutes": element.frame_rule.window_minutes},
        "gridValue": element.grid_value,
        # 時刻の段の順（近い時刻から）。画面のデータ層は、配信元のURLを要素idと系統から、
        # 時刻一覧のURLを系統とファイル名から組み立て、行を読み方に従ってコマにする。
        "jmaElements": [
            {
                "id": delivery.element_id,
                "pathGroup": delivery.path_group,
                "targetTimeFiles": list(delivery.target_time_files),
                "reader": delivery.reader,
                "refreshIntervalMs": delivery.refresh_interval_seconds * 1000,
            }
            for delivery in weather_element_deliveries(element)
        ],
        "attribution": weather_element_attribution(element),
        # タイルで描くものだけが持つ。ズームの上限は配信元に実データがある範囲から導く。
        "tile": None
        if tile is None
        else {
            "minZoom": tile.min_zoom,
            "maxZoom": effective_max_zoom(tile),
            "vectorLayer": tile.vector_layer,
        },
    }


def main() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUTPUT_PATH, _strip_prose(app.openapi()))  # type: ignore[arg-type]
    # 地域ベクタタイルのレイヤー名・世代。フロントの手書き定数（MapView.tsxのソース
    # レイヤー名、regionApi.ts: roadSurfaceTileUrl()等の?v=）がこのJSONとregionApi.test.tsで
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
            # 画面が点からタイル座標を求めるときに緯度を挟む限界（`domain/region.py`と同じ式を使う）。
            "max_mercator_latitude": MAX_MERCATOR_LATITUDE,
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
            "layerDataSources": [
                {"key": source.key, "minZoom": source.min_zoom} for source in MAP_LAYER_DATA_SOURCES
            ],
            "layerDataNatures": list(MAP_LAYER_DATA_NATURES),
            "layerKinds": list(MAP_LAYER_KINDS),
            # 地図に載るものの、描き方以外の宣言（種別・情報源・性質・既定表示）。
            "layers": [{"id": layer_id, **_map_layer_entry(spec)} for layer_id, spec in MAP_LAYERS],
            "axisLayers": {kind: _map_layer_entry(spec) for kind, spec in AXIS_LAYER_SPECS.items()},
            # 動的気象のチップ（1つが複数の名前付きソースを束ねる）。画面が写しを持たない。
            "weatherLayerGroups": list(WEATHER_LAYER_GROUPS),
            # 動的気象で描くもの。画面はこれをループし、描き方（paint・layout・filter・記号）だけを持つ。
            "weatherElements": [_weather_element_entry(element) for element in WEATHER_ELEMENTS],
            # 方位の呼び名。**画面が写しを持たない**——丸め規則が違うと境界で
            # ラベルが食い違うため、並びは1箇所（domain/geo.py）だけが持つ。
            "compassLabels": list(COMPASS_LABELS),
            # 地図へ常に出す出典。
            "alwaysShownAttributions": list(ALWAYS_SHOWN_ATTRIBUTIONS),
            # 値が無い線の破線（道・評価軸・ルートで共有）。
            "noDataDash": list(NO_DATA_DASH),
            "road": {
                "lineWidthPx": ROAD_LINE_WIDTH_PX,
                "trackOffsetStepPx": ROAD_TRACK_OFFSET_STEP_PX,
                "knownOpacity": ROAD_KNOWN_OPACITY,
                "unknownOpacity": ROAD_UNKNOWN_OPACITY,
                "underlayOpacity": ROAD_UNDERLAY_OPACITY,
                "inspectedWidthPx": ROAD_INSPECTED_WIDTH_PX,
            },
            "point": {
                "radiusPx": POINT_RADIUS_PX,
                "fatalRadiusPx": POINT_FATAL_RADIUS_PX,
                "nonFatalRadiusPx": POINT_NON_FATAL_RADIUS_PX,
                "strokeWidthPx": POINT_STROKE_WIDTH_PX,
                "opacity": POINT_OPACITY,
                "accidentOpacity": ACCIDENT_POINT_OPACITY,
            },
            "area": {
                "opacity": AREA_OPACITY,
                "hillshadeIlluminationDeg": HILLSHADE_ILLUMINATION_DEG,
                "hillshadeMethod": HILLSHADE_METHOD,
                "terrainExaggeration": TERRAIN_EXAGGERATION,
            },
            "weather": {
                "markHaloWidthPx": WEATHER_MARK_HALO_WIDTH_PX,
                "windIconScaleRange": list(WIND_ICON_SCALE_RANGE),
                "windFullScaleMs": WIND_FULL_SCALE_MS,
                "lightningIconScale": LIGHTNING_ICON_SCALE,
            },
            "valueScale": {
                "difficultyBoundaries": list(DEFAULT_DIFFICULTY_BOUNDARIES),
            },
            "route": {
                "lineWidthsPx": ROUTE_LINE_WIDTHS_PX,
                "casingWidthsPx": ROUTE_CASING_WIDTHS_PX,
                "opacities": ROUTE_LINE_OPACITIES,
                "spliceDash": list(ROUTE_SPLICE_DASH),
                "arrowSpacingPx": ROUTE_ARROW_SPACING_PX,
                "arrowHaloScale": ROUTE_ARROW_HALO_SCALE,
                "arrowSizeByZoom": [list(pair) for pair in ROUTE_ARROW_SIZE_BY_ZOOM],
            },
        },
    )
    # backendの語彙に付く、画面に出す名前と色。画面は写しを持たずこれを読む。キーで引く画面側の表（アイコン等）が
    # 語彙の増減で型検査に落ちるよう、mapDisplayと同じくTypeScriptの`as const`で出す。
    _write_ts(
        VOCABULARY_PATH,
        "vocabulary",
        {
            "warningBadge": {
                source: [level._asdict() for level in levels] for source, levels in WARNING_BADGE_DISPLAY.items()
            },
            "weatherCategories": [{"key": c.key, "label": c.label, "codes": list(c.codes)} for c in WEATHER_CATEGORIES],
            "weatherCategoryFallback": WEATHER_CATEGORY_FALLBACK,
            "materialPopulations": [{"key": key, "label": label} for key, label in POPULATION_LABELS.items()],
            # backendのログのレベル（軽い順）。画面の絞り込みの選択肢と、ログ行からレベルを読む正規表現がこの並びを使う。
            "logLevels": list(get_args(LogLevelName)),
            "materialMissingSemantics": [
                {"key": key, **display._asdict()} for key, display in MISSING_SEMANTICS_DISPLAY.items()
            ],
            # 取込のrunの状態の呼び名（DB状態の「最後の取込」）。宣言に無い状態は画面が生のまま出す。
            "sourceRunStatuses": [{"key": key, "label": label} for key, label in SOURCE_RUN_STATUS_LABELS.items()],
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
            "linear_rainband_color": LINEAR_RAINBAND_COLOR,
            "thunder_activity": [level._asdict() for level in THUNDER_ACTIVITY_LEVELS],
            "tornado_potential": [level._asdict() for level in TORNADO_POTENTIAL_LEVELS],
            "wind_calm_below_ms": WIND_CALM_BELOW_MS,
            "precipitation_none_below_mm": PRECIPITATION_MIN_MM,
        },
    )
    # 画面が取り直す間隔。新しい値が出る間隔（配信元の更新・backendの作り直し）そのもので、これより短く
    # 取り直しても新しい値は無い。実行時に変わりうるもの（プリウォームの間隔は環境変数、MSMのrun更新間隔は
    # 配信元のメタ情報）も、生成物は宣言の既定値を運ぶ——ずれても画面の鮮度が遅れるか取り直しが増えるだけ。
    _write_json(
        REFRESH_INTERVALS_PATH,
        {
            "amedas_seconds": AMEDAS_REFRESH_INTERVAL_MINUTES * 60,
            "jma_tile_index_seconds": Settings.model_fields["jma_tile_prewarm_interval_minutes"].default * 60,
            "msm_seconds": MSM_UPDATE_INTERVAL_SECONDS,
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
                # 路面タイルがこの材料を載せる属性の名前（載せない材料はnull）。
                "tile_property": spec.tile_property,
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
        # 宣言をそのまま配る。色だけは宣言に無いので`resolved_display_axes`が決め、値が欠けたときの意味は
        # その値を載せる材料の宣言から引く（地図の凡例が「不明」を出すかを決める）。
        [
            {
                **attr.model_dump(exclude={"display_axes"}),
                "display_axes": [
                    {**axis, "missing_semantics": display_axis_missing_semantics(attr, axis["property"])}
                    for axis in resolved_display_axes(attr)
                ],
            }
            for attr in all_primary_attributes()
        ],
    )
    # 風・降水延長予報の粗い格子の間隔と、詳細格子の問い合わせが受け付ける範囲（domain/wind_grid.py）。
    # APIレスポンスは間隔を含まないため、frontend（windLayer.ts）はこのJSONから読む以外に値を知る手段がない。
    _write_json(
        WIND_GRID_CONFIG_PATH,
        {
            "spacing_deg": WIND_GRID_SPACING_DEG,
            "detail_min_spacing_deg": WIND_GRID_DETAIL_MIN_SPACING_DEG,
            "detail_max_points": WIND_GRID_DETAIL_MAX_POINTS,
        },
    )
    # 軸スタジオが送る軸の既定値と、地図チップの名前の上限。画面は編集欄を持たない項目を新規の軸で
    # この既定値のまま送る（写しを持つと、backendの既定を変えたとき新規の軸だけ古い値で作られる）。
    _write_json(
        AXIS_PAYLOAD_CONFIG_PATH,
        {
            "defaults": {
                name: field.get_default(call_default_factory=True)
                for name, field in AxisDefinitionPayload.model_fields.items()
                if not field.is_required()
            },
            "chip_label_max_length": MAP_CHIP_LABEL_MAX_LENGTH,
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
            "routes_with_waypoints": ROUTES_WITH_WAYPOINTS,
            "default_assumed_speed_kmh": ASSUMED_SPEED_KMH,
            "default_distance_tolerance_km": DEFAULT_DISTANCE_TOLERANCE_KM,
            "spliced_route_id": SPLICED_ROUTE_ID,
            "waypoints_route_id": WAYPOINTS_ROUTE_ID,
            "max_axis_weight": MAX_AXIS_WEIGHT,
            "min_assumed_speed_kmh": MIN_ASSUMED_SPEED_KMH,
            "max_assumed_speed_kmh": MAX_ASSUMED_SPEED_KMH,
            # フロントのポーリングの打ち切り。backendが結果を持つ時間より長く待つと、
            # 掃除済みのjob_idを引いて「ジョブが見つかりません」になる。
            "job_result_ttl_seconds": JOB_TTL_SECONDS,
            # 風の予報を追う長さ（レグごと、時刻ビンの本数×幅）。区間の詳細の説明が、この先は最後に追った時刻の予報を
            # そのまま使うことを数字で示す。
            "wind_forecast_hours_per_leg": MAX_TIME_BINS * TIME_BIN_HOURS,
            # フロントが使う較正値の**既定**（`domain/tuning.py`の宣言そのまま）。
            # 実際に効いている値はGET /api/axis-catalogが返し、これはそれを取れるまでの値。
            "client_tuning": client_tuning_values(),
            # 0次ハードフィルタのキー一覧・画面に出す名前・既定値。backendは`_check_filter_keys`で
            # **キー集合の完全一致**を要求するため、frontendが手書きで持っていると
            # キーを1つ足した瞬間にすべてのルート生成が422になる。名前も同じ行で配る——
            # 別に持つと、足したフィルタの名前が無く画面に内部名が出る。
            "hard_filters": {
                "filters": [{"key": name, "label": HARD_FILTER_LABELS[name]} for name in sorted(HARD_FILTER_NAMES)],
                "defaults": sorted(DEFAULT_HARD_FILTERS),
            },
        },
    )


if __name__ == "__main__":
    main()
