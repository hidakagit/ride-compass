// 二次軸の汎用rampレイヤー定義（改善計画T145b「事実はタイルに、解釈はクライアントに」）。
//
// backendのレジストリ（app/domain/registry_defaults.py）が書き出す生成物
// axis-catalog.json（export_openapi.py）を単一ソースとして、display.kind==="ramp"の軸から
// 地図レイヤー・凡例・パネル項目を自動生成する。新しい軸は、
//   1. backendのレジストリへAxisSpec（display: kind="ramp"）を登録
//   2. タイルへ事実プロパティを焼き込む（way_attribute_counts等）
// だけでフロントのコード変更なしに地図レイヤーとして現れる。
//
// rampの値は tile_inputs の線形結合（Σ property×weight。例: 停止密度 =
// stop_per_km + 0.3×intersection_per_km）で、backend側の軸内係数
// （domain/difficulty.py: UNSIGNALED_INTERSECTION_WEIGHT等）がカタログ経由で反映される
// （設計原則2: 片側import。フロントに同じ係数を手書きしない）。
// プロパティ欠損はタイル側が「0をNULLIFでキー省略」した結果なのでcoalesceで0へ倒す
// （_ROAD_SURFACE_TILE_MVT_SQLのコメント参照）。

import axisCatalog from "@/types/generated/axis-catalog.json";

export interface AxisTileInput {
  property: string;
  weight: number;
}

export interface RampAxis {
  axisId: string;
  label: string;
  category: string;
  tileInputs: readonly AxisTileInput[];
  /** 昇順の色段階境界値。値 < thresholds[0] が最も低い段階 */
  thresholds: readonly number[];
  unit: string;
  note: string;
}

interface CatalogAxis {
  axis_id: string;
  display: {
    kind: string;
    label: string;
    category: string;
    tile_inputs: { property: string; weight: number }[];
    thresholds: number[];
    unit: string;
    note: string;
  } | null;
}

export const RAMP_AXES: readonly RampAxis[] = (axisCatalog.axes as CatalogAxis[])
  .filter((axis) => axis.display?.kind === "ramp")
  .map((axis) => ({
    axisId: axis.axis_id,
    label: axis.display!.label,
    category: axis.display!.category,
    tileInputs: axis.display!.tile_inputs,
    thresholds: axis.display!.thresholds,
    unit: axis.display!.unit,
    note: axis.display!.note,
  }));

/** mapLayers.ts のレイヤーID（チップ・パネル・visibility状態のキー） */
export type AxisMapLayerId = `axis:${string}`;

export function axisMapLayerId(axisId: string): AxisMapLayerId {
  return `axis:${axisId}`;
}

/** MapLibreのlayer id（MapView内部） */
export function axisLineLayerId(axisId: string): string {
  return `region-axis-${axisId}-line`;
}

// 4段階の共有ランプ配色（低→高）。全ramp軸が同じ配色を使うことで「低=緑〜高=赤」という
// 読み方を1回覚えれば全軸に通用させる（軸ごとに独自配色を作らない）。
export const AXIS_RAMP_COLORS = ["#4caf50", "#ffb300", "#fb8c00", "#e53935"] as const;

/** tile_inputsの線形結合（Σ property×weight）のMapLibre expression */
export function buildAxisRampValueExpression(axis: RampAxis): unknown[] {
  const terms = axis.tileInputs.map((input) => [
    "*",
    ["coalesce", ["get", input.property], 0],
    input.weight,
  ]);
  if (terms.length === 1) return terms[0];
  return ["+", ...terms];
}

/** thresholdsによるstep色分けのMapLibre expression */
export function buildAxisRampColorExpression(axis: RampAxis): unknown[] {
  const expression: unknown[] = ["step", buildAxisRampValueExpression(axis), AXIS_RAMP_COLORS[0]];
  axis.thresholds.forEach((threshold, index) => {
    expression.push(threshold, AXIS_RAMP_COLORS[Math.min(index + 1, AXIS_RAMP_COLORS.length - 1)]);
  });
  return expression;
}

/** パネル・凡例用の段階ラベル（例: 「〜1回/km」「1〜2回/km」「4回/km超」） */
export function axisRampLegendEntries(axis: RampAxis): { label: string; color: string }[] {
  const t = axis.thresholds;
  return [
    { label: `${t[0]}${axis.unit}未満`, color: AXIS_RAMP_COLORS[0] },
    ...t.slice(1).map((threshold, index) => ({
      label: `${t[index]}〜${threshold}${axis.unit}`,
      color: AXIS_RAMP_COLORS[Math.min(index + 1, AXIS_RAMP_COLORS.length - 1)],
    })),
    {
      label: `${t[t.length - 1]}${axis.unit}以上`,
      color: AXIS_RAMP_COLORS[Math.min(t.length, AXIS_RAMP_COLORS.length - 1)],
    },
  ];
}
