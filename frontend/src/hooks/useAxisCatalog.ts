"use client";

import { useEffect, useSyncExternalStore } from "react";
import type { PreferenceAxisDef } from "@/lib/evaluationAxes";
import { PREFERENCE_AXES } from "@/lib/evaluationAxes";
import type { AxisCatalogEntry, RoutePreferenceWeights } from "@/types/route";
import { getAxisCatalog } from "@/services/axisCatalogApi";
import axisCatalogStatic from "@/types/generated/axis-catalog.json";
import {
  AXIS_LABELS,
  RAMP_AXES,
  axisLabelsFromCatalogAxes,
  rampAxesFromCatalogAxes,
  type CatalogAxis,
  type RampAxis,
} from "@/components/Map/axisLayers";
import { SECONDARY_AXES, secondaryAxesFromCatalogAxes, type SecondaryAxisSummary } from "@/components/Map/secondaryAxes";
import {
  ROUTE_STYLE_MODES,
  routeStyleModesFromCatalogAxes,
  type RouteStyleMode,
} from "@/components/Map/routeStyleModes";

// ビルド時静的生成物（既存7軸の既定重み、開発中のフォールバック用）。
// GET /api/axis-catalogはこれと同じ形の情報をDBの最新内容から動的に返す。
const STATIC_DEFAULT_WEIGHTS: RoutePreferenceWeights = axisCatalogStatic.preference_defaults;

export interface AxisCatalog {
  /** axisId・label・descriptionの一覧（フェッチ成功時はDB由来、失敗時は静的フォールバック）。 */
  axes: readonly PreferenceAxisDef[];
  /** axis_idから既定重みを引く。未知のaxis_idには0を返す。 */
  defaultWeights: RoutePreferenceWeights;
  /** 地図のramp表示を持つ軸。フェッチ完了までとエラー時は静的
   * フォールバック（axisLayers.ts: RAMP_AXES）を返す。 */
  rampAxes: readonly RampAxis[];
  /** axis_id→表示名の辞書（軸スタジオ公開軸を含む、フェッチ完了までは静的フォールバック）。 */
  axisLabels: Record<string, string>;
  /** 二次軸(推定指標)一覧（地図チップの「推定指標」グループが読む）。フェッチ完了までと
   * エラー時は静的フォールバック（secondaryAxes.ts: SECONDARY_AXES）。 */
  secondaryAxes: readonly SecondaryAxisSummary[];
  /** ルート地図の色分けモード一覧（公開軸を無条件で動的に含む）。フェッチ完了までと
   * エラー時は静的フォールバック（routeStyleModes.ts: ROUTE_STYLE_MODES）。 */
  routeStyleModes: readonly RouteStyleMode[];
  /** GET /api/axis-catalogの取得が成功し、他フィールドが実際のDB由来の値であることを表す。
   * falseの間（未取得・取得失敗）は他フィールドが静的フォールバック（ビルド時の既存7軸
   * スナップショット）である可能性があるため、呼び出し側が「軸スタジオの現在の公開軸集合と
   * 一致している」ことを要求する処理（route_preferenceのキー整合等）では、このフラグで
   * 未確定状態を区別しなければならない。取得成功時にaxesが0件（全軸非公開）であっても
   * trueになる（0件も確定した実際の状態のため）。 */
  loaded: boolean;
}

const FALLBACK_CATALOG: AxisCatalog = {
  axes: PREFERENCE_AXES,
  defaultWeights: STATIC_DEFAULT_WEIGHTS,
  rampAxes: RAMP_AXES,
  axisLabels: AXIS_LABELS,
  secondaryAxes: SECONDARY_AXES,
  routeStyleModes: ROUTE_STYLE_MODES,
  loaded: false,
};

