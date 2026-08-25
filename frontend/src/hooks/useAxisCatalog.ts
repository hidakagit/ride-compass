"use client";

import { useEffect, useState } from "react";
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

// ビルド時静的生成物（既存7軸の既定重み、開発中のフォールバック用）。GET /api/axis-catalog
// （改善計画T269）はこれと同じ形の情報をDBの最新内容から動的に返す。
const STATIC_DEFAULT_WEIGHTS: RoutePreferenceWeights = axisCatalogStatic.preference_defaults;

export interface AxisCatalog {
  /** axisId・label・descriptionの一覧（フェッチ成功時はDB由来、失敗時は静的フォールバック）。 */
  axes: readonly PreferenceAxisDef[];
  /** axis_idから既定重みを引く。未知のaxis_idには0を返す。 */
  defaultWeights: RoutePreferenceWeights;
  /** 地図のramp表示を持つ軸（改善計画T308）。フェッチ完了までとエラー時は静的
   * フォールバック（axisLayers.ts: RAMP_AXES）を返す。 */
  rampAxes: readonly RampAxis[];
  /** axis_id→表示名の辞書（軸スタジオ公開軸を含む、フェッチ完了までは静的フォールバック）。 */
  axisLabels: Record<string, string>;
  /** 二次軸(推定指標)一覧（地図チップの「推定指標」グループが読む、改善計画T308でフェッチ
   * 対応）。フェッチ完了までとエラー時は静的フォールバック（secondaryAxes.ts: SECONDARY_AXES）。 */
  secondaryAxes: readonly SecondaryAxisSummary[];
}

const FALLBACK_CATALOG: AxisCatalog = {
  axes: PREFERENCE_AXES,
  defaultWeights: STATIC_DEFAULT_WEIGHTS,
  rampAxes: RAMP_AXES,
  axisLabels: AXIS_LABELS,
  secondaryAxes: SECONDARY_AXES,
};

/** GET /api/axis-catalogのAxisCatalogEntry（displayが必ず非null）を、axisLayers.ts/
 * secondaryAxes.tsの変換関数が受け取れるCatalogAxis形（displayが`{...} | null`、
 * ビルド時静的json由来）へ合わせる。tile_inputs/thresholdsはbackendで既定値付き
 * （常に配列で返るが、OpenAPI生成型は既定値ありのフィールドをoptionalとしてマークするため
 * 型上はundefinedを許容する）ため、undefined時は空配列を補う。 */
function toCatalogAxis(entry: AxisCatalogEntry): CatalogAxis {
  return {
    axis_id: entry.axis_id,
    display: {
      kind: entry.display.kind,
      label: entry.display.label,
      category: entry.display.category,
      tile_inputs: (entry.display.tile_inputs ?? []).map((input) => ({
        property: input.property,
        weight: input.weight,
        boolean: input.boolean,
        invert: input.invert,
        true_value: input.true_value,
        false_value: input.false_value,
        has_unknown_fallback: input.has_unknown_fallback,
        categories: input.categories ?? null,
        breakpoints: input.breakpoints ?? null,
      })),
      thresholds: entry.display.thresholds ?? [],
      unit: entry.display.unit,
      note: entry.display.note,
    },
    primary_attribute_ids: entry.primary_attribute_ids,
  };
}

function buildCatalog(entries: readonly AxisCatalogEntry[]): AxisCatalog {
  const defaultWeights: RoutePreferenceWeights = {};
  const axes: PreferenceAxisDef[] = entries.map((entry) => {
    defaultWeights[entry.axis_id] = entry.default_weight;
    return { axisId: entry.axis_id, label: entry.label, description: entry.description };
  });
  const catalogAxes = entries.map(toCatalogAxis);
  return {
    axes,
    defaultWeights,
    rampAxes: rampAxesFromCatalogAxes(catalogAxes),
    axisLabels: axisLabelsFromCatalogAxes(catalogAxes),
    secondaryAxes: secondaryAxesFromCatalogAxes(catalogAxes),
  };
}

/** 軸カタログ（改善計画T269、T308で地図表示情報を追加）。マウント時に一度
 * `GET /api/axis-catalog`を取得し、軸スタジオ（T270）がDBへ追加・公開した軸を反映する
 * （is_publishedの切替も含め、再デプロイ不要で即座に反映される）。取得完了までとエラー時は
 * 静的な既存7軸カタログ（フォールバック）を返すため、呼び出し側は常に何かしらの
 * 一覧を受け取れる（loading状態を個別に扱う必要がない）。
 *
 * 改善計画T306: 以前はaxis_idから観測/推定/動的カテゴリを引く`categoryOf`も持っていたが、
 * 唯一の消費者だったRouteSettingsPanelのカテゴリ別グルーピング表示を撤去したのに伴い削除。
 * backendのGET /api/axis-catalogレスポンス自体には引き続き`category`フィールドが含まれる
 * （他用途・将来のプロファイル機能のため）が、このフックはそれを消費しない。 */
export function useAxisCatalog(): AxisCatalog {
  const [catalog, setCatalog] = useState<AxisCatalog>(FALLBACK_CATALOG);

  useEffect(() => {
    let cancelled = false;
    getAxisCatalog()
      .then((response) => {
        if (!cancelled && response.axes.length > 0) {
          setCatalog(buildCatalog(response.axes));
        }
      })
      .catch(() => {
        // 取得失敗時はFALLBACK_CATALOGのまま（fetchJsonが既にdebugLogへ記録済み）。
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return catalog;
}
