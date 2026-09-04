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

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.axis_definitions import AXIS_DEFINITIONS, default_axis_weights  # noqa: E402
from app.domain.registry import (  # noqa: E402
    all_axes,
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
from app.api.routers.routes import MAX_ROUTE_DISTANCE_KM  # noqa: E402
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository  # noqa: E402
from app.infrastructure.database import get_session_factory  # noqa: E402
from app.infrastructure.vector_tile import (  # noqa: E402
    ACCIDENT_LAYER_NAME,
    ROAD_SURFACE_LAYER_NAME,
    STOP_POI_LAYER_NAME,
)
from app.main import app  # noqa: E402
from app.services.accident_service import ACCIDENT_TILE_VERSION  # noqa: E402
from app.services.axis_registry_service import refresh_axis_definitions  # noqa: E402
from app.services.region_service import POI_TILE_VERSION, ROAD_SURFACE_TILE_VERSION  # noqa: E402
from app.domain.wind import ASSUMED_SPEED_KMH, MAX_ASSUMED_SPEED_KMH, MIN_ASSUMED_SPEED_KMH  # noqa: E402
from app.services.route_generator import DEFAULT_MAX_ROUTES, MAX_ROUTES  # noqa: E402

GENERATED_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "generated"
OUTPUT_PATH = GENERATED_DIR / "openapi.json"
SURFACE_TAGS_PATH = GENERATED_DIR / "surface-tags.json"
REGION_TILE_CONFIG_PATH = GENERATED_DIR / "region-tile-config.json"
AXIS_CATALOG_PATH = GENERATED_DIR / "axis-catalog.json"
WIND_GRID_CONFIG_PATH = GENERATED_DIR / "wind-grid-config.json"
ROUTE_GENERATE_CONFIG_PATH = GENERATED_DIR / "route-generate-config.json"

def _write_json(path: Path, data: dict | list) -> None:
    # ensure_ascii=False: 日本語のdescription（レート制限メッセージ等）を可読なまま残す。
    # indent固定・末尾改行あり: 再生成のdiffが内容の変化だけを反映するようにする。
    # newline="\n"固定: Windowsで実行してもCRLFにならないようにする（CI（Linux）の
    # ドリフト検知と生成環境によらずバイト単位で一致させるため）。
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path}")