/** GET /api/axis-catalogのAxisCatalogEntry（displayが必ず非null）を、axisLayers.ts/
 * secondaryAxes.tsの変換関数が受け取れるCatalogAxis形（displayが`{...} | null`、
 * ビルド時静的json由来）へ合わせる。tile_inputs/thresholdsはbackendで既定値付き
 * （常に配列で返るが、OpenAPI生成型は既定値ありのフィールドをoptionalとしてマークするため
 * 型上はundefinedを許容する）ため、undefined時は空配列を補う。 */
function toCatalogAxis(entry: AxisCatalogEntry): CatalogAxis {
  return {
    axis_id: entry.axis_id,
    label: entry.label,
    category: entry.category,
    display: {
      kind: entry.display.kind,
      label: entry.display.label,
      category: entry.display.category,
      tile_inputs: (entry.display.tile_inputs ?? []).map((input) => ({
        property: input.property,
        weight: input.weight,
        boolean: input.boolean,
        true_value: input.true_value,
        false_value: input.false_value,
        has_unknown_fallback: input.has_unknown_fallback,
        categories: input.categories ?? null,
        breakpoints: input.breakpoints ?? null,
        needs_runtime_scale: input.needs_runtime_scale,
      })),
      thresholds: entry.display.thresholds ?? [],
      unit: entry.display.unit,
      note: entry.display.note,
    },
    primary_attribute_ids: entry.primary_attribute_ids,
    icon_id: entry.icon_id,
    chip_label: entry.chip_label,
    panel_hint: entry.panel_hint,
    show_map_icon: entry.show_map_icon,
    shape: entry.shape,
    display_thresholds_override: entry.display_thresholds_override,
    display_band_labels_override: entry.display_band_labels_override,
    dedicated_way_value_layer: entry.dedicated_way_value_layer,
    map_value_kind: entry.map_value_kind,
    map_value_unit: entry.map_value_unit,
  };
}

function buildCatalog(
  entries: readonly AxisCatalogEntry[],
  materialRuntimeScales: Readonly<Record<string, number>>,
): AxisCatalog {
  const defaultWeights: RoutePreferenceWeights = {};
  const axes: PreferenceAxisDef[] = entries.map((entry) => {
    defaultWeights[entry.axis_id] = entry.default_weight;
    return {
      axisId: entry.axis_id,
      label: entry.label,
      description: entry.description,
      dedicatedWayValueLayer: entry.dedicated_way_value_layer,
      displayThresholdsOverride: entry.display_thresholds_override ?? undefined,
      displayBandLabelsOverride: entry.display_band_labels_override ?? undefined,
      mapValueKind: entry.map_value_kind,
      mapValueUnit: entry.map_value_unit,
    };
  });
  const catalogAxes = entries.map(toCatalogAxis);
  return {
    axes,
    defaultWeights,
    rampAxes: rampAxesFromCatalogAxes(catalogAxes, materialRuntimeScales),
    axisLabels: axisLabelsFromCatalogAxes(catalogAxes),
    secondaryAxes: secondaryAxesFromCatalogAxes(catalogAxes),
    routeStyleModes: routeStyleModesFromCatalogAxes(catalogAxes),
    loaded: true,
  };
}

// page.tsxとRouteSettingsPanel.tsx（page.tsxの子として初回描画時からマウントされる）が
// 同時にこのフックを呼びうるため、同時に飛んでいる（未解決の）フェッチだけをこの
// モジュールレベル変数で共有し、解決/失敗したら即座にクリアする（解決後の結果を
// 永続キャッシュしない——軸スタジオでの公開操作を再デプロイなしに反映するため、
// 後続の別マウント[例: モバイルのBottomSheetでタブを開き直す]では改めて最新を取得する）。
let inFlightCatalogFetch: ReturnType<typeof getAxisCatalog> | null = null;

function fetchAxisCatalogDeduped(): ReturnType<typeof getAxisCatalog> {
  if (inFlightCatalogFetch) return inFlightCatalogFetch;
  const request = getAxisCatalog().finally(() => {
    if (inFlightCatalogFetch === request) inFlightCatalogFetch = null;
  });
  inFlightCatalogFetch = request;
  return request;
}

