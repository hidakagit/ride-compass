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
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.axis_definitions import AXIS_DEFINITIONS, default_axis_weights  # noqa: E402
from app.domain.axis_display import derive_ramp_inputs  # noqa: E402
from app.domain.registry import (  # noqa: E402
    AxisDisplaySpec,
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

logger = logging.getLogger("ridecompass.export_openapi")

GENERATED_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "types" / "generated"
OUTPUT_PATH = GENERATED_DIR / "openapi.json"
SURFACE_TAGS_PATH = GENERATED_DIR / "surface-tags.json"
REGION_TILE_CONFIG_PATH = GENERATED_DIR / "region-tile-config.json"
AXIS_CATALOG_PATH = GENERATED_DIR / "axis-catalog.json"
WIND_GRID_CONFIG_PATH = GENERATED_DIR / "wind-grid-config.json"

def _write_json(path: Path, data: dict | list) -> None:
    # ensure_ascii=False: 日本語のdescription（レート制限メッセージ等）を可読なまま残す。
    # indent固定・末尾改行あり: 再生成のdiffが内容の変化だけを反映するようにする。
    # newline="\n"固定: Windowsで実行してもCRLFにならないようにする（CI（Linux）の
    # ドリフト検知と生成環境によらずバイト単位で一致させるため）。
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {path}")


async def _try_load_axis_definitions_from_db() -> None:
    """可能ならDBの軸定義でAXIS_DEFINITIONSをin-place更新する（改善計画T278の
    バグ修正）。

    以前は本スクリプトがAXIS_DEFINITIONSをコード内蔵の静的辞書のまま一切DBへ
    問い合わせなかったため、下記main()の「registry.py未登録だがramp化可能な軸を
    axis-catalog.jsonへ足す」ループ（軸スタジオがDBのみに作った新規軸を拾う想定）が
    恒久的に空リストのまま機能していなかった（_registered_axis_idsと
    AXIS_DEFINITIONS.keys()が常に同じ7軸で一致してしまうため）。

    CIの`api-contract`ジョブはDB接続を持たない（本スクリプトのdocstring参照）ため、
    接続失敗時は`services/axis_registry_service.py: refresh_axis_definitions`と
    同じ安全側フォールバック（WARNINGログを出しコード内蔵の既定値のまま続行）に
    倣う——DB無しの環境でも生成物の内容（既存7軸ぶん）は今までどおり変わらない。
    """
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await refresh_axis_definitions(AxisDefinitionRepository(session))
    except Exception as exc:  # noqa: BLE001 生成を止めず内蔵の既定値へ安全側フォールバックする
        logger.warning("軸定義のDB読み込みに失敗、コード内蔵の既定値を使用します error=%r", exc)


def main() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(_try_load_axis_definitions_from_db())
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
    # 書き出す。各軸のinputsは既にattr_idのリストとして含まれているため、
    # フロントはこのprimary_attributesのlabel（正式名）とinputsの組み合わせだけで
    # 2次→1次・1次→2次の双方向導出ができる（片側import、設計原則2）。
    reset_registry_for_testing()
    register_defaults()
    # 改善計画T278: registry.pyへ手書き登録されていない軸（軸スタジオ/AXIS_DEFINITIONSにのみ
    # 存在する新規軸）のうち、材料が全てタイル焼き込み済み（ramp化可能と自動判定された）
    # ものだけをここへ追加する。ramp化不可（None）と判定された軸は追加しない（地図に出ない
    # ＝現状と同じ「専用レイヤー無し」のまま、退行にならない）。
    # AXIS_DEFINITIONSは上の_try_load_axis_definitions_from_dbが可能ならDBの内容で
    # 更新済み（DB未接続時は内蔵の既定7軸のまま＝このループは空リストのまま安全側で終わる）。
    # inputs（一次属性id一覧）は registry.py 側の別語彙（T12関係）のため空のまま。
    _registered_axis_ids = {axis.axis_id for axis in all_axes()}
    _auto_ramp_axes = []
    for axis_id, definition in AXIS_DEFINITIONS.items():
        if axis_id in _registered_axis_ids:
            continue
        # 改善計画T292: 内部軸（is_published=False、他の公開軸から参照される専用の
        # 推定軸）は恒久的に非公開のため、単独の地図レイヤーとして自動生成しない
        # （公開軸car_stressの内訳であって、それ自体が地図に出る意味を持たない）。
        if not definition.is_published:
            continue
        ramp = derive_ramp_inputs(definition)
        if ramp is None:
            continue
        _auto_ramp_axes.append(
            {
                "axis_id": axis_id,
                "inputs": [],
                "output_range": [0.0, 100.0],
                "display": AxisDisplaySpec(
                    kind="ramp",
                    label=definition.label,
                    # registry.py側のcategory（地図レイヤーのグルーピング用「terrain」
                    # 「road」「trafficSafety」等）とAXIS_DEFINITIONS.category（軸の性質
                    # 「観測」「推定」「動的」）は別語彙で機械的な対応が無いため、
                    # 軸スタジオ作成軸には汎用既定値trafficSafetyを充てる（多くの推定・観測軸が
                    # 実際に属する分類、地図レイヤーパネル上の表示グループが最適でないだけで
                    # 動作自体は壊れない）。カテゴリを選ばせるUIはStage Eのスコープ外。
                    category="trafficSafety",
                    tile_inputs=ramp.tile_inputs,
                    thresholds=ramp.thresholds,
                    note=f"{definition.description}(改善計画T278: 軸スタジオ作成軸の自動導出表示)",
                ).model_dump(),
            }
        )
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
            ]
            + _auto_ramp_axes,
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


if __name__ == "__main__":
    main()