async def _load_axis_definitions_from_db() -> None:
    """DBの軸定義でAXIS_DEFINITIONSをin-place更新する（改善計画T278のバグ修正）。

    以前は本スクリプトがAXIS_DEFINITIONSをコード内蔵の静的辞書のまま一切DBへ
    問い合わせなかったため、軸スタジオがDBのみに作った新規軸（コード内蔵の既定値には
    存在しない）が生成物へ一切反映されなかった。

    改善計画T350: `AXIS_DEFINITIONS`のPython literal撤去に伴い、DB読み込み失敗時に
    フォールバックする「コード内蔵の既定値」自体が存在しなくなった。以前はCIの
    `api-contract`ジョブがDB接続を持たなかったため、この関数が例外を捕捉して
    「空のAXIS_DEFINITIONSのまま生成を続行し、コード内蔵の既定値ぶんの内容だけ
    出力する」というフォールバックを行っていたが、その出力自体が「空のカタログ」に
    なってしまい、生成失敗をエラーなく見逃す方が実害が大きいと判断してfail-fast化した
    （`api-contract`ジョブは同じ改善計画T350でpostgresサービスコンテナを追加済みのため、
    通常の実行経路では影響しない）。DB接続が無い環境でこのスクリプトを実行すると
    例外がそのまま送出され、`main()`を異常終了させる。
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        await refresh_axis_definitions(AxisDefinitionRepository(session))


def main() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(_load_axis_definitions_from_db())
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
    # 改善計画T292: 車ストレスの専用Pythonレシピ（CarStressRecipe等）を廃止し、
    # AXIS_DEFINITIONSの内部軸5つ+公開軸1つの階層構造で再現するようにしたため、
    # レシピ既定値・Python⇔JS相互検証フィクスチャ（旧traffic-stress-recipe.json・
    # traffic-stress-test-cases.json・road-suitability-recipe.json・
    # motor-vehicle-density-recipe.json）の生成は廃止した。
    # 二次軸カタログ（改善計画T145b「事実はタイルに、解釈はクライアントに」）。
    # レジストリ（domain/registry_defaults.py）の全軸と表示宣言（AxisDisplaySpec）を
    # 書き出し、フロントの汎用レイヤーファクトリ（axisLayers.ts）がkind="ramp"の軸から
    # レイヤー・凡例を自動生成する。新しい軸はレジストリへの登録（＋タイルへの事実の
    # 焼き込み）だけで地図レイヤーが現れる。
    # 一次属性カタログ（改善計画T163、地図レイヤー階層の次数反転）も同じレジストリから
    # 書き出す。各軸のprimary_attribute_idsは既にattr_idのリストとして含まれているため、
    # フロントはこのprimary_attributesのlabel（正式名）とprimary_attribute_idsの組み合わせ
    # だけで2次→1次・1次→2次の双方向導出ができる（片側import、設計原則2）。
    #
    # 改善計画T320: 以前は組み込み6軸を`registry_defaults.py`が手書きで個別登録し、
    # それ以外の軸（軸スタジオ作成軸）だけをここで別ループ（`_auto_ramp_axes`）で
    # 拾うという二重実装だった。`_register_axes()`が`AXIS_DEFINITIONS`を走査して
    # 公開軸すべてを一様に登録するようになったため（`domain/registry_defaults.py`
    # 参照）、`all_axes()`は既に組み込み・GUI作成を問わず全公開軸を含む。
    reset_registry_for_testing()
    register_defaults()
    _write_json(
        AXIS_CATALOG_PATH,
        {
            "axes": [
                {
                    "axis_id": axis.axis_id,
                    # 改善計画T352: ルート地図の色分けモード（frontend routeStyleModes.ts）が
                    # 軸ラベルを動的に組み立てるための値。display.labelは
                    # kind="none"の軸（例: wind）でも設定されているが、実行時API
                    # （GET /api/axis-catalog: AxisCatalogEntry.label）と揃えるため
                    # 独立したトップレベルフィールドとして書き出す。
                    "label": AXIS_DEFINITIONS[axis.axis_id].label,
                    # コードレビュー指摘の修正: 軸自身の分類（観測/推定/動的、domain/
                    # axis_definitions.py: AxisDefinition.category）を書き出す。これが無いと
                    # フロント側でwind（category="動的"）を推定指標チップグループから除外
                    # できない（secondaryAxes.ts参照）。
                    "category": AXIS_DEFINITIONS[axis.axis_id].category,
                    # 改善計画T308: GET /api/axis-catalog（実行時API）のprimary_attribute_ids
                    # と同じ値をキー名も揃えて書き出す（frontend側のCatalogAxis型・
                    # secondaryAxesFromCatalogAxes等が実行時API/静的生成物どちらの入力も
                    # 同じ変換関数で処理できるようにするため）。死コード監査（過去の監査）で、
                    # 同じ値を重複して書き出していた旧inputsキー（唯一の読み手だった
                    # frontend/src/lib/evaluationAxes.test.tsはprimary_attribute_ids読みへ
                    # 移行済み）は削除した。
                    "primary_attribute_ids": axis.inputs,
                    # 改善計画T310: registry.py側のAxisSpecはicon_id等を持たないため、
                    # AXIS_DEFINITIONS側（単一ソース、domain/axis_definitions.py）を都度引く。
                    "icon_id": AXIS_DEFINITIONS[axis.axis_id].icon_id,
                    "chip_label": AXIS_DEFINITIONS[axis.axis_id].chip_label,
                    "panel_hint": AXIS_DEFINITIONS[axis.axis_id].panel_hint,
                    "show_map_icon": AXIS_DEFINITIONS[axis.axis_id].show_map_icon,
                    "display": axis.display.model_dump() if axis.display is not None else None,
                    # 改善計画T440: GET /api/axis-catalog（AxisCatalogEntry）と同じ「軸スタジオで
                    # 決められること全部返す」方針を静的フォールバックにも揃える。
                    "shape": AXIS_DEFINITIONS[axis.axis_id].shape.model_dump(),
                    "display_thresholds_override": AXIS_DEFINITIONS[axis.axis_id].display_thresholds_override,
                    "display_band_labels_override": AXIS_DEFINITIONS[axis.axis_id].display_band_labels_override,
                    "dedicated_way_value_layer": AXIS_DEFINITIONS[axis.axis_id].dedicated_way_value_layer,
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
            # 区間難易度の重み（route_preference）の既定値（改善計画T221 Stage B）。
            # domain/axis_definitions.py: AXIS_DEFINITIONSのdefault_weightを書き出し、
            # フロント（evaluationAxes.ts: DEFAULT_ROUTE_PREFERENCE）はこの値を読む
            # （以前はroute_preference.yamlの手書きミラーで、値の変更時にドリフトしうる
            # 手動同期ペアだった）。表示カタログのaxes[]と異なりwindを含む全軸を持つ
            # （windはレイヤー表示を持たないためaxes[]には無いが、重みの軸としては存在する）。
            "preference_defaults": default_axis_weights(),
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
            "min_assumed_speed_kmh": MIN_ASSUMED_SPEED_KMH,
            "max_assumed_speed_kmh": MAX_ASSUMED_SPEED_KMH,
        },
    )


if __name__ == "__main__":
    main()