// 上記の「同時に飛んでいる場合」の重複排除だけでは、page.tsxが先にマウント・フェッチ
// 完了した後にRouteSettingsPanel.tsxが再マウント（モバイルのBottomSheetでタブを
// 開き直す等）してフェッチし直すケースを救えない。解決済みカタログをモジュールレベルの
// 単一ストアとして持ち、全呼び出し元がuseSyncExternalStoreで同じオブジェクト参照を
// 購読することで、2インスタンス間で`axes`配列が食い違うことは構造的に起こらない
// （どちらかのフェッチが解決すれば全呼び出し元へ即座に反映される）。
let sharedCatalog: AxisCatalog = FALLBACK_CATALOG;
const catalogListeners = new Set<() => void>();

function publishCatalog(next: AxisCatalog): void {
  sharedCatalog = next;
  catalogListeners.forEach((listener) => listener());
}

function subscribeToCatalog(listener: () => void): () => void {
  catalogListeners.add(listener);
  return () => {
    catalogListeners.delete(listener);
  };
}

function getCatalogSnapshot(): AxisCatalog {
  return sharedCatalog;
}

function getCatalogServerSnapshot(): AxisCatalog {
  return FALLBACK_CATALOG;
}

/** テスト専用: モジュールレベルの共有ストアをリセットする。本番コードからは呼ばない。 */
export function __resetAxisCatalogStoreForTests(): void {
  sharedCatalog = FALLBACK_CATALOG;
  inFlightCatalogFetch = null;
}

/** 軸カタログ。マウント時に一度`GET /api/axis-catalog`を取得し、軸スタジオがDBへ
 * 追加・公開した軸を反映する（is_publishedの切替も含め、再デプロイ不要で即座に
 * 反映される）。取得完了までとエラー時は静的な既存7軸カタログ（フォールバック）を
 * 返すため、呼び出し側は常に何かしらの一覧を受け取れる（loading状態を個別に扱う
 * 必要がない）。
 *
 * フォールバック中（`loaded=false`）の値を「軸スタジオの現在の公開軸集合」と取り違えて
 * 送信すると、実際の公開軸と食い違うroute_preferenceを送ってしまい422になりうる
 * （`page.tsx: handleGenerate`参照）。フォールバック値をUIの初期描画・地図レイヤーの初期状態
 * 用に使うことは問題ないが、APIへ送るペイロードの構築等「軸スタジオの現在の状態と一致して
 * いなければならない」処理では、必ず`loaded`を確認すること。このフックはaxis_idから
 * 観測/推定/動的カテゴリを引く手段を提供しない——backendのGET /api/axis-catalog
 * レスポンス自体には引き続き`category`フィールドが含まれる（他用途のため）が、
 * このフックはそれを消費しない。 */
export function useAxisCatalog(): AxisCatalog {
  useEffect(() => {
    fetchAxisCatalogDeduped()
      .then((response) => {
        // 取得成功時はaxesが空でもそのままbuildCatalogへ渡す（フェッチ未完了・失敗時のみ
        // FALLBACK_CATALOGに留まる、という区別に一本化する——「まだ取得中/取得失敗」と
        // 「取得成功したが軸が0件（全軸非公開）」を同一視すると、軸スタジオで全軸を
        // 非公開にしても静的フォールバックの既存7軸が表示され続けてしまう）。
        publishCatalog(buildCatalog(response.axes, response.material_runtime_scales ?? {}));
      })
      .catch(() => {
        // 取得失敗時は共有ストアを書き換えない（fetchJsonが既にdebugLogへ記録済み。
        // 他の呼び出し元が既に取得済みの正常なカタログを、この呼び出し元だけの
        // 失敗で巻き戻さないため）。
      });
  }, []);

  return useSyncExternalStore(subscribeToCatalog, getCatalogSnapshot, getCatalogServerSnapshot);
}
